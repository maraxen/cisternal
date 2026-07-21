"""Claude rust-parity emit helpers (M12.2) — byte match praxia bundle_claude.rs."""

from __future__ import annotations

from typing import Any

from cisternal.assets.bundle import AssetBundle
from cisternal.export._rust_emit import (
    agent_markdown_rust,
    build_claude_hooks_json,
    compact_json,
    mcp_servers_json,
    skill_markdown_rust,
)

_PLUGIN_JSON_PATH = ".claude-plugin/plugin.json"
_HOOKS_JSON_PATH = "hooks/hooks.json"
_MCP_JSON_PATH = ".mcp.json"


def emit_claude_rust_parity(bundle: AssetBundle) -> dict[str, str]:
    """Emit Claude files matching praxia-agent-assets (no provenance sidecar)."""
    files: dict[str, str] = {_PLUGIN_JSON_PATH: _plugin_json_rust(bundle)}

    for agent in bundle.agents:
        files[f"agents/{agent.name}.md"] = agent_markdown_rust(agent)

    for skill in bundle.skills:
        files[f"skills/{skill.name}/SKILL.md"] = skill_markdown_rust(skill)

    if bundle.mcp_servers:
        files[_MCP_JSON_PATH] = compact_json({"mcpServers": mcp_servers_json(bundle.mcp_servers)})

    if bundle.hook_specs:
        files[_HOOKS_JSON_PATH] = compact_json(build_claude_hooks_json(bundle.hook_specs))

    return files


def _plugin_json_rust(bundle: AssetBundle) -> str:
    obj: dict[str, Any] = {
        "name": bundle.metadata.name,
        "version": bundle.metadata.version,
        "description": bundle.metadata.description or "",
        "agents": [agent.name for agent in bundle.agents],
        "skills": [skill.name for skill in bundle.skills],
    }
    if bundle.commands:
        obj["commands"] = [cmd.name for cmd in bundle.commands]
    if bundle.mcp_servers:
        obj["mcpServers"] = mcp_servers_json(bundle.mcp_servers)
    return compact_json(obj)
