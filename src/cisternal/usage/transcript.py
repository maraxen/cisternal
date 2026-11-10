"""Transcript parsing core for Claude Code session transcripts.

Ported/adapted from Praxia session_context_audit.py (2026).
Native cisternal implementation providing canonical tool key normalization,
compound shell CLI tokenization, recursive transcript discovery, worktree-aware
repository normalization, and session-type stratification.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Literal

_log = logging.getLogger(__name__)

ToolKey = str
SessionType = Literal["main_interactive", "subagent_headless"]


@dataclass(frozen=True, slots=True)
class VerbSpec:
    """Declaration for a CLI binary and its mapped subcommands."""

    binary: str
    subcommands: dict[str, str] = field(default_factory=dict)
    tool_family: str = ""
    global_flags_with_value: tuple[str, ...] = ()
    global_flags: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


VerbTable = Mapping[str, VerbSpec | Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    """Structured event extracted from JSONL transcripts."""

    event_type: str
    timestamp: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    raw_record: dict[str, Any] = field(default_factory=dict)


def canonical_tool_key(raw: str, declared_servers: Collection[str] = ()) -> ToolKey:
    """Resolve a raw tool name to canonical (server, tool) written 'server/tool'.

    Handles:
    - Already canonical 'server/tool' -> returns as-is.
    - Wire plugin form 'mcp__plugin_<p>_<s>__<t>' -> '<s>/<t>' using longest-suffix
      match of <s> against declared_servers. If no declared server matches, keeps
      the whole segment as server and logs an advisory.
    - Wire standalone form 'mcp__<s>__<t>' -> '<s>/<t>'.
    - Bare '<t>' -> resolves only when a single declared server is in context
      (len(declared_servers) == 1). Otherwise raises ValueError.
    - Empty or malformed inputs -> raises ValueError.
    """
    if not raw or not raw.strip():
        raise ValueError("Tool name cannot be empty")

    if "/" in raw:
        return raw

    if raw.startswith("mcp__"):
        parts = raw.split("__")
        if len(parts) < 3:
            raise ValueError(f"Malformed MCP tool name: {raw}")
        middle = parts[1]
        tool = "__".join(parts[2:])
        if not middle or not tool:
            raise ValueError(f"Malformed MCP tool name: {raw}")

        if middle.startswith("plugin_"):
            ps = middle[len("plugin_") :]
            if declared_servers:
                candidates = [
                    s for s in declared_servers if ps == s or ps.endswith(f"_{s}")
                ]
                if candidates:
                    server = max(candidates, key=len)
                    return f"{server}/{tool}"

            # Fallback if no declared servers or no match:
            # Check duplicate plugin_server prefix, e.g. bathos_bathos -> bathos
            halves = ps.split("_", 1)
            if len(halves) == 2 and halves[0] == halves[1]:
                return f"{halves[1]}/{tool}"

            _log.warning("Unresolved MCP plugin server: %s in %s", middle, raw)
            return f"{ps}/{tool}"
        return f"{middle}/{tool}"

    # Bare tool name: resolve only if single declared server is in context
    if len(declared_servers) == 1:
        return f"{next(iter(declared_servers))}/{raw}"
    if len(declared_servers) > 1:
        raise ValueError(
            f"Ambiguous bare tool {raw!r} with multiple declared servers: {declared_servers}"
        )
    raise ValueError(
        f"Bare tool {raw!r} cannot be resolved without declared server context"
    )


def _split_compound_command(cmd: str) -> list[str]:
    """Split cmd on unquoted &&, ||, ;, |, &, \n.

    Fails open by returning [] if quotes are unclosed.
    Ignores & when part of redirections (2>&1, >&, <&).
    """
    segments: list[str] = []
    current: list[str] = []
    i = 0
    n = len(cmd)
    in_single = False
    in_double = False

    while i < n:
        ch = cmd[i]

        if in_single:
            if ch == "'":
                in_single = False
            current.append(ch)
            i += 1
            continue

        if in_double:
            if ch == "\\":
                if i + 1 < n:
                    current.append(ch)
                    current.append(cmd[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                in_double = False
            current.append(ch)
            i += 1
            continue

        # Outside quotes
        if ch == "\\":
            if i + 1 < n:
                current.append(ch)
                current.append(cmd[i + 1])
                i += 2
                continue
        elif ch == "'":
            in_single = True
            current.append(ch)
            i += 1
            continue
        elif ch == '"':
            in_double = True
            current.append(ch)
            i += 1
            continue

        # Check 2-character operators: &&, ||
        if i + 1 < n and cmd[i : i + 2] in ("&&", "||"):
            seg = "".join(current).strip()
            if seg:
                segments.append(seg)
            current = []
            i += 2
            continue

        # Check 1-character operators: ;, |, \n
        if ch in (";", "\n", "|"):
            seg = "".join(current).strip()
            if seg:
                segments.append(seg)
            current = []
            i += 1
            continue

        # Check operator: & (differentiating from redirections like 2>&1, >&, <&)
        if ch == "&":
            prev_str = "".join(current).rstrip()
            if prev_str.endswith(">") or prev_str.endswith("<"):
                current.append(ch)
                i += 1
                continue
            seg = "".join(current).strip()
            if seg:
                segments.append(seg)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    if in_single or in_double:
        # Unclosed quotes fail-open -> []
        return []

    seg = "".join(current).strip()
    if seg:
        segments.append(seg)

    return segments


def _has_unquoted_substitution_before(seg: str, pos: int) -> bool:
    """Check if seg contains unquoted $( or backtick before index pos."""
    in_s = False
    in_d = False
    i = 0
    limit = min(pos, len(seg))
    while i < limit:
        ch = seg[i]
        if in_s:
            if ch == "'":
                in_s = False
            i += 1
            continue
        if in_d:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_d = False
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == "'":
            in_s = True
            i += 1
            continue
        if ch == '"':
            in_d = True
            i += 1
            continue
        if ch == "`":
            return True
        if ch == "$" and i + 1 < limit and seg[i + 1] == "(":
            return True
        i += 1
    return False


def _get_verb_field(
    spec: VerbSpec | Mapping[str, Any], name: str, default: Any = None
) -> Any:
    if isinstance(spec, Mapping):
        return spec.get(name, default)
    return getattr(spec, name, default)


def parse_cli_commands(cmd: str, verbs: VerbTable) -> list[tuple[str, str]]:
    """Parse compound shell command into recognized (binary, subcommand) pairs.

    Splits compound commands on unquoted operators (&&, ||, ;, |, &, \\n),
    strips shell wrappers (rtk, just, env, sudo, time, nice, nohup, timeout, path prefixes),
    handles global flags (consuming values where declared), skips segments with
    unknown flags or unquoted command substitutions before the verb, and fails open.
    """
    segments = _split_compound_command(cmd)
    if not segments:
        return []

    results: list[tuple[str, str]] = []

    for seg in segments:
        try:
            tokens = shlex.split(seg)
        except ValueError:
            continue

        if not tokens:
            continue

        # Strip prefix wrappers
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]
            # VAR=val assignments
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*", tok):
                idx += 1
                continue
            # Simple wrappers
            if tok in ("rtk", "just", "time", "nohup", "command", "builtin"):
                idx += 1
                continue
            # sudo wrapper: sudo [-u user] [-g group] [-p prompt] [-D dir] [-E] [-i] [-s] [-n] [-H] [-b] etc.
            if tok == "sudo":
                idx += 1
                while idx < len(tokens):
                    sub = tokens[idx]
                    if sub == "--":
                        idx += 1
                        break
                    if sub in (
                        "-u",
                        "-g",
                        "-p",
                        "-C",
                        "-h",
                        "-r",
                        "-t",
                        "-T",
                        "-D",
                        "--user",
                        "--group",
                        "--prompt",
                        "--chdir",
                        "--role",
                        "--type",
                        "--close-from",
                        "--command-timeout",
                    ):
                        idx += 2
                        continue
                    if (
                        sub.startswith("--user=")
                        or sub.startswith("--group=")
                        or sub.startswith("--prompt=")
                        or sub.startswith("--chdir=")
                    ):
                        idx += 1
                        continue
                    if sub.startswith("-") and not sub.startswith("--"):
                        if sub.startswith("-u") and len(sub) > 2:
                            idx += 1
                            continue
                        if sub.startswith("-g") and len(sub) > 2:
                            idx += 1
                            continue
                        if any(c in sub for c in ("u", "g", "p", "D", "C", "T")):
                            idx += 2
                            continue
                        idx += 1
                        continue
                    if sub.startswith("--"):
                        idx += 1
                        continue
                    break
                continue
            # env wrapper: env [-i] [-u VAR] [VAR=val ...]
            if tok == "env":
                idx += 1
                while idx < len(tokens):
                    sub = tokens[idx]
                    if sub in ("-i", "-0", "--null") or sub.startswith("-u"):
                        idx += 1
                        if sub == "-u" and idx < len(tokens):
                            idx += 1
                    elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*", sub):
                        idx += 1
                    else:
                        break
                continue
            # nice wrapper: nice [-n increment]
            if tok == "nice":
                idx += 1
                if idx < len(tokens):
                    if tokens[idx] == "-n":
                        idx += 2
                    elif re.match(r"^-\d+$", tokens[idx]):
                        idx += 1
                continue
            # timeout wrapper: timeout [-s sig] duration
            if tok == "timeout":
                idx += 1
                while idx < len(tokens) and tokens[idx].startswith("-"):
                    if tokens[idx] in ("-s", "-k", "--signal", "--kill-after"):
                        idx += 2
                    else:
                        idx += 1
                if idx < len(tokens) and not tokens[idx].startswith("-"):
                    idx += 1
                continue

            break

        if idx >= len(tokens):
            continue

        raw_bin = tokens[idx]
        bin_name = Path(raw_bin).name

        if bin_name not in verbs:
            continue

        # Check for unquoted $( or backtick before binary token in seg
        bin_pos = seg.find(raw_bin)
        if bin_pos != -1 and _has_unquoted_substitution_before(seg, bin_pos):
            continue

        spec = verbs[bin_name]
        flags_with_val = set(_get_verb_field(spec, "global_flags_with_value", ()))
        flags_valueless = set(_get_verb_field(spec, "global_flags", ()))
        subcommands = _get_verb_field(spec, "subcommands", {})
        exclude = set(_get_verb_field(spec, "exclude", ()))

        # Process tokens after binary
        j = idx + 1
        subcommand_found = None
        while j < len(tokens):
            arg = tokens[j]
            flag, eq, _ = arg.partition("=")
            if eq:
                if flag in flags_with_val:
                    j += 1
                    continue
                if flag.startswith("-"):
                    # Unknown flag preceding subcommand -> skip segment fail-open
                    break
            else:
                if arg in flags_with_val:
                    j += 2
                    continue
                if arg in flags_valueless:
                    j += 1
                    continue
                if arg.startswith("-"):
                    # Unknown flag preceding subcommand -> skip segment fail-open
                    break

            # Non-flag token: candidate subcommand
            if isinstance(subcommands, Mapping):
                is_sub = arg in subcommands
            else:
                is_sub = arg in set(subcommands)

            if is_sub or arg in exclude:
                subcommand_found = arg
            break

        if subcommand_found is not None:
            results.append((bin_name, subcommand_found))

    return results


def parse_cli_command(cmd: str, verbs: VerbTable) -> tuple[str, str] | None:
    """Return the first matched (binary, subcommand) pair, or None."""
    matches = parse_cli_commands(cmd, verbs)
    return matches[0] if matches else None


def discover_transcript_files(projects_root: Path) -> Iterator[tuple[str, Path]]:
    """Recursively discover Claude Code session transcripts.

    Yields (slug, path) for:
    - Main session transcripts: <projects_root>/<slug>/*.jsonl
    - Subagent transcripts: <projects_root>/<slug>/<session_id>/subagents/*.jsonl
    """
    if not projects_root.exists() or not projects_root.is_dir():
        return

    for slug_dir in sorted(projects_root.iterdir()):
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name

        # Main session transcripts
        for main_file in sorted(slug_dir.glob("*.jsonl")):
            if main_file.is_file():
                yield (slug, main_file)

        # Subagent transcripts
        for sub_file in sorted(slug_dir.glob("*/subagents/*.jsonl")):
            if sub_file.is_file():
                yield (slug, sub_file)


_GIT_COMMON_DIR_CACHE: dict[str, str] = {}


def resolve_repo_key(session_cwd: str | None, slug: str) -> str:
    """Normalize worktree sessions to parent repository key.

    Strips `/.claude/worktrees/<name>` and `/.worktrees/<name>` from session_cwd;
    resolves git-common-dir parent when path is on disk; falls back to stripping
    `--claude-worktrees-<suffix>` from slug.
    """
    if session_cwd:
        stripped = re.sub(
            r"/(?:\.claude/worktrees|\.worktrees)/[^/]+(?:/.*)?$", "", session_cwd
        )
        path = Path(stripped)
        if path.exists():
            path_str = str(path.resolve())
            if path_str in _GIT_COMMON_DIR_CACHE:
                return _GIT_COMMON_DIR_CACHE[path_str]
            try:
                res = subprocess.run(
                    [
                        "git",
                        "-C",
                        path_str,
                        "rev-parse",
                        "--path-format=absolute",
                        "--git-common-dir",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=2,
                )
                if res.returncode == 0:
                    common_dir = res.stdout.strip()
                    if common_dir:
                        parent = str(Path(common_dir).parent)
                        _GIT_COMMON_DIR_CACHE[path_str] = parent
                        return parent
            except Exception:
                pass
            _GIT_COMMON_DIR_CACHE[path_str] = path_str
            return path_str
        if not slug:
            return stripped

    # Fallback to slug normalization
    clean_slug = re.sub(r"--(?:claude-)?worktrees-.*$", "", slug)
    return clean_slug


def stratify_session_type(
    events: Iterable[TranscriptEvent | dict[str, Any]],
    path: Path,
) -> SessionType:
    """Stratify session into main_interactive vs subagent_headless.

    Checks path for /subagents/ first, then checks events for isSidechain is True
    or session_type == 'subagent'. Takes an iterable of TranscriptEvent or dict records.
    """
    if "subagents" in path.parts:
        return "subagent_headless"

    for item in events:
        rec = item.raw_record if isinstance(item, TranscriptEvent) else item
        if not isinstance(rec, dict):
            continue
        if rec.get("isSidechain") is True or rec.get("session_type") == "subagent":
            return "subagent_headless"

    return "main_interactive"


def stream_transcript_events(path: Path) -> Iterator[TranscriptEvent]:
    """Stream TranscriptEvent records from a JSONL transcript file.

    Extracts tool_use, tool_result, skill_listing, invoked_skills,
    and deferred_tools records.
    """
    if not path.is_file():
        return

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue

            event_type = str(rec.get("type") or rec.get("event") or "unknown")
            timestamp = rec.get("timestamp") or rec.get("ts")
            yield TranscriptEvent(
                event_type=event_type,
                timestamp=str(timestamp) if timestamp else None,
                payload=rec.get("payload") or rec.get("data") or rec,
                raw_record=rec,
            )
