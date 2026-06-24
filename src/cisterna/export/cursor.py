"""CursorEmitter — Cursor IDE plugin format (M3.1b spec rev3).

Port of praxia ``bundle_cursor.rs`` with L17 fail-closed: ``agents`` and
``skills`` keys are omitted from ``plugin.json`` when corresponding files are
not emitted (non-empty body required).
"""

from __future__ import annotations

import json
from collections import defaultdict

from cisterna.assets.bundle import AssetBundle, HookSpecAsset
from cisterna.export._markdown import format_agent_markdown, format_skill_markdown
from cisterna.export.cursor_rust import emit_cursor_rust_parity
from cisterna.export.base import Emitter
from cisterna.export.hooks import hooks_for_surface

_PLUGIN_JSON_PATH = ".cursor-plugin/plugin.json"
_HOOKS_JSON_PATH = ".cursor/hooks.json"
_MCP_JSON_PATH = ".mcp.json"


class CursorEmitter(Emitter):
    """Emit an AssetBundle as a Cursor plugin directory (pure, never-raise)."""

    def __init__(self, *, rust_parity: bool = False) -> None:
        self._rust_parity = rust_parity

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        if self._rust_parity:
            return emit_cursor_rust_parity(bundle)

        files: dict[str, str] = {}
        hook_specs = hooks_for_surface(bundle.hook_specs, "cursor")

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
            hooks_doc = _build_cursor_hooks(hook_specs)
            plugin_obj["hooks"] = hooks_doc

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

        if hook_specs:
            hooks_doc = _build_cursor_hooks(hook_specs)
            files[_HOOKS_JSON_PATH] = json.dumps(hooks_doc, sort_keys=True, indent=2)

        return files


def _cursor_event_name(canonical: str) -> str:
    mapping = {
        "SessionStart": "sessionStart",
        "SessionEnd": "sessionEnd",
        "PreCompact": "preCompact",
        "PostCompact": "postCompact",
        "WorktreeCreate": "worktreeCreate",
        "WorktreeRemove": "worktreeRemove",
        "SubagentStart": "subagentStart",
        "SubagentStop": "subagentStop",
        "PreToolUse": "beforeShellExecution",
        "PostToolUse": "afterFileEdit",
    }
    return mapping.get(canonical, canonical)


def _build_cursor_hooks(hook_specs: tuple[HookSpecAsset, ...]) -> dict[str, object]:
    events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for spec in hook_specs:
        event_key = _cursor_event_name(spec.event)
        entry: dict[str, str] = {"command": spec.script}
        if spec.matcher:
            entry["matcher"] = spec.matcher
        events[event_key].append(entry)

    return {
        "version": 1,
        "hooks": dict(sorted(events.items())),
    }
