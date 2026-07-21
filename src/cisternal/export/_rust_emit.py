"""Shared rust-parity emit helpers (M12.2/M12.3) — byte match praxia-agent-assets."""

from __future__ import annotations

import json
from typing import Any

from cisternal.assets.bundle import AgentAsset, HookSpecAsset, McpAsset, SkillAsset


def compact_json(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


def yaml_description(description: str) -> str:
    if description:
        return f"description: {description}"
    return "description: ''"


def agent_markdown_rust(agent: AgentAsset) -> str:
    yaml_lines = [f"name: {agent.name}", yaml_description(agent.description)]
    if agent.tools:
        yaml_lines.append("tools:")
        yaml_lines.extend(f"- {tool}" for tool in agent.tools)
    if agent.model:
        yaml_lines.append(f"model: {agent.model}")
    yaml_str = "\n".join(yaml_lines) + "\n"
    return f"---\n{yaml_str}---\n{agent.body}"


def skill_markdown_rust(skill: SkillAsset) -> str:
    yaml_str = f"name: {skill.name}\n{yaml_description(skill.description)}\n"
    return f"---\n{yaml_str}---\n{skill.body}"


def claude_hook_command(event: str, script: str) -> str:
    return f"env PRAXIA_HOOK_SURFACE=claude PRAXIA_HOOK_EVENT={event} {script}"


def cursor_event_name_rust(canonical: str) -> str:
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


def copilot_event_name_rust(canonical: str) -> str:
    mapping = {
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
        "SessionStart": "sessionStart",
        "SessionEnd": "sessionEnd",
    }
    return mapping.get(canonical, canonical)


def build_claude_hooks_json(hook_specs: tuple[HookSpecAsset, ...]) -> dict[str, Any]:
    """Build Claude hooks object (top-level event keys, praxia build_claude_hooks)."""
    events: dict[str, list[dict[str, Any]]] = {}
    pre_tool: list[dict[str, Any]] = []
    post_tool: list[dict[str, Any]] = []

    for spec in hook_specs:
        hook_cmd = {
            "type": "command",
            "command": claude_hook_command(spec.event, spec.script),
        }
        if spec.event == "PreToolUse":
            append_hook_entry(pre_tool, spec.matcher, hook_cmd)
            continue
        if spec.event == "PostToolUse":
            append_hook_entry(post_tool, spec.matcher, hook_cmd)
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


def append_hook_entry(
    bucket: list[dict[str, Any]],
    matcher: str,
    hook_cmd: dict[str, str],
) -> None:
    for entry in bucket:
        if entry["matcher"] == matcher:
            entry["hooks"].append(hook_cmd)
            return
    bucket.append({"matcher": matcher, "hooks": [hook_cmd]})


def mcp_servers_json(bundle_mcp: tuple[McpAsset, ...]) -> dict[str, Any]:
    return {
        srv.name: {
            "command": list(srv.command),
            "env": dict(srv.env),
        }
        for srv in bundle_mcp
    }
