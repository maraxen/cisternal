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
        commands = load_export_commands(plugin, self._root, warnings)
        warnings.extend(validate_extension_sections(plugin, self._root))

        bundle = AssetBundle(
            metadata=metadata,
            commands=commands,
            mcp_servers=mcp_servers,
            skills=skills,
            agents=agents,
            hook_specs=hook_specs,
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
        text = _read_text(root / rel, warnings, f"skill {name!r}")
        body = text if text is not None else ""
        skills.append(SkillAsset(name=name, body=body))
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


def _parse_agent_markdown(text: str) -> tuple[tuple[str, ...], str]:
    """Return (default_tools, body_without_frontmatter)."""
    if not text.startswith("---"):
        return (), text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return (), text
    fm = parts[1]
    body = parts[2].lstrip("\n")
    return _parse_default_tools(fm), body


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
