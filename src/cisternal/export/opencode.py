"""OpenCodeEmitter — OpenCode agent export format.

Emits OpenCode configuration (opencode.json conforming to
https://opencode.ai/config.json), skills (.opencode/skills/ and skills/),
agents (.opencode/agents/), and commands (.opencode/commands/).

Purity contract:
    PURE: zero I/O, zero filesystem access, no side effects.
    DETERMINISTIC: identical bundle -> identical dict on every call.
    FORWARD-SLASH PATHS: all keys use ``/`` as separator.
    NEVER-RAISE: degenerate input yields a valid dict.
"""

from __future__ import annotations

import json

from cisternal.assets.bundle import AssetBundle
from cisternal.export._markdown import (
    format_agent_markdown,
    format_command_markdown,
    format_skill_markdown,
)
from cisternal.export.base import Emitter

_OPENCODE_SCHEMA = "https://opencode.ai/config.json"
_CONFIG_JSON_PATH = "opencode.json"


class OpenCodeEmitter(Emitter):
    """Emit an AssetBundle as an OpenCode plugin / project configuration."""

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        files: dict[str, str] = {}

        config_obj: dict[str, object] = {
            "$schema": _OPENCODE_SCHEMA,
        }

        if bundle.mcp_servers:
            mcp_obj: dict[str, object] = {}
            for srv in bundle.mcp_servers:
                first_cmd = srv.command[0] if srv.command else ""
                if first_cmd.startswith(("http://", "https://")):
                    server_entry: dict[str, object] = {
                        "type": "remote",
                        "url": first_cmd,
                    }
                else:
                    server_entry: dict[str, object] = {
                        "type": "local",
                        "command": list(srv.command),
                    }
                if srv.env and server_entry["type"] == "local":
                    server_entry["environment"] = dict(srv.env)
                mcp_obj[srv.name] = server_entry

            config_obj["mcp"] = mcp_obj


        files[_CONFIG_JSON_PATH] = json.dumps(config_obj, sort_keys=True, indent=2)

        emit_skills = tuple(s for s in bundle.skills if s.body)
        for skill in emit_skills:
            skill_md = format_skill_markdown(skill)
            files[f".opencode/skills/{skill.name}/SKILL.md"] = skill_md
            files[f"skills/{skill.name}/SKILL.md"] = skill_md
            for resource_path, content in skill.resources:
                files[f".opencode/skills/{skill.name}/{resource_path}"] = content
                files[f"skills/{skill.name}/{resource_path}"] = content

        emit_agents = tuple(a for a in bundle.agents if a.body)
        for agent in emit_agents:
            files[f".opencode/agents/{agent.name}.md"] = format_agent_markdown(agent)

        emit_commands = tuple(c for c in bundle.commands if c.body)
        for cmd in emit_commands:
            files[f".opencode/commands/{cmd.name}.md"] = format_command_markdown(cmd)

        return files
