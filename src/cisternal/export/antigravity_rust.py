"""Antigravity rust-parity emit helpers (M12.3) — byte match praxia bundle_antigravity.rs."""

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

_EXTENSION_JSON_PATH = "gemini-extension.json"
_MCP_JSON_PATH = ".mcp.json"
_HOOKS_JSON_PATH = "hooks/hooks.json"
_CONTEXT_FILE_NAME = "GEMINI.md"


def emit_antigravity_rust_parity(bundle: AssetBundle) -> dict[str, str]:
    """Emit Antigravity files matching praxia-agent-assets."""
    files: dict[str, str] = {}

    extension: dict[str, Any] = {
        "name": bundle.metadata.name,
        "version": bundle.metadata.version,
        "agents": [agent.name for agent in bundle.agents],
        "skills": [skill.name for skill in bundle.skills],
        "commands": [cmd.name for cmd in bundle.commands],
        "contextFileName": _CONTEXT_FILE_NAME,
    }
    if bundle.mcp_servers:
        extension["mcpServers"] = mcp_servers_json(bundle.mcp_servers)
    extension["settings"] = {}

    files[_EXTENSION_JSON_PATH] = compact_json(extension)

    for agent in bundle.agents:
        files[f"agents/{agent.name}.md"] = agent_markdown_rust(agent)

    for skill in bundle.skills:
        files[f"skills/{skill.name}/SKILL.md"] = skill_markdown_rust(skill)

    if bundle.mcp_servers:
        files[_MCP_JSON_PATH] = compact_json(
            {"mcpServers": mcp_servers_json(bundle.mcp_servers)},
        )

    if bundle.hook_specs:
        files[_HOOKS_JSON_PATH] = compact_json(
            {"hooks": build_claude_hooks_json(bundle.hook_specs)},
        )

    return files
