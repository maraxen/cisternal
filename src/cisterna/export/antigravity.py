"""AntigravityEmitter — Antigravity CLI gemini-extension format (M3.1c)."""

from __future__ import annotations

import json

from cisterna.assets.bundle import AssetBundle
from cisterna.export._markdown import format_agent_markdown, format_skill_markdown
from cisterna.export.antigravity_rust import emit_antigravity_rust_parity
from cisterna.export.base import Emitter
from cisterna.export.hooks import build_claude_style_hooks, hooks_for_surface

_EXTENSION_JSON_PATH = "gemini-extension.json"
_MCP_JSON_PATH = ".mcp.json"
_HOOKS_JSON_PATH = "hooks/hooks.json"
_CONTEXT_FILE_NAME = "GEMINI.md"


class AntigravityEmitter(Emitter):
    """Emit an AssetBundle as an Antigravity gemini-extension (pure, never-raise)."""

    def __init__(self, *, rust_parity: bool = False) -> None:
        self._rust_parity = rust_parity

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        if self._rust_parity:
            return emit_antigravity_rust_parity(bundle)

        files: dict[str, str] = {}
        hook_specs = hooks_for_surface(bundle.hook_specs, "antigravity")

        emit_agents = tuple(a for a in bundle.agents if a.body)
        emit_skills = tuple(s for s in bundle.skills if s.body)
        emit_commands = tuple(c for c in bundle.commands if c.body)

        extension: dict[str, object] = {
            "name": bundle.metadata.name,
            "version": bundle.metadata.version,
            "contextFileName": _CONTEXT_FILE_NAME,
            "settings": {},
        }

        if emit_agents:
            extension["agents"] = [a.name for a in emit_agents]
        if emit_skills:
            extension["skills"] = [s.name for s in emit_skills]
        if emit_commands:
            extension["commands"] = [c.name for c in emit_commands]

        if bundle.mcp_servers:
            extension["mcpServers"] = {
                srv.name: {
                    "command": list(srv.command),
                    "env": dict(srv.env),
                }
                for srv in bundle.mcp_servers
            }

        files[_EXTENSION_JSON_PATH] = json.dumps(extension, sort_keys=True, indent=2)

        for agent in emit_agents:
            files[f"agents/{agent.name}.md"] = format_agent_markdown(agent)

        for skill in emit_skills:
            files[f"skills/{skill.name}/SKILL.md"] = format_skill_markdown(skill)

        if bundle.mcp_servers:
            mcp_obj = {
                "mcpServers": {
                    srv.name: {
                        "command": list(srv.command),
                        "env": dict(srv.env),
                    }
                    for srv in bundle.mcp_servers
                }
            }
            files[_MCP_JSON_PATH] = json.dumps(mcp_obj, sort_keys=True, indent=2)

        if hook_specs:
            hooks_root = build_claude_style_hooks(hook_specs)
            files[_HOOKS_JSON_PATH] = json.dumps(
                {"hooks": hooks_root},
                sort_keys=True,
                indent=2,
            )

        return files
