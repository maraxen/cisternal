"""Active Claude Code server registrations scanner and cache manager (Spec §C1).

Invariants:
1. Host safety: read-only with respect to host configuration. NEVER mutates
   ~/.config/cisternal/config.toml (uses marketplace_root_source(), NOT resolve_marketplace_root()).
2. Never spawns `claude` CLI process.
3. Expands active server wire prefixes against [families] and [verbs] into active_servers.json.
4. Writes <sessions dir>/active_servers.json atomically via temporary file + os.replace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import random
from typing import Any

from cisternal.plugin.config import marketplace_root_source
from cisternal.plugin.shared import claude_home
from cisternal.usage.paths import resolve_sessions_dir

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PluginAssetInfo:
    servers: tuple[str, ...] = ()
    hooks: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActiveRegistrations:
    servers: tuple[str, ...] = ()
    tools: dict[str, str] = field(default_factory=dict)
    verbs: dict[str, Any] = field(default_factory=dict)
    families: dict[str, tuple[str, ...]] = field(default_factory=dict)
    plugins: dict[str, PluginAssetInfo] = field(default_factory=dict)


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log.warning("Failed to read JSON from %s: %s", path, exc)
        return {}


def _atomic_write_cache(cache_file: Path, data: dict[str, Any]) -> None:
    tmp_file = cache_file.with_suffix(
        f".tmp.{os.getpid()}.{random.randint(1000, 9999)}"
    )
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
        tmp_file.write_text(text, encoding="utf-8")
        os.replace(tmp_file, cache_file)
    except Exception as exc:
        _log.warning("Failed to atomically write active_servers.json: %s", exc)
        try:
            if tmp_file.exists():
                tmp_file.unlink()
        except OSError:
            pass


def scan_active_registrations(
    sessions_dir: Path | str | None = None,
    *,
    claude_dir: Path | None = None,
    marketplace_dir: Path | None = None,
    manifest_path: Path | None = None,
    force: bool = False,
) -> ActiveRegistrations:
    """Scan active Claude Code registrations, plugin manifests, and bundle assets.

    ``sessions_dir`` is layer 1 of the sessions-dir resolver: ``None`` re-resolves
    from the environment/pyproject/XDG layers, while ``"off"``/``"none"``/``""``
    disables the ``active_servers.json`` cache (nothing is read or written).
    """
    # 1. Resolve sessions dir
    s_dir, _ = resolve_sessions_dir(data_dir=sessions_dir)
    cache_file = (s_dir / "active_servers.json") if s_dir else None

    # 2. Check cache freshness unless force=True
    c_home = claude_dir or claude_home()
    settings_file = c_home / "settings.json"
    claude_json_file = Path.home() / ".claude.json"
    local_mcp_file = Path.cwd() / ".mcp.json"
    m_root, _ = marketplace_root_source(marketplace_dir)

    candidate_files: list[Path] = [settings_file, claude_json_file, local_mcp_file]
    try:
        if m_root and m_root.is_dir():
            plugins_dir = m_root / "plugins"
            search_dirs = [plugins_dir] if plugins_dir.is_dir() else [m_root]
            for s_dir_entry in search_dirs:
                for p_subdir in s_dir_entry.iterdir():
                    if p_subdir.is_dir():
                        candidate_files.extend(
                            (
                                p_subdir / ".claude-plugin" / "plugin.json",
                                p_subdir / "plugin.json",
                                p_subdir / ".mcp.json",
                                p_subdir / ".claude-plugin" / "cisternal-source.json",
                            )
                        )
    except OSError:
        pass

    max_mtime = 0.0
    for f in candidate_files:
        try:
            if f.is_file():
                mt = f.stat().st_mtime
                if mt > max_mtime:
                    max_mtime = mt
        except OSError:
            continue

    try:
        cache_is_file = bool(cache_file and cache_file.is_file())
    except OSError:
        cache_is_file = False

    if cache_file and cache_is_file and not force:
        try:
            cache_mtime = cache_file.stat().st_mtime
            if cache_mtime >= max_mtime:
                raw_cache = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(raw_cache, dict):
                    return ActiveRegistrations(
                        servers=tuple(raw_cache.get("servers", ())),
                        tools=dict(raw_cache.get("tools", {})),
                        verbs=dict(raw_cache.get("verbs", {})),
                        families={
                            str(k): tuple(str(x) for x in v)
                            for k, v in raw_cache.get("families", {}).items()
                        },
                        plugins={
                            str(p_name): PluginAssetInfo(
                                servers=tuple(p_info.get("servers", ())),
                                hooks=tuple(p_info.get("hooks", ())),
                                commands=tuple(p_info.get("commands", ())),
                                skills=tuple(p_info.get("skills", ())),
                            )
                            for p_name, p_info in raw_cache.get("plugins", {}).items()
                        },
                    )
        except Exception as exc:
            _log.warning("Cache active_servers.json invalid or corrupt: %s", exc)

    # 3. Read host settings and ~/.claude.json read-only
    settings_data = _read_json_file(settings_file)
    claude_json_data = _read_json_file(claude_json_file)
    local_mcp_data = _read_json_file(local_mcp_file)

    active_servers: set[str] = set()
    server_to_plugin: dict[str, str] = {}
    plugin_infos: dict[str, PluginAssetInfo] = {}
    sidecar_families: dict[str, tuple[str, ...]] = {}
    sidecar_verbs: dict[str, Any] = {}

    # Extract mcpServers from settings, ~/.claude.json, and local .mcp.json
    for doc in (settings_data, claude_json_data, local_mcp_data):
        servers_table = doc.get("mcpServers")
        if isinstance(servers_table, dict):
            for s_name in servers_table.keys():
                active_servers.add(str(s_name))

    # 4. Extract enabled plugins
    enabled_plugins: set[str] = set()
    ep_entry = settings_data.get("enabledPlugins")
    if isinstance(ep_entry, dict):
        for p_name, is_enabled in ep_entry.items():
            if is_enabled:
                p_str = str(p_name)
                enabled_plugins.add(p_str)
                enabled_plugins.add(p_str.split("@")[0])
    elif isinstance(ep_entry, list):
        for p_name in ep_entry:
            p_str = str(p_name)
            enabled_plugins.add(p_str)
            enabled_plugins.add(p_str.split("@")[0])

    # Also inspect plugins directory under m_root if enabled
    if m_root and m_root.is_dir():
        plugins_dir = m_root / "plugins"
        search_dirs = [plugins_dir] if plugins_dir.is_dir() else [m_root]
        for s_dir_entry in search_dirs:
            for p_subdir in s_dir_entry.iterdir():
                if not p_subdir.is_dir():
                    continue
                p_name = p_subdir.name
                # Check if this plugin is enabled
                if p_name not in enabled_plugins:
                    continue

                p_servers: list[str] = []
                p_hooks: list[str] = []
                p_commands: list[str] = []
                p_skills: list[str] = []

                # Read .claude-plugin/plugin.json or plugin.json
                p_manifest_file = p_subdir / ".claude-plugin" / "plugin.json"
                if not p_manifest_file.is_file():
                    p_manifest_file = p_subdir / "plugin.json"
                p_manifest = _read_json_file(p_manifest_file)

                # Read .claude-plugin/cisternal-source.json sidecar if present
                source_sidecar = _read_json_file(
                    p_subdir / ".claude-plugin" / "cisternal-source.json"
                )
                if isinstance(source_sidecar.get("families"), dict):
                    for fk, fv in source_sidecar["families"].items():
                        if isinstance(fv, (list, tuple)):
                            sidecar_families[str(fk)] = tuple(str(x) for x in fv)
                if isinstance(source_sidecar.get("verbs"), dict):
                    for vk, vv in source_sidecar["verbs"].items():
                        if isinstance(vv, dict):
                            sidecar_verbs[str(vk)] = vv

                # Servers
                mcp_table = p_manifest.get("mcpServers") or p_manifest.get(
                    "mcp_servers"
                )
                if isinstance(mcp_table, dict):
                    for s in mcp_table.keys():
                        p_servers.append(str(s))
                elif (p_subdir / ".mcp.json").is_file():
                    sub_mcp = _read_json_file(p_subdir / ".mcp.json")
                    if isinstance(sub_mcp.get("mcpServers"), dict):
                        for s in sub_mcp["mcpServers"].keys():
                            p_servers.append(str(s))
                else:
                    # In Claude Code, an enabled plugin provides an MCP server under its name
                    p_servers.append(p_name)

                # Hooks
                if (p_subdir / "hooks" / "hooks.json").is_file() or (
                    p_subdir / "hooks"
                ).is_dir():
                    p_hooks.append("hooks")
                if p_manifest.get("hooks") or p_manifest.get("hook_specs"):
                    p_hooks.append("hook_specs")

                # Commands
                cmd_dir = p_subdir / "commands"
                if cmd_dir.is_dir():
                    for cmd in cmd_dir.iterdir():
                        if cmd.is_file():
                            p_commands.append(cmd.stem)
                if isinstance(p_manifest.get("commands"), list):
                    for cmd in p_manifest["commands"]:
                        p_commands.append(
                            str(cmd.get("name") if isinstance(cmd, dict) else cmd)
                        )

                # Skills
                skills_dir = p_subdir / "skills"
                if skills_dir.is_dir():
                    for sk in skills_dir.iterdir():
                        if sk.is_dir():
                            p_skills.append(sk.name)
                if isinstance(source_sidecar.get("skills_meta"), dict):
                    for sk_name in source_sidecar["skills_meta"].keys():
                        if sk_name not in p_skills:
                            p_skills.append(sk_name)

                for s in p_servers:
                    active_servers.add(s)
                    server_to_plugin[s] = p_name

                plugin_infos[p_name] = PluginAssetInfo(
                    servers=tuple(p_servers),
                    hooks=tuple(p_hooks),
                    commands=tuple(p_commands),
                    skills=tuple(p_skills),
                )

    # 6. Load [families] and [verbs] from bundle or manifest
    families: dict[str, tuple[str, ...]] = {}
    verbs: dict[str, Any] = {}

    if manifest_path and manifest_path.is_file():
        from cisternal.assets.manifest import ManifestAssetSource

        m_report = ManifestAssetSource(manifest_path).load()
        families.update(m_report.bundle.families)
        verbs.update(m_report.bundle.verbs)
    else:
        # Load cisternal's own bundle via locate_bundle / loads_snapshot (Spec §C1 / GAP-40)
        from cisternal.assets.manifest import ManifestAssetSource
        from cisternal.assets.snapshot import loads_snapshot
        from cisternal.plugin.app import PluginSpec, locate_bundle

        try:
            source = locate_bundle(PluginSpec(name="cisternal", package="cisternal"))
            if source.kind == "snapshot":
                default_bundle = loads_snapshot(source.path.read_text(encoding="utf-8"))
            else:
                default_bundle = ManifestAssetSource(source.path).load().bundle
            families.update(default_bundle.families)
            verbs.update(default_bundle.verbs)
        except Exception:
            pass

    families.update(sidecar_families)
    verbs.update(sidecar_verbs)

    # 7. Expand tools: map "<server>/<tool>" to "<wire_name>"
    tools: dict[str, str] = {}

    # Extract all known tools from families and verbs
    all_known_tools: set[str] = set()
    for fam_tools in families.values():
        all_known_tools.update(fam_tools)
    for v_name, v_data in verbs.items():
        subcmds = getattr(v_data, "subcommands", None)
        if subcmds is None and isinstance(v_data, dict):
            subcmds = v_data.get("subcommands", {})
        if isinstance(subcmds, dict):
            for t_target in subcmds.values():
                if isinstance(t_target, str):
                    all_known_tools.add(t_target)

    for tool_key in sorted(all_known_tools):
        if "/" not in tool_key:
            continue
        server, tool = tool_key.split("/", 1)
        if server in active_servers:
            plugin = server_to_plugin.get(server)
            if plugin:
                wire_name = f"mcp__plugin_{plugin}_{server}__{tool}"
            else:
                wire_name = f"mcp__{server}__{tool}"
            tools[tool_key] = wire_name

    registrations = ActiveRegistrations(
        servers=tuple(sorted(active_servers)),
        tools=tools,
        verbs=verbs,
        families=families,
        plugins=plugin_infos,
    )

    # 8. Write atomic cache to <sessions dir>/active_servers.json via temp file + os.replace
    if cache_file:
        cache_data = {
            "version": "1.0",
            "servers": list(registrations.servers),
            "tools": registrations.tools,
            "verbs": registrations.verbs,
            "families": {k: list(v) for k, v in registrations.families.items()},
            "plugins": {
                k: {
                    "servers": list(v.servers),
                    "hooks": list(v.hooks),
                    "commands": list(v.commands),
                    "skills": list(v.skills),
                }
                for k, v in registrations.plugins.items()
            },
        }
        _atomic_write_cache(cache_file, cache_data)

    return registrations
