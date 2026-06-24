"""Cursor rust-parity emit helpers (M12.3) — byte match praxia bundle_cursor.rs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from cisterna.assets.bundle import AssetBundle, HookSpecAsset
from cisterna.export._rust_emit import (
    compact_json,
    cursor_event_name_rust,
    mcp_servers_json,
    skill_markdown_rust,
)

_PLUGIN_JSON_PATH = ".cursor-plugin/plugin.json"
_HOOKS_JSON_PATH = ".cursor/hooks.json"
_MCP_JSON_PATH = ".mcp.json"


def emit_cursor_rust_parity(bundle: AssetBundle) -> dict[str, str]:
    """Emit Cursor files matching praxia-agent-assets default emit (no agent .md)."""
    files: dict[str, str] = {}
    hook_specs = bundle.hook_specs

    hooks_doc: dict[str, object] | None = None
    if hook_specs:
        hooks_doc = _build_cursor_hooks_rust(hook_specs)

    plugin_obj: dict[str, Any] = {
        "name": bundle.metadata.name,
        "version": bundle.metadata.version,
        "description": bundle.metadata.description or "",
        "agents": [agent.name for agent in bundle.agents],
        "skills": [skill.name for skill in bundle.skills],
    }
    if hooks_doc is not None:
        plugin_obj["hooks"] = hooks_doc
    if bundle.mcp_servers:
        plugin_obj["mcpServers"] = mcp_servers_json(bundle.mcp_servers)

    files[_PLUGIN_JSON_PATH] = compact_json(plugin_obj)

    for skill in bundle.skills:
        files[f"skills/{skill.name}/SKILL.md"] = skill_markdown_rust(skill)

    if bundle.mcp_servers:
        files[_MCP_JSON_PATH] = compact_json(
            {"mcpServers": mcp_servers_json(bundle.mcp_servers)},
        )

    if hooks_doc is not None:
        files[_HOOKS_JSON_PATH] = compact_json(hooks_doc)

    return files


def _build_cursor_hooks_rust(hook_specs: tuple[HookSpecAsset, ...]) -> dict[str, object]:
    events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for spec in hook_specs:
        event_key = cursor_event_name_rust(spec.event)
        entry: dict[str, str] = {"command": spec.script}
        if spec.matcher:
            entry["matcher"] = spec.matcher
        events[event_key].append(entry)

    return {
        "version": 1,
        "hooks": dict(sorted(events.items())),
    }
