"""Manifest-driven asset source (M3.1a spec L4, L12)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    HookSpecAsset,
    LoadReport,
    MarketplaceAsset,
    McpAsset,
    SkillAsset,
)
from cisternal.assets.manifest_commands import load_export_commands
from cisternal.assets.manifest_extensions import validate_extension_sections

class ManifestAssetSource:
    """Load assets from a praxia-style ``.praxia/manifest.toml`` file."""

    def __init__(self, manifest_path: Path | str) -> None:
        self._manifest_path = Path(manifest_path)
        self._root = self._manifest_path.parent

    def load(self) -> LoadReport:
        warnings: list[str] = []
        try:
            raw = tomllib.loads(self._manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            warnings.append(f"manifest unreadable: {self._manifest_path}: {exc}")
            return _empty_report(warnings)
        except tomllib.TOMLDecodeError as exc:
            warnings.append(f"manifest TOML invalid: {exc}")
            return _empty_report(warnings)

        plugin = raw.get("plugin")
        if not isinstance(plugin, dict):
            warnings.append("manifest missing [plugin] table")
            return _empty_report(warnings)

        name = str(plugin.get("name") or "")
        version = str(plugin.get("version") or "0.0.0")
        description = str(plugin.get("description") or "")
        if not name:
            warnings.append("plugin.name is empty")

        metadata = BundleMetadata(name=name or "unknown", version=version, description=description)

        skills = _load_skills(plugin, self._root, warnings)
        agents = _load_agents(plugin, self._root, warnings)
        hook_specs = _load_hook_specs(plugin, self._root, warnings)
        mcp_servers = _load_mcp(plugin, name)
        marketplace = _load_marketplace(plugin, name)
        commands = load_export_commands(plugin, self._root, warnings)
        warnings.extend(validate_extension_sections(plugin, self._root))

        bundle = AssetBundle(
            metadata=metadata,
            commands=commands,
            mcp_servers=mcp_servers,
            skills=skills,
            agents=agents,
            hook_specs=hook_specs,
            marketplace=marketplace,
        )
        return LoadReport(bundle=bundle, warnings=tuple(warnings))


def _empty_report(warnings: list[str]) -> LoadReport:
    meta = BundleMetadata(name="unknown", version="0.0.0")
    return LoadReport(bundle=AssetBundle(metadata=meta), warnings=tuple(warnings))


def _read_text(path: Path, warnings: list[str], label: str) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"{label}: missing or unreadable: {path}: {exc}")
        return None


_SKILL_RESOURCE_DIRS = ("references", "scripts", "assets")


def _load_skill_resources(skill_dir: Path, name: str, warnings: list[str]) -> tuple[tuple[str, str], ...]:
    """Walk a skill's ``references/``/``scripts/``/``assets/`` sibling dirs.

    Returns ``(relative_path, content)`` pairs, forward-slash paths, sorted
    for determinism. Non-UTF-8 files are skipped with a warning rather than
    raising (fail-open, matching ``_read_text``'s convention) — a binary
    asset (e.g. a real image) isn't supported by this text-only bundle
    format yet, but one bad file shouldn't drop the rest of the skill.
    """
    resources: list[tuple[str, str]] = []
    for subdir_name in _SKILL_RESOURCE_DIRS:
        subdir = skill_dir / subdir_name
        if not subdir.is_dir():
            continue
        for path in sorted(subdir.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"skill {name!r}: unreadable resource {path}: {exc}")
                continue
            resources.append((path.relative_to(skill_dir).as_posix(), content))
    return tuple(resources)


def _load_skills(
    plugin: dict[str, object],
    root: Path,
    warnings: list[str],
) -> tuple[SkillAsset, ...]:
    entries = plugin.get("skills")
    if not isinstance(entries, list):
        return ()
    skills: list[SkillAsset] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        rel = str(entry.get("path") or "")
        if not name or not rel:
            warnings.append(f"skill entry missing name or path: {entry!r}")
            continue
        skill_path = root / rel
        text = _read_text(skill_path, warnings, f"skill {name!r}")
        raw = text if text is not None else ""

        # Strip any existing SKILL.md frontmatter (mirrors _load_agents /
        # _parse_agent_markdown) so format_skill_markdown's own frontmatter
        # block on export isn't doubled up with the source file's own.
        fm, body = _split_frontmatter(raw)

        manifest_description = str(entry.get("description") or "")
        description = manifest_description or _parse_scalar_field(fm, "description")

        manifest_triggers = entry.get("triggers")
        triggers: tuple[str, ...] = ()
        if isinstance(manifest_triggers, list) and manifest_triggers:
            triggers = tuple(str(t) for t in manifest_triggers)

        resources = _load_skill_resources(skill_path.parent, name, warnings)

        skills.append(
            SkillAsset(
                name=name,
                description=description,
                body=body,
                triggers=triggers,
                resources=resources,
            )
        )
    return tuple(skills)


def _load_agents(
    plugin: dict[str, object],
    root: Path,
    warnings: list[str],
) -> tuple[AgentAsset, ...]:
    entries = plugin.get("agents")
    if not isinstance(entries, list):
        return ()
    agents: list[AgentAsset] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        rel = str(entry.get("path") or "")
        if not name or not rel:
            warnings.append(f"agent entry missing name or path: {entry!r}")
            continue
        manifest_tools = entry.get("tools")
        tools_from_manifest: tuple[str, ...] = ()
        if isinstance(manifest_tools, list) and manifest_tools:
            tools_from_manifest = tuple(str(t) for t in manifest_tools)

        text = _read_text(root / rel, warnings, f"agent {name!r}")
        if text is None:
            agents.append(AgentAsset(name=name, tools=tools_from_manifest))
            continue

        fm_tools, body = _parse_agent_markdown(text)
        tools = tools_from_manifest if tools_from_manifest else fm_tools
        desc = str(entry.get("description") or "") or None
        agents.append(
            AgentAsset(
                name=name,
                description=desc or "",
                tools=tools,
                body=body,
            )
        )
    return tuple(agents)


def _load_hook_specs(
    plugin: dict[str, object],
    root: Path,
    warnings: list[str],
) -> tuple[HookSpecAsset, ...]:
    entries = plugin.get("hook_specs")
    if not isinstance(entries, list):
        return ()
    specs: list[HookSpecAsset] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        event = str(entry.get("event") or "")
        matcher = str(entry.get("matcher") or "")
        script = str(entry.get("script") or "")
        if not event or not script:
            continue
        tier = str(entry.get("tier") or "")
        surfaces_raw = entry.get("surfaces")
        surfaces: tuple[str, ...] = ()
        if isinstance(surfaces_raw, list):
            surfaces = tuple(str(s) for s in surfaces_raw)

        content = ""
        rel = str(entry.get("path") or "")
        if rel:
            text = _read_text(root / rel, warnings, f"hook script {script!r}")
            content = text if text is not None else ""

        specs.append(
            HookSpecAsset(
                event=event,
                matcher=matcher,
                script=script,
                tier=tier,
                surfaces=surfaces,
                content=content,
            )
        )
    return tuple(specs)


def _load_mcp(plugin: dict[str, object], plugin_name: str) -> tuple[McpAsset, ...]:
    mcp = plugin.get("mcp")
    if not isinstance(mcp, dict):
        return ()
    command = mcp.get("command")
    if not isinstance(command, list) or not command:
        return ()
    argv = tuple(str(part) for part in command)
    return (McpAsset(name=plugin_name or "mcp", command=argv),)


def _load_marketplace(plugin: dict[str, object], plugin_name: str) -> MarketplaceAsset | None:
    marketplace = plugin.get("marketplace")
    if not isinstance(marketplace, dict):
        return None
    name = str(marketplace.get("name") or plugin_name or "")
    if not name:
        return None
    owner = marketplace.get("owner")
    owner_name = owner_email = owner_url = ""
    if isinstance(owner, dict):
        owner_name = str(owner.get("name") or "")
        owner_email = str(owner.get("email") or "")
        owner_url = str(owner.get("url") or "")
    return MarketplaceAsset(
        name=name,
        owner_name=owner_name,
        owner_email=owner_email,
        owner_url=owner_url,
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a markdown asset source into (frontmatter, body).

    Shared by ``_load_agents``/``_parse_agent_markdown`` and ``_load_skills``
    so both asset kinds strip a source file's own ``---`` frontmatter block
    the same way before re-wrapping it in the exporter's own frontmatter
    (avoids doubled/malformed frontmatter on export).

    If ``text`` does not start with a ``---`` delimiter, or the delimiter is
    never closed, frontmatter is ``""`` and body is the original text
    unchanged.
    """
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    fm = parts[1]
    body = parts[2].lstrip("\n")
    return fm, body


def _parse_agent_markdown(text: str) -> tuple[tuple[str, ...], str]:
    """Return (default_tools, body_without_frontmatter)."""
    fm, body = _split_frontmatter(text)
    return _parse_default_tools(fm), body


def _parse_scalar_field(frontmatter: str, field: str) -> str:
    """Return a single-line ``field: value`` from a frontmatter block, or "".

    Handles an optionally quoted value; does not attempt list/multi-line
    values (use ``_parse_default_tools``-style parsing for those).
    """
    prefix = f"{field}:"
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip()
            return value.strip("'\"")
    return ""


def _parse_default_tools(frontmatter: str) -> tuple[str, ...]:
    tools: list[str] = []
    in_list = False
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("default_tools:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest.startswith("["):
                inner = rest.strip("[]")
                for part in inner.split(","):
                    token = part.strip().strip("'\"")
                    if token:
                        tools.append(token)
                in_list = False
            elif not rest:
                in_list = True
            else:
                token = rest.strip().strip("'\"")
                if token:
                    tools.append(token)
                in_list = False
        elif in_list and stripped.startswith("- "):
            tools.append(stripped[2:].strip().strip("'\""))
        elif in_list and stripped and not stripped.startswith("#"):
            in_list = False
    return tuple(tools)
