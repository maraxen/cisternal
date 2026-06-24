"""Claude rust-parity emit helpers (M12.2) — byte match praxia bundle_claude.rs."""

from __future__ import annotations

import json
from typing import Any

from cisterna.assets.bundle import AgentAsset, AssetBundle, HookSpecAsset, SkillAsset

_PLUGIN_JSON_PATH = ".claude-plugin/plugin.json"
_HOOKS_JSON_PATH = "hooks/hooks.json"
_MCP_JSON_PATH = ".mcp.json"


def emit_claude_rust_parity(bundle: AssetBundle) -> dict[str, str]:
    """Emit Claude files matching praxia-agent-assets (no provenance sidecar)."""
    files: dict[str, str] = {_PLUGIN_JSON_PATH: _plugin_json_rust(bundle)}

    for agent in bundle.agents:
        files[f"agents/{agent.name}.md"] = _agent_markdown_rust(agent)

    for skill in bundle.skills:
        files[f"skills/{skill.name}/SKILL.md"] = _skill_markdown_rust(skill)

    if bundle.mcp_servers:
        mcp_servers: dict[str, Any] = {
            srv.name: {
                "command": list(srv.command),
                "env": dict(srv.env),
            }
            for srv in bundle.mcp_servers
        }
        files[_MCP_JSON_PATH] = _compact_json({"mcpServers": mcp_servers})

    if bundle.hook_specs:
        files[_HOOKS_JSON_PATH] = _compact_json(_build_claude_hooks_json(bundle.hook_specs))

    return files


def _compact_json(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


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
        obj["mcpServers"] = {
            srv.name: {
                "command": list(srv.command),
                "env": dict(srv.env),
            }
            for srv in bundle.mcp_servers
        }
    return _compact_json(obj)


def _agent_markdown_rust(agent: AgentAsset) -> str:
    yaml_lines = [f"name: {agent.name}", _yaml_description(agent.description)]
    if agent.tools:
        yaml_lines.append("tools:")
        yaml_lines.extend(f"- {tool}" for tool in agent.tools)
    if agent.model:
        yaml_lines.append(f"model: {agent.model}")
    yaml_str = "\n".join(yaml_lines) + "\n"
    return f"---\n{yaml_str}---\n{agent.body}"


def _skill_markdown_rust(skill: SkillAsset) -> str:
    yaml_str = f"name: {skill.name}\n{_yaml_description(skill.description)}\n"
    return f"---\n{yaml_str}---\n{skill.body}"


def _yaml_description(description: str) -> str:
    if description:
        return f"description: {description}"
    return "description: ''"


def _hook_command_rust(event: str, script: str) -> str:
    return f"env PRAXIA_HOOK_SURFACE=claude PRAXIA_HOOK_EVENT={event} {script}"


def _build_claude_hooks_json(hook_specs: tuple[HookSpecAsset, ...]) -> dict[str, Any]:
    """Build Claude hooks object (top-level event keys, praxia build_claude_hooks)."""
    events: dict[str, list[dict[str, Any]]] = {}
    pre_tool: list[dict[str, Any]] = []
    post_tool: list[dict[str, Any]] = []

    for spec in hook_specs:
        hook_cmd = {
            "type": "command",
            "command": _hook_command_rust(spec.event, spec.script),
        }
        if spec.event == "PreToolUse":
            _append_hook_entry(pre_tool, spec.matcher, hook_cmd)
            continue
        if spec.event == "PostToolUse":
            _append_hook_entry(post_tool, spec.matcher, hook_cmd)
            continue
        matcher = spec.matcher if spec.matcher else ""
        events.setdefault(spec.event, []).append(
            {"matcher": matcher, "hooks": [hook_cmd]},
        )

    root: dict[str, Any] = dict(sorted(events.items()))
    if pre_tool:
        root["PreToolUse"] = pre_tool
    if post_tool:
        root["PostToolUse"] = post_tool
    return root


def _append_hook_entry(
    bucket: list[dict[str, Any]],
    matcher: str,
    hook_cmd: dict[str, str],
) -> None:
    for entry in bucket:
        if entry["matcher"] == matcher:
            entry["hooks"].append(hook_cmd)
            return
    bucket.append({"matcher": matcher, "hooks": [hook_cmd]})
