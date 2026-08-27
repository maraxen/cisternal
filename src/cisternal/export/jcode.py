"""JCodeEmitter — JCode plugin format.

Emits JCode plugin manifest (plugin.json), optional local marketplace catalog
(marketplace.json), MCP configuration (.jcode/mcp.json), skills (skills/<name>/SKILL.md),
and agents (agents/<name>.md).

Purity contract:
    PURE: zero I/O, zero filesystem access, no side effects.
    DETERMINISTIC: identical bundle -> identical dict on every call.
    FORWARD-SLASH PATHS: all keys use ``/`` as separator.
    NEVER-RAISE: degenerate input yields a valid dict.
"""

from __future__ import annotations

import json

from cisternal.assets.bundle import AssetBundle, McpAsset
from cisternal.export._markdown import format_agent_markdown, format_skill_markdown
from cisternal.export.base import Emitter

_PLUGIN_JSON_PATH = "plugin.json"
_MARKETPLACE_JSON_PATH = "marketplace.json"
_MCP_JSON_PATH = ".jcode/mcp.json"


class JCodeEmitter(Emitter):
    """Emit an AssetBundle as a JCode plugin directory."""

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        files: dict[str, str] = {}

        emit_agents = tuple(a for a in bundle.agents if a.body)
        emit_skills = tuple(s for s in bundle.skills if s.body)

        plugin_obj: dict[str, object] = {
            "name": bundle.metadata.name,
            "version": bundle.metadata.version,
            "description": bundle.metadata.description or "",
        }

        if emit_skills:
            plugin_obj["skills"] = [s.name for s in emit_skills]
        if emit_agents:
            plugin_obj["agents"] = [a.name for a in emit_agents]

        mcp_servers_obj: dict[str, object] = {}
        if bundle.mcp_servers:
            mcp_servers_obj = {
                srv.name: _mcp_server_obj(srv) for srv in bundle.mcp_servers
            }
            plugin_obj["mcpServers"] = mcp_servers_obj

        files[_PLUGIN_JSON_PATH] = json.dumps(plugin_obj, sort_keys=True, indent=2)

        for agent in emit_agents:
            files[f"agents/{agent.name}.md"] = format_agent_markdown(agent)

        for skill in emit_skills:
            files[f"skills/{skill.name}/SKILL.md"] = format_skill_markdown(skill)
            for resource_path, content in skill.resources:
                files[f"skills/{skill.name}/{resource_path}"] = content

        if bundle.mcp_servers:
            mcp_obj = {"mcpServers": mcp_servers_obj}
            files[_MCP_JSON_PATH] = json.dumps(mcp_obj, sort_keys=True, indent=2)

        if bundle.marketplace is not None:
            owner: dict[str, str] = {
                "name": bundle.marketplace.owner_name or bundle.metadata.name,
            }
            if bundle.marketplace.owner_email:
                owner["email"] = bundle.marketplace.owner_email
            if bundle.marketplace.owner_url:
                owner["url"] = bundle.marketplace.owner_url
            marketplace_obj = {
                "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
                "name": bundle.marketplace.name,
                "description": bundle.metadata.description or "",
                "owner": owner,
                "plugins": [
                    {
                        "name": bundle.metadata.name,
                        "description": bundle.metadata.description or "",
                        "version": bundle.metadata.version,
                        "source": "./",
                    }
                ],
            }
            files[_MARKETPLACE_JSON_PATH] = json.dumps(
                marketplace_obj, sort_keys=True, indent=2
            )

        return files


def _mcp_server_obj(srv: McpAsset) -> dict[str, object]:
    command = srv.command
    obj: dict[str, object] = {
        "command": command[0] if command else "",
    }
    if len(command) > 1:
        obj["args"] = list(command[1:])
    if srv.env:
        obj["env"] = dict(srv.env)
    return obj

