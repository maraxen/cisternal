"""Shared markdown formatters for asset emitters."""

from __future__ import annotations

import json

import yaml

from cisternal.assets.bundle import AgentAsset, SkillAsset


def _yaml_scalar(value: str) -> str:
    """Render ``value`` as a YAML frontmatter scalar, quoting only if unsafe.

    Bug (cisternal/fix-description-yaml-escaping): the export formatters used
    to interpolate field values directly into unquoted YAML plain scalars.
    Plain scalars have real syntax rules -- e.g. `` #`` starts a comment
    (silently truncating everything after it) and ``: `` is a hard parse
    error -- so values containing either broke YAML parsing while looking
    fine to a human `cat`-ing the file.

    Safety is determined by round-tripping ``value`` through the real YAML
    parser rather than hand-enumerating unsafe productions: a first attempt
    at this used a hand-rolled set of indicator-char/whitespace/``: ``/`` #``
    checks, which missed YAML 1.1 productions PyYAML's default resolver
    still treats as non-string (sexagesimal ints like ``"16:9"`` -> ``969``,
    hex like ``"0x1A"`` -> ``26``, binary like ``"0b1010"`` -> ``10``). Using
    ``yaml.safe_load`` as ground truth subsumes every case the heuristic was
    trying to enumerate (and any future YAML 1.1 resolver production we
    haven't thought of): ``value`` is safe to leave bare iff parsing it back
    yields the identical string (same value AND type -- an int/list/bool
    result is never equal to the original str). Already-safe strings render
    byte-identical to before; unsafe ones get a JSON string literal (also
    valid YAML 1.2 double-quoted scalar syntax, so this needs no separate
    YAML-emitting dependency -- ``ensure_ascii=False`` keeps astral-plane
    Unicode, e.g. emoji, as a single escape/codepoint rather than a split
    UTF-16 surrogate pair that YAML's escape scanner won't recombine).
    """
    try:
        safe = yaml.safe_load(value) == value
    except yaml.YAMLError:
        safe = False
    if safe:
        return value
    return json.dumps(value, ensure_ascii=False)


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
