"""Regression tests for the frontmatter YAML-escaping bug (bugfix,
cisternal/fix-description-yaml-escaping).

Confirmed bug: ``format_skill_markdown``/``format_agent_markdown`` wrote
``description``/``triggers``/``tools`` fields via raw f-string interpolation
into YAML plain (unquoted) scalars, with no regard for plain-scalar syntax
rules. Two real-world cases broke silently:

1. A space followed by ``#`` starts a YAML comment -- e.g.
   ``description: The #ebooks channel...`` is parsed by any real YAML
   parser as just ``The``, silently truncating everything from ``#ebooks``
   onward.
2. A colon followed by a space inside a plain scalar is a hard YAML parse
   error -- e.g. ``description: How to work in this repo: conventions...``
   makes the whole frontmatter block (and therefore the whole file)
   unparseable.

A bare substring check (``"description: ..." in header``) does NOT catch
either failure mode, since the raw text is technically present in the
output -- it's just not correctly delimited as YAML. These tests instead
parse the rendered frontmatter with real PyYAML (``yaml.safe_load``) and
assert the round-tripped value equals the original input exactly, which is
the check that would have caught the bug.
"""

from __future__ import annotations

import yaml

from cisternal.assets.bundle import AgentAsset, SkillAsset
from cisternal.export._markdown import (
    _yaml_scalar,
    format_agent_markdown,
    format_skill_markdown,
)


def _parse_frontmatter(rendered: str) -> dict:
    """Extract and YAML-parse the frontmatter block from rendered markdown."""
    assert rendered.startswith("---\n")
    _, _, rest = rendered.partition("---\n")
    frontmatter, _, _ = rest.partition("\n---")
    parsed = yaml.safe_load(frontmatter)
    assert isinstance(parsed, dict)
    return parsed


# ---------------------------------------------------------------------------
# skill.description
# ---------------------------------------------------------------------------


def test_skill_description_with_space_hash_survives_yaml_parse() -> None:
    """A description containing ' #something' would previously be truncated
    by any real YAML parser at the '#' (comment start)."""
    description = "The #ebooks channel handles automated book requests"
    skill = SkillAsset(name="demo-skill", description=description)

    rendered = format_skill_markdown(skill)
    parsed = _parse_frontmatter(rendered)

    assert parsed["description"] == description


def test_skill_description_with_colon_space_survives_yaml_parse() -> None:
    """A description containing 'word: rest' would previously be a hard
    YAML parse error (colon-space is illegal in a plain scalar)."""
    description = "How to work in this repo: conventions and workflows"
    skill = SkillAsset(name="demo-skill", description=description)

    rendered = format_skill_markdown(skill)
    parsed = _parse_frontmatter(rendered)

    assert parsed["description"] == description


def test_skill_triggers_with_space_hash_and_colon_space_survive_yaml_parse() -> None:
    """Same two failure modes, but for individual ``triggers`` list items."""
    triggers = ["check the #ebooks channel", "repo: run conventions"]
    skill = SkillAsset(name="demo-skill", triggers=tuple(triggers))

    rendered = format_skill_markdown(skill)
    parsed = _parse_frontmatter(rendered)

    assert parsed["triggers"] == triggers


# ---------------------------------------------------------------------------
# agent.description / agent.tools
# ---------------------------------------------------------------------------


def test_agent_description_with_space_hash_survives_yaml_parse() -> None:
    description = "Watches the #ebooks channel for requests"
    agent = AgentAsset(name="demo-agent", description=description)

    rendered = format_agent_markdown(agent)
    parsed = _parse_frontmatter(rendered)

    assert parsed["description"] == description


def test_agent_description_with_colon_space_survives_yaml_parse() -> None:
    description = "How to work in this repo: conventions and workflows"
    agent = AgentAsset(name="demo-agent", description=description)

    rendered = format_agent_markdown(agent)
    parsed = _parse_frontmatter(rendered)

    assert parsed["description"] == description


def test_agent_tools_with_space_hash_and_colon_space_survive_yaml_parse() -> None:
    tools = ["grep #patterns", "note: bash"]
    agent = AgentAsset(name="demo-agent", tools=tuple(tools))

    rendered = format_agent_markdown(agent)
    parsed = _parse_frontmatter(rendered)

    assert parsed["tools"] == tools


# ---------------------------------------------------------------------------
# Don't over-quote: currently-safe strings must render bare, byte-identical
# to the pre-fix output.
# ---------------------------------------------------------------------------


def test_safe_description_still_renders_bare_unquoted() -> None:
    """Locks in the 'only quote when unsafe' design: a description with no
    special YAML characters must render exactly as it did before the fix
    (no added quotes), to avoid golden-digest/output churn."""
    description = "Minimal manifest for M3.1a tests"
    skill = SkillAsset(name="demo-skill", description=description)

    rendered = format_skill_markdown(skill)

    assert f"description: {description}" in rendered.splitlines()


def test_safe_agent_description_still_renders_bare_unquoted() -> None:
    description = "Minimal manifest for M3.1a tests"
    agent = AgentAsset(name="demo-agent", description=description)

    rendered = format_agent_markdown(agent)

    assert f"description: {description}" in rendered.splitlines()


# ---------------------------------------------------------------------------
# _yaml_scalar unit tests (direct, pure-function coverage)
# ---------------------------------------------------------------------------


def test_yaml_scalar_safe_value_passes_through_unchanged() -> None:
    assert _yaml_scalar("a plain safe description") == "a plain safe description"


def test_yaml_scalar_quotes_space_hash() -> None:
    value = "The #ebooks channel"
    quoted = _yaml_scalar(value)
    assert quoted != value
    assert yaml.safe_load(quoted) == value


def test_yaml_scalar_quotes_colon_space() -> None:
    value = "repo: conventions"
    quoted = _yaml_scalar(value)
    assert quoted != value
    assert yaml.safe_load(quoted) == value


def test_yaml_scalar_quotes_trailing_colon() -> None:
    value = "trailing colon:"
    quoted = _yaml_scalar(value)
    assert quoted != value
    assert yaml.safe_load(quoted) == value


def test_yaml_scalar_quotes_leading_hash() -> None:
    value = "#starts-with-hash"
    quoted = _yaml_scalar(value)
    assert quoted != value
    assert yaml.safe_load(quoted) == value


def test_yaml_scalar_quotes_empty_string() -> None:
    quoted = _yaml_scalar("")
    assert quoted == '""'
    assert yaml.safe_load(quoted) == ""


def test_yaml_scalar_quotes_leading_trailing_whitespace() -> None:
    value = "  padded  "
    quoted = _yaml_scalar(value)
    assert quoted != value
    assert yaml.safe_load(quoted) == value


def test_yaml_scalar_quotes_reserved_words_case_insensitively() -> None:
    for reserved in ("null", "NULL", "true", "False", "yes", "No", "on", "Off", "~"):
        quoted = _yaml_scalar(reserved)
        assert quoted != reserved, f"{reserved!r} should have been quoted"
        assert yaml.safe_load(quoted) == reserved

    # A substring match on a reserved word should NOT trigger quoting.
    assert _yaml_scalar("nullable") == "nullable"
    assert _yaml_scalar("yesterday") == "yesterday"


def test_yaml_scalar_quotes_numeric_looking_strings() -> None:
    for numeric in ("42", "-3.14", "0", "1e10"):
        quoted = _yaml_scalar(numeric)
        assert quoted != numeric, f"{numeric!r} should have been quoted"
        assert yaml.safe_load(quoted) == numeric


def test_yaml_scalar_quotes_leading_indicator_chars() -> None:
    for value in ("- dash", "? question", "* star", "! bang", "@ at", "` tick"):
        quoted = _yaml_scalar(value)
        assert quoted != value, f"{value!r} should have been quoted"
        assert yaml.safe_load(quoted) == value


def test_yaml_scalar_quotes_embedded_newline_or_tab() -> None:
    for value in ("line one\nline two", "tab\there"):
        quoted = _yaml_scalar(value)
        assert quoted != value
        assert yaml.safe_load(quoted) == value
