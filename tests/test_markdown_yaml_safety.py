"""Unit tests for YAML scalar safety in _markdown.py."""

from __future__ import annotations

import yaml

from cisternal.assets.bundle import AgentAsset, CommandAsset, SkillAsset
from cisternal.export._markdown import (
    _yaml_scalar,
    format_agent_markdown,
    format_command_markdown,
    format_skill_markdown,
)


def test_yaml_scalar_roundtrip_safety() -> None:
    test_cases = [
        "regular_name",
        "name-with-hyphens",
        "name:with:colons",
        "audit:",
        ":audit",
        "?audit",
        "100%",
        "name # with comment",
        "100",
        "0x1A",
        "16:9",
        "true",
        "false",
        "null",
        "yes",
        "no",
        "on",
        "off",
        "@special",
        "[array_like]",
        "{dict_like}",
    ]

    for val in test_cases:
        rendered = _yaml_scalar(val)
        parsed = yaml.safe_load(f"k: {rendered}")
        assert parsed == {"k": val}, f"Failed roundtrip for {val!r}: got {parsed!r}"

    # Non-string and None inputs
    assert _yaml_scalar(None) == ""
    assert _yaml_scalar(123) == "123"



def test_format_agent_markdown_parseable_with_special_chars() -> None:
    agent = AgentAsset(
        name="audit:sec",
        model="provider/model:v2",
        description="Agent for security # critical",
        tools=("bash:eval", "edit:file"),
        body="Agent instructions body\n",
    )
    md = format_agent_markdown(agent)
    parts = md.split("---")
    assert len(parts) >= 3
    frontmatter = yaml.safe_load(parts[1])

    assert frontmatter["name"] == "audit:sec"
    assert frontmatter["model"] == "provider/model:v2"
    assert frontmatter["description"] == "Agent for security # critical"
    assert frontmatter["tools"] == ["bash:eval", "edit:file"]


def test_format_skill_markdown_parseable_with_special_chars() -> None:
    skill = SkillAsset(
        name="16:9",
        description="Aspect ratio 16:9 # helper",
        triggers=("run 100%", "fix:bug"),
        body="Skill body content\n",
    )
    md = format_skill_markdown(skill)
    parts = md.split("---")
    assert len(parts) >= 3
    frontmatter = yaml.safe_load(parts[1])

    assert frontmatter["name"] == "16:9"
    assert frontmatter["description"] == "Aspect ratio 16:9 # helper"
    assert frontmatter["triggers"] == ["run 100%", "fix:bug"]


def test_format_command_markdown_parseable_with_special_chars() -> None:
    command = CommandAsset(
        name="cmd:test",
        description="Run test:suite # fast",
        body="Command body\n",
    )
    md = format_command_markdown(command)
    parts = md.split("---")
    assert len(parts) >= 3
    frontmatter = yaml.safe_load(parts[1])

    assert frontmatter["name"] == "cmd:test"
    assert frontmatter["description"] == "Run test:suite # fast"
