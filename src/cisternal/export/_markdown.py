"""Shared markdown formatters for asset emitters."""

from __future__ import annotations

import json

from cisternal.assets.bundle import AgentAsset, SkillAsset

# YAML 1.1 boolean/null-like reserved words that, if left as a bare plain
# scalar, would be parsed back as a non-string value rather than the literal
# text (matched case-insensitively against the WHOLE string, not a substring).
_YAML_RESERVED_WORDS = frozenset(
    {"null", "~", "true", "false", "yes", "no", "on", "off"}
)

# Characters that are illegal (or reserved) as the first character of a YAML
# plain scalar.
_YAML_INDICATOR_CHARS = set("-?:,[]{}#&*!|>'\"%@`")


def _yaml_scalar(value: str) -> str:
    """Render ``value`` as a YAML frontmatter scalar, quoting only if unsafe.

    Bug (cisternal/fix-description-yaml-escaping): the export formatters used
    to interpolate field values directly into unquoted YAML plain scalars.
    Plain scalars have real syntax rules -- e.g. `` #`` starts a comment
    (silently truncating everything after it) and ``: `` is a hard parse
    error -- so values containing either broke YAML parsing while looking
    fine to a human `cat`-ing the file. This returns the value unchanged when
    it's safe as a bare plain scalar, and a JSON string literal (which is
    also valid YAML 1.2 double-quoted scalar syntax, so this needs no new
    dependency) when it isn't -- so already-safe strings render byte-identical
    to before, and unsafe ones get an unambiguous quoted form instead of being
    truncated or breaking the parse.
    """
    if not value:
        return json.dumps(value)
    if value != value.strip():
        return json.dumps(value)
    if ": " in value or value.endswith(":"):
        return json.dumps(value)
    if " #" in value or value.startswith("#"):
        return json.dumps(value)
    if "\n" in value or "\t" in value:
        return json.dumps(value)
    if value[0] in _YAML_INDICATOR_CHARS:
        return json.dumps(value)
    if value.lower() in _YAML_RESERVED_WORDS:
        return json.dumps(value)
    try:
        float(value)
    except ValueError:
        pass
    else:
        return json.dumps(value)
    return value


def format_agent_markdown(agent: AgentAsset) -> str:
    lines = ["---", f"name: {agent.name}"]
    if agent.description:
        lines.append(f"description: {_yaml_scalar(agent.description)}")
    if agent.tools:
        lines.append("tools:")
        for tool in agent.tools:
            lines.append(f"  - {_yaml_scalar(tool)}")
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
        lines.append(f"description: {_yaml_scalar(skill.description)}")
    if skill.triggers:
        lines.append("triggers:")
        for trigger in skill.triggers:
            lines.append(f"  - {_yaml_scalar(trigger)}")
    lines.append("---")
    body = skill.body
    if body and not body.startswith("\n"):
        lines.append("")
    return "\n".join(lines) + body
