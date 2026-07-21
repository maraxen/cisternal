"""Shared markdown formatters for asset emitters."""

from __future__ import annotations

from cisternal.assets.bundle import AgentAsset, SkillAsset


def format_agent_markdown(agent: AgentAsset) -> str:
    lines = ["---", f"name: {agent.name}"]
    if agent.description:
        lines.append(f"description: {agent.description}")
    if agent.tools:
        lines.append("tools:")
        for tool in agent.tools:
            lines.append(f"  - {tool}")
    if agent.model:
        lines.append(f"model: {agent.model}")
    lines.append("---")
    body = agent.body
    if body and not body.startswith("\n"):
        lines.append("")
    return "\n".join(lines) + body


def format_skill_markdown(skill: SkillAsset) -> str:
    lines = ["---", f"name: {skill.name}"]
    if skill.description:
        lines.append(f"description: {skill.description}")
    lines.append("---")
    body = skill.body
    if body and not body.startswith("\n"):
        lines.append("")
    return "\n".join(lines) + body
