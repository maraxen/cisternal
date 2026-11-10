"""Tests for C6 triage-tool skill (Spec §C6)."""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib as tomli
except ImportError:
    import tomli

from cisternal.assets.load import load_asset_report
from cisternal.assets.skill_schema import check_skill


def test_triage_tool_manifest_registration() -> None:
    """triage-tool must be registered under [[plugin.skills]] in .praxia/manifest.toml."""
    manifest_path = Path(".praxia/manifest.toml")
    assert manifest_path.is_file()
    with open(manifest_path, "rb") as f:
        doc = tomli.load(f)
    skills = doc.get("plugin", {}).get("skills", [])
    skill_names = [s.get("name") for s in skills if isinstance(s, dict)]
    assert "triage-tool" in skill_names


def test_triage_tool_listing_character_cap() -> None:
    """triage-tool listing length must satisfy listing_chars <= 150 (Spec §C6)."""
    report = load_asset_report(manifest=Path(".praxia/manifest.toml"))
    triage_skill = next(
        (s for s in report.bundle.skills if s.name == "triage-tool"), None
    )
    assert triage_skill is not None
    assert triage_skill.listing_chars <= 150
    assert len(triage_skill.description) > 0


def test_triage_tool_non_destructive_safety() -> None:
    """triage-tool must be non-destructive: no commands modifying settings.json or .claude.json."""
    skill_path = Path(".praxia/skills/triage-tool/SKILL.md")
    ref_path = Path(".praxia/skills/triage-tool/references/triage_workflow.md")
    assert skill_path.is_file()
    assert ref_path.is_file()

    for path in (skill_path, ref_path):
        text = path.read_text(encoding="utf-8")
        # Prohibit instructions to echo/write/sed/rm settings.json or .claude.json
        assert not re.search(r">\s*~?/\.claude(?:/settings)?\.json", text)
        assert not re.search(r"rm\s+~?/\.claude", text)
        assert not re.search(r"sed\s+.*settings\.json", text)
        # Affirm non-destructive documentation
        assert "non-destructive" in text.lower()


def test_triage_tool_schema_and_headings() -> None:
    """triage-tool frontmatter conforms to schema and has Scope/When to Use headings."""
    report = load_asset_report(manifest=Path(".praxia/manifest.toml"))
    triage_skill = next(
        (s for s in report.bundle.skills if s.name == "triage-tool"), None
    )
    assert triage_skill is not None

    warnings = check_skill(triage_skill)
    assert warnings == []

    assert 1 <= len(triage_skill.distinctive_strings) <= 5
    for s in triage_skill.distinctive_strings:
        assert len(s.strip()) >= 3

    # Check headings
    body_lines = triage_skill.body.splitlines()[:50]
    has_when_to_use = any(
        re.match(r"^##\s+When to Use\b", line, re.IGNORECASE) for line in body_lines
    )
    has_scope = any(
        re.match(r"^##\s+Scope\b", line, re.IGNORECASE) for line in body_lines
    )
    assert has_when_to_use
    assert has_scope
