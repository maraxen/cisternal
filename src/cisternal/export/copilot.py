"""CopilotEmitter — Copilot CLI plugin format (M3.1b spec rev3)."""

from __future__ import annotations

import json
from collections import defaultdict

from cisternal.assets.bundle import AssetBundle, HookSpecAsset
from cisternal.export._markdown import format_agent_markdown, format_skill_markdown
from cisternal.export.copilot_rust import emit_copilot_rust_parity
from cisternal.export.base import Emitter
from cisternal.export.hooks import hooks_for_surface

_PLUGIN_JSON_PATH = "plugin.json"
_MCP_JSON_PATH = ".mcp.json"


class CopilotEmitter(Emitter):
    """Emit an AssetBundle as a Copilot plugin directory (pure, never-raise)."""

    def __init__(self, *, rust_parity: bool = False) -> None:
        self._rust_parity = rust_parity

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        if self._rust_parity:
            return emit_copilot_rust_parity(bundle)

        files: dict[str, str] = {}
        hook_specs = hooks_for_surface(bundle.hook_specs, "copilot")

        emit_agents = tuple(a for a in bundle.agents if a.body)
        emit_skills = tuple(s for s in bundle.skills if s.body)

        plugin_obj: dict[str, object] = {
            "name": bundle.metadata.name,
            "version": bundle.metadata.version,
            "description": bundle.metadata.description or "",
        }

        if emit_agents:
            plugin_obj["agents"] = [a.name for a in emit_agents]
        if emit_skills:
            plugin_obj["skills"] = [s.name for s in emit_skills]

        if hook_specs:
            plugin_obj["hooks"] = _build_copilot_hooks(hook_specs)

        if bundle.mcp_servers:
            plugin_obj["mcpServers"] = {
                srv.name: {
                    "command": list(srv.command),
                    "env": dict(srv.env),
                }
                for srv in bundle.mcp_servers
            }

        files[_PLUGIN_JSON_PATH] = json.dumps(plugin_obj, sort_keys=True, indent=2)

        for agent in emit_agents:
            files[f"agents/{agent.name}.agent.md"] = format_agent_markdown(agent)

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

        return files


def _copilot_event_name(canonical: str) -> str:
    mapping = {
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
        "SessionStart": "sessionStart",
        "SessionEnd": "sessionEnd",
    }
    return mapping.get(canonical, canonical)


def _build_copilot_hooks(hook_specs: tuple[HookSpecAsset, ...]) -> dict[str, list[dict[str, object]]]:
    events: dict[str, list[dict[str, object]]] = defaultdict(list)
    for spec in hook_specs:
        event_key = _copilot_event_name(spec.event)
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
