"""PiEmitter — Pi coding agent package format (pi-package).

Emits Pi package manifest (package.json with pi-package keyword),
MCP configuration (.pi/mcp.json), skills (skills/<name>/SKILL.md),
prompt templates (prompts/<name>.md), and root AGENTS.md.

Purity contract:
    PURE: zero I/O, zero filesystem access, no side effects.
    DETERMINISTIC: identical bundle -> identical dict on every call.
    FORWARD-SLASH PATHS: all keys use ``/`` as separator.
    NEVER-RAISE: degenerate input yields a valid dict.
"""

from __future__ import annotations

import json

from cisternal.assets.bundle import AgentAsset, AssetBundle
from cisternal.export._markdown import (
    format_agent_markdown,
    format_command_markdown,
    format_skill_markdown,
)
from cisternal.export.base import Emitter

_PACKAGE_JSON_PATH = "package.json"
_MCP_JSON_PATH = ".pi/mcp.json"
_AGENTS_MD_PATH = "AGENTS.md"


class PiEmitter(Emitter):
    """Emit an AssetBundle as a Pi package."""

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        files: dict[str, str] = {}

        emit_skills = tuple(s for s in bundle.skills if s.body)
        emit_commands = tuple(c for c in bundle.commands if c.body)
        emit_agents = tuple(a for a in bundle.agents if a.body)

        package_obj: dict[str, object] = {
            "name": bundle.metadata.name,
            "version": bundle.metadata.version,
            "description": bundle.metadata.description or "",
            "type": "module",
            "keywords": ["pi-package"],
        }

        pi_block: dict[str, list[str]] = {}
        if emit_skills:
            pi_block["skills"] = ["./skills"]
        if emit_commands:
            pi_block["prompts"] = ["./prompts"]

        if pi_block:
            package_obj["pi"] = pi_block

        files[_PACKAGE_JSON_PATH] = json.dumps(package_obj, sort_keys=True, indent=2)

        if bundle.mcp_servers:
            mcp_servers: dict[str, object] = {}
            for srv in bundle.mcp_servers:
                command = list(srv.command)
                srv_obj: dict[str, object] = {
                    "command": command[0] if command else "",
                }
                if len(command) > 1:
                    srv_obj["args"] = command[1:]
                if srv.env:
                    srv_obj["env"] = dict(srv.env)
                mcp_servers[srv.name] = srv_obj
            files[_MCP_JSON_PATH] = json.dumps(
                {"mcpServers": mcp_servers},
                sort_keys=True,
                indent=2,
            )

        for skill in emit_skills:
            skill_md = format_skill_markdown(skill)
            files[f"skills/{skill.name}/SKILL.md"] = skill_md
            for resource_path, content in skill.resources:
                files[f"skills/{skill.name}/{resource_path}"] = content

        for cmd in emit_commands:
            files[f"prompts/{cmd.name}.md"] = format_command_markdown(cmd)

        if emit_agents:
            files[_AGENTS_MD_PATH] = _format_pi_agents(emit_agents)

        return files


def _format_pi_agents(agents: tuple[AgentAsset, ...]) -> str:
    """Format agents for Pi root AGENTS.md."""
    if len(agents) == 1:
        md = format_agent_markdown(agents[0])
        return md if md.endswith("\n") else md + "\n"

    sections = ["# Agents"]
    for agent in agents:
        sections.append(f"## {agent.name}\n\n{format_agent_markdown(agent).strip()}")
    return "\n\n".join(sections).strip() + "\n"

