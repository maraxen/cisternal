"""Copilot rust-parity emit helpers (M12.3) — byte match praxia bundle_copilot.rs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from cisterna.assets.bundle import AssetBundle, HookSpecAsset
from cisterna.export._rust_emit import (
    agent_markdown_rust,
    compact_json,
    copilot_event_name_rust,
    mcp_servers_json,
    skill_markdown_rust,
)

_PLUGIN_JSON_PATH = "plugin.json"
_MCP_JSON_PATH = ".mcp.json"


def emit_copilot_rust_parity(bundle: AssetBundle) -> dict[str, str]:
    """Emit Copilot files matching praxia-agent-assets."""
    files: dict[str, str] = {}
    hook_specs = bundle.hook_specs

    plugin_obj: dict[str, Any] = {
        "name": bundle.metadata.name,
        "version": bundle.metadata.version,
        "description": bundle.metadata.description or "",
        "agents": [agent.name for agent in bundle.agents],
        "skills": [skill.name for skill in bundle.skills],
    }
    if hook_specs:
        plugin_obj["hooks"] = _build_copilot_hooks_rust(hook_specs)
    if bundle.mcp_servers:
        plugin_obj["mcpServers"] = mcp_servers_json(bundle.mcp_servers)

    files[_PLUGIN_JSON_PATH] = compact_json(plugin_obj)

    for agent in bundle.agents:
        files[f"agents/{agent.name}.agent.md"] = agent_markdown_rust(agent)

    for skill in bundle.skills:
        files[f"skills/{skill.name}/SKILL.md"] = skill_markdown_rust(skill)

    if bundle.mcp_servers:
        files[_MCP_JSON_PATH] = compact_json(
            {"mcpServers": mcp_servers_json(bundle.mcp_servers)},
        )

    return files


def _build_copilot_hooks_rust(
    hook_specs: tuple[HookSpecAsset, ...],
) -> dict[str, list[dict[str, object]]]:
    events: dict[str, list[dict[str, object]]] = defaultdict(list)
    for spec in hook_specs:
        event_key = copilot_event_name_rust(spec.event)
        events[event_key].append(
            {
                "matcher": spec.matcher,
                "hooks": [
                    {
                        "type": "command",
                        "command": spec.script,
                    }
                ],
            }
        )
    return dict(sorted(events.items()))
