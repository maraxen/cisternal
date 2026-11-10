"""Asset guidance-coverage and structural validation lints (Spec §C2, §C4a)."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection
from pathlib import Path

import yaml

from cisternal.assets.bundle import AssetBundle, SkillAsset
from cisternal.usage.transcript import canonical_tool_key

C4A_STOPWORDS: frozenset[str] = frozenset(
    {
        "for",
        "with",
        "when",
        "use",
        "audit",
        "tools",
        "support",
        "handling",
        "session",
        "manage",
        "agent-asset",
        "read-only",
        "non-empty",
        "case-insensitive",
        "single-repo",
        "fail-open",
        "warn-only",
        "in-band",
        "client-side",
        "server-side",
        "per-session",
        "per-repo",
        "short-description",
        "tool-surface",
        "cli-to-mcp",
    }
)

_BACKTICK_LITERAL_RE = re.compile(r"`([a-zA-Z0-9_\-\.:/]+)`")
_PASCAL_RE = re.compile(r"\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b")
_CAMEL_RE = re.compile(r"\b[a-z0-9]+[A-Z][A-Za-z0-9]*\b")
_HYPHEN_UNDERSCORE_RE = re.compile(r"\b[a-z0-9]+(?:[-_][a-z0-9]+)+\b", re.IGNORECASE)

_RAW_MCP_RE = re.compile(
    r"^mcp__(?:plugin_[a-zA-Z0-9_-]+_)?([a-zA-Z0-9_-]+)__([a-zA-Z0-9_-]+)$"
)
_SERVER_TOOL_RE = re.compile(r"^([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)$")
_INLINE_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def strip_code_fences(text: str) -> str:
    """Remove fenced code blocks (```...``` and ~~~...~~~) from markdown text.

    Uses a robust line-by-line scanner to guarantee O(N) execution without
    regex backtracking risk.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_fence: str | None = None
    fence_len: int = 0

    for line in lines:
        stripped = line.strip()
        if in_fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                char = stripped[0]
                length = len(stripped) - len(stripped.lstrip(char))
                if length >= 3:
                    in_fence = char
                    fence_len = length
                    continue
            out.append(line)
        else:
            if stripped.startswith(in_fence):
                length = len(stripped) - len(stripped.lstrip(in_fence))
                if length >= fence_len:
                    in_fence = None
                    continue
            continue

    return "".join(out)


def build_hermetic_tool_index(bundle: AssetBundle) -> tuple[set[str], set[str]]:
    """Derive hermetic known_tools and declared_servers sets from AssetBundle.

    - known_tools: union of canonical keys from bundle.families, bundle.verbs,
      and bundle.commands (formatted as '<plugin.name>/<command.name>').
    - declared_servers: server prefixes from known_tools plus bundle.mcp_servers names.
    """
    known_tools: set[str] = set()

    for tools in bundle.families.values():
        known_tools.update(tools)

    for verb_data in bundle.verbs.values():
        if isinstance(verb_data, dict):
            subcommands = verb_data.get("subcommands", {})
            if isinstance(subcommands, dict):
                known_tools.update(subcommands.values())
        elif hasattr(verb_data, "subcommands") and isinstance(
            verb_data.subcommands, dict
        ):
            known_tools.update(verb_data.subcommands.values())

    plugin_name = bundle.metadata.name or "cisternal"
    for cmd in bundle.commands:
        known_tools.add(f"{plugin_name}/{cmd.name}")

    declared_servers: set[str] = {
        tool.split("/", 1)[0] for tool in known_tools if "/" in tool
    }
    for srv in bundle.mcp_servers:
        declared_servers.add(srv.name)

    return known_tools, declared_servers


def extract_quoted_tool_candidates(
    text: str, declared_servers: Collection[str]
) -> list[tuple[str, str]]:
    """Extract candidate (raw_token, canonical_key) from markdown prose.

    Filters tokens:
    - Raw MCP format: mcp__...__... -> canonicalized via canonical_tool_key
    - Server/tool format: server/tool -> only if server in declared_servers
    - Bare words or paths with non-server prefix -> ignored
    """
    cleaned = strip_code_fences(text)
    raw_tokens = _INLINE_BACKTICK_RE.findall(cleaned)
    candidates: list[tuple[str, str]] = []

    for raw in raw_tokens:
        token = raw.strip().removesuffix("()")
        if not token:
            continue

        if _RAW_MCP_RE.match(token):
            try:
                canonical = canonical_tool_key(token, declared_servers=declared_servers)
                candidates.append((token, canonical))
            except ValueError:
                candidates.append((token, token))
            continue

        st_match = _SERVER_TOOL_RE.match(token)
        if st_match:
            server, tool = st_match.groups()
            if server in declared_servers:
                candidates.append((token, f"{server}/{tool}"))

    return candidates


def check_uncovered_families(bundle: AssetBundle) -> list[str]:
    """Emit advisories for any declared family with 0 covering skills."""
    if not bundle.families:
        return []

    covered: set[str] = {
        fam for skill in bundle.skills for fam in skill.covers_families
    }

    advisories: list[str] = []
    for fam_name in sorted(bundle.families.keys()):
        if fam_name not in covered:
            advisories.append(
                f"family {fam_name!r} has no covering skill (declared in [families] "
                f"but not listed in any skill's covers_families)"
            )
    return advisories


def check_dangling_tool_names(bundle: AssetBundle) -> list[str]:
    """Emit fatal warnings for quoted tool names absent from the hermetic known-tool set.

    A reference is judged only when its server has a known tool inventory in this
    bundle (families, verbs or registry commands). A tool of another plugin's
    server -- or of a server whose tools this bundle never lists -- cannot be
    called dangling hermetically, so it is not reported.
    """
    known_tools, declared_servers = build_hermetic_tool_index(bundle)
    inventoried_servers = {t.split("/", 1)[0] for t in known_tools if "/" in t}
    warnings: list[str] = []

    for skill in bundle.skills:
        texts_to_scan = [skill.description, skill.when_to_use, skill.body]
        for rel_path, content in skill.resources:
            if rel_path.endswith(".md") or rel_path.endswith(".txt"):
                texts_to_scan.append(content)

        candidates: list[tuple[str, str]] = []
        for text in texts_to_scan:
            candidates.extend(extract_quoted_tool_candidates(text, declared_servers))

        # Check allowed_tools and disallowed_tools
        for tool_list in (skill.allowed_tools, skill.disallowed_tools):
            for item in tool_list:
                item_str = str(item).strip()
                if _RAW_MCP_RE.match(item_str):
                    try:
                        canonical = canonical_tool_key(
                            item_str, declared_servers=declared_servers
                        )
                        candidates.append((item_str, canonical))
                    except ValueError:
                        candidates.append((item_str, item_str))
                else:
                    st_match = _SERVER_TOOL_RE.match(item_str)
                    if st_match:
                        s, t = st_match.groups()
                        if s in declared_servers:
                            candidates.append((item_str, f"{s}/{t}"))

        seen_dangling: set[str] = set()
        for raw_token, canonical in candidates:
            server = canonical.split("/", 1)[0] if "/" in canonical else ""
            if server not in inventoried_servers:
                continue
            if canonical not in known_tools and raw_token not in seen_dangling:
                seen_dangling.add(raw_token)
                warnings.append(
                    f"skill {skill.name!r}: quotes dangling tool name {raw_token!r} "
                    f"(canonical key {canonical!r} is not declared in known tools)"
                )

    return warnings


def validate_bundle_guidance(
    bundle: AssetBundle,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Run all C2 guidance-coverage lints. Returns (warnings, advisories)."""
    warnings = tuple(check_dangling_tool_names(bundle))
    advisories = tuple(check_uncovered_families(bundle))
    return warnings, advisories


def check_distinctive_strings_containment(skill: SkillAsset) -> list[str]:
    """Check (a): Frontmatter distinctive_strings appear in listing text or body."""
    if not skill.distinctive_strings:
        return []
    listing_text = f"{skill.description} {skill.effective_when_to_use}".lower()
    body_text = skill.body.lower()
    combined = f"{listing_text}\n{body_text}"

    warnings: list[str] = []
    for s in skill.distinctive_strings:
        s_clean = s.strip()
        if not s_clean:
            continue
        if s_clean.lower() not in combined:
            warnings.append(
                f"skill {skill.name!r}: distinctive string {s!r} not found in listing text or body"
            )
    return warnings


def check_baseline_capability_erosion(
    bundle: AssetBundle,
    baseline_ref: str,
    manifest_path: Path | None = None,
    cwd: Path | None = None,
) -> list[str]:
    """Check (a) baseline: baseline distinctive strings retained in listing, body, or references.

    Skill paths in a manifest are plugin-root-relative (the manifest's
    ``<root>/.praxia/manifest.toml`` layout, as :class:`ManifestAssetSource`
    reads them). Git is run from the plugin root and each blob is addressed as
    ``<ref>:./<path>`` -- relative to that directory, not the repository root --
    so a plugin nested in a larger repository resolves the same files.
    """
    import os  # noqa: PLC0415
    import tomllib  # noqa: PLC0415

    plugin_root: Path | None = None
    if manifest_path and manifest_path.is_file():
        plugin_root = manifest_path.resolve().parent.parent
    work_dir = (cwd or plugin_root or Path.cwd()).resolve()
    path_root = plugin_root or work_dir

    # Verify baseline ref
    rev_res = subprocess.run(
        ["git", "rev-parse", "--verify", f"{baseline_ref}^{{commit}}"],
        capture_output=True,
        text=True,
        cwd=work_dir,
    )
    if rev_res.returncode != 0:
        raise ValueError(f"invalid baseline ref: {baseline_ref}")

    # Map skill name to its plugin-root-relative path
    skill_paths: dict[str, str] = {}
    if manifest_path and manifest_path.is_file():
        try:
            with open(manifest_path, "rb") as f:
                data = tomllib.load(f)
            plugin = data.get("plugin", {})
            for entry in plugin.get("skills", []):
                if isinstance(entry, dict) and entry.get("name") and entry.get("path"):
                    skill_paths[str(entry["name"])] = str(entry["path"])
        except (OSError, tomllib.TOMLDecodeError, AttributeError, TypeError):
            pass

    warnings: list[str] = []
    for skill in bundle.skills:
        rel_to_root = skill_paths.get(
            skill.name, f".praxia/skills/{skill.name}/SKILL.md"
        )
        skill_file = path_root / rel_to_root
        if (
            not skill_file.exists()
            and manifest_path is not None
            and (manifest_path.resolve().parent / rel_to_root).exists()
        ):
            # Tolerate manifest-dir-relative entries (not what the loader reads).
            skill_file = manifest_path.resolve().parent / rel_to_root
        rel_to_cwd = Path(os.path.relpath(skill_file, work_dir)).as_posix()
        # "./" or "../" makes git resolve the path against cwd, not the repo root.
        prefix = "" if rel_to_cwd.startswith("../") else "./"
        blob = f"{baseline_ref}:{prefix}{rel_to_cwd}"

        # Check if skill existed at baseline ref
        cat_res = subprocess.run(
            ["git", "cat-file", "-e", blob],
            capture_output=True,
            text=True,
            cwd=work_dir,
        )
        if cat_res.returncode != 0:
            # Skill did not exist at baseline ref; skip baseline check
            continue

        show_res = subprocess.run(
            ["git", "show", blob],
            capture_output=True,
            text=True,
            cwd=work_dir,
        )
        if show_res.returncode != 0:
            continue

        from cisternal.assets.manifest import _split_frontmatter

        fm, _ = _split_frontmatter(show_res.stdout)
        if not fm.strip():
            continue

        try:
            doc = yaml.safe_load(fm)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue

        baseline_strings = doc.get("distinctive_strings", [])
        if isinstance(baseline_strings, (list, tuple)):
            current_corpus = [
                skill.description,
                skill.effective_when_to_use,
                skill.body,
            ]
            for _, res_content in skill.resources:
                current_corpus.append(res_content)
            combined = "\n".join(current_corpus).lower()

            for base_str in baseline_strings:
                base_str_clean = str(base_str).strip()
                if not base_str_clean:
                    continue
                if base_str_clean.lower() not in combined:
                    warnings.append(
                        f"CAPABILITY_EROSION_DETECTED: skill {skill.name!r} removed baseline "
                        f"distinctive string {base_str_clean!r} without retention in listing, body, or references"
                    )

    return warnings


def extract_headings(text: str) -> list[str]:
    """Extract heading text lines (# Heading, ## Subheading, etc.)."""
    headings: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if m:
            headings.append(m.group(1))
    return headings


def extract_fenced_code_blocks(text: str) -> list[str]:
    """Extract content inside fenced code blocks (```...``` or ~~~...~~~)."""
    blocks: list[str] = []
    in_fence: str | None = None
    fence_len: int = 0
    curr: list[str] = []

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if in_fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                char = stripped[0]
                length = len(stripped) - len(stripped.lstrip(char))
                if length >= 3:
                    in_fence = char
                    fence_len = length
                    curr = []
        else:
            if stripped.startswith(in_fence):
                length = len(stripped) - len(stripped.lstrip(in_fence))
                if length >= fence_len:
                    in_fence = None
                    blocks.append("".join(curr))
                    curr = []
                    continue
            curr.append(line)

    return blocks


def check_listing_no_overclaim(skill: SkillAsset) -> list[str]:
    """Check (b): Verify candidate topic tokens from listing are grounded in body or references."""
    listing_text = f"{skill.description} {skill.effective_when_to_use}"
    clean_listing = strip_code_fences(listing_text)

    # Distinctive strings to shield
    distinctive_tokens: set[str] = set()
    for ds in skill.distinctive_strings:
        distinctive_tokens.add(ds.lower())
        for w in re.findall(r"[a-zA-Z0-9_-]+", ds.lower()):
            distinctive_tokens.add(w)

    # 1. Backticked tokens
    backticked_raw = _INLINE_BACKTICK_RE.findall(clean_listing)
    backticked_tokens: list[str] = []
    for b in backticked_raw:
        token = b.strip().removesuffix("()")
        if not token or " " in token:
            continue
        if not re.match(r"^[a-zA-Z0-9_\-\.:/]+$", token):
            continue
        if token.lower() in C4A_STOPWORDS or token.lower() in distinctive_tokens:
            continue
        backticked_tokens.append(token)

    # 2. Non-backticked tokens (PascalCase, camelCase, hyphenated/underscored)
    no_backticks = _INLINE_BACKTICK_RE.sub(" ", clean_listing)
    non_backticked_candidates: set[str] = set()

    for m in _PASCAL_RE.finditer(no_backticks):
        tok = m.group(0)
        if tok.lower() not in C4A_STOPWORDS and tok.lower() not in distinctive_tokens:
            non_backticked_candidates.add(tok)

    for m in _CAMEL_RE.finditer(no_backticks):
        tok = m.group(0)
        if tok.lower() not in C4A_STOPWORDS and tok.lower() not in distinctive_tokens:
            non_backticked_candidates.add(tok)

    for m in _HYPHEN_UNDERSCORE_RE.finditer(no_backticks):
        tok = m.group(0)
        if tok.lower() not in C4A_STOPWORDS and tok.lower() not in distinctive_tokens:
            non_backticked_candidates.add(tok)

    # Corpus preparation
    all_texts = [skill.body] + [content for _, content in skill.resources]
    full_corpus = "\n".join(all_texts)

    headings: list[str] = []
    fences: list[str] = []
    inline_spans: list[str] = []
    for txt in all_texts:
        headings.extend(extract_headings(txt))
        fences.extend(extract_fenced_code_blocks(txt))
        inline_spans.extend(_INLINE_BACKTICK_RE.findall(strip_code_fences(txt)))

    grounding_corpus = "\n".join(headings + fences + inline_spans)

    warnings: list[str] = []

    # Verify backticked tokens (pass if anywhere in body or references)
    for tok in sorted(set(backticked_tokens)):
        pattern = rf"(?<![a-zA-Z0-9_-]){re.escape(tok)}(?![a-zA-Z0-9_-])"
        if not re.search(pattern, full_corpus, re.IGNORECASE):
            warnings.append(
                f"skill {skill.name!r}: listing quotes token `{tok}` without appearance in body or references"
            )

    # Verify non-backticked tokens (must match headings, fences, or inline code)
    for tok in sorted(non_backticked_candidates):
        pattern = rf"(?<![a-zA-Z0-9_-]){re.escape(tok)}(?![a-zA-Z0-9_-])"
        if not re.search(pattern, grounding_corpus, re.IGNORECASE):
            warnings.append(
                f"skill {skill.name!r}: listing claims topic token {tok!r} without heading, code fence, or inline code grounding in body or references"
            )

    return warnings


def check_scope_header(skill: SkillAsset) -> list[str]:
    """Check (c): '## Scope' or '## When to Use' heading within first 50 lines and 2,000 characters."""
    lines = skill.body.splitlines()[:50]
    char_offset = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"^##\s+(?:scope|when\s+to\s+use)\b", stripped, re.IGNORECASE):
            if char_offset < 2000:
                return []
            return [
                f"skill {skill.name!r}: '## Scope' or '## When to Use' heading found "
                f"at character offset {char_offset}, exceeding 2000 character limit"
            ]
        char_offset += len(line) + 1
    return [
        f"skill {skill.name!r}: missing '## Scope' or '## When to Use' heading "
        "within first 50 body lines and 2000 characters"
    ]


def validate_bundle_honesty(
    bundle: AssetBundle,
    manifest_path: Path | None = None,
    baseline_ref: str | None = None,
    report_only: bool = False,
    cwd: Path | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Run all C4a static honesty lints. Returns (warnings, advisories)."""
    findings: list[str] = []

    for skill in bundle.skills:
        if not skill.distinctive_strings:
            continue
        findings.extend(check_distinctive_strings_containment(skill))
        findings.extend(check_listing_no_overclaim(skill))
        findings.extend(check_scope_header(skill))

    if baseline_ref:
        findings.extend(
            check_baseline_capability_erosion(
                bundle,
                baseline_ref,
                manifest_path=manifest_path,
                cwd=cwd,
            )
        )

    if report_only:
        return (), tuple(findings)
    return tuple(findings), ()
