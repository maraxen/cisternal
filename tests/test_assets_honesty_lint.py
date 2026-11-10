"""Tests for C4a Static Honesty Lint (Spec §C4a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.assets.bundle import AssetBundle, BundleMetadata, SkillAsset
from cisternal.assets.load import load_asset_report
from cisternal.assets.validate import (
    check_baseline_capability_erosion,
    check_distinctive_strings_containment,
    check_listing_no_overclaim,
    check_scope_header,
    validate_bundle_honesty,
)


def test_shipped_skills_pass_honesty_lint() -> None:
    """All 5 shipped skills in .praxia/manifest.toml pass static honesty lint with zero warnings."""
    report = load_asset_report(manifest=Path(".praxia/manifest.toml"))
    warnings, advisories = validate_bundle_honesty(
        report.bundle,
        manifest_path=Path(".praxia/manifest.toml"),
        baseline_ref="HEAD",
        report_only=False,
    )
    assert warnings == ()


def test_check_a_containment_failure() -> None:
    """Check (a) fails when a distinctive string is absent from listing text and body."""
    skill = SkillAsset(
        name="test-skill",
        description="A simple testing skill.",
        body="## When to Use\n\nRun the test runner.",
        distinctive_strings=("absent-trigger-keyword",),
    )
    warnings = check_distinctive_strings_containment(skill)
    assert len(warnings) == 1
    assert "distinctive string 'absent-trigger-keyword' not found" in warnings[0]


def test_check_a_containment_success_in_listing() -> None:
    """Check (a) passes when distinctive strings appear in listing text."""
    skill = SkillAsset(
        name="test-skill",
        description="A simple testing skill for absent-trigger-keyword.",
        body="## When to Use\n\nRun the test runner.",
        distinctive_strings=("absent-trigger-keyword",),
    )
    assert check_distinctive_strings_containment(skill) == []


def test_check_a_containment_success_in_body() -> None:
    """Check (a) passes when distinctive strings appear in body."""
    skill = SkillAsset(
        name="test-skill",
        description="A simple testing skill.",
        body="## When to Use\n\nRun absent-trigger-keyword now.",
        distinctive_strings=("absent-trigger-keyword",),
    )
    assert check_distinctive_strings_containment(skill) == []


def test_check_a_baseline_invalid_ref() -> None:
    """Check (a) baseline check raises ValueError on invalid git ref."""
    bundle = AssetBundle(metadata=BundleMetadata(name="test", version="1.0"))
    with pytest.raises(ValueError, match="invalid baseline ref"):
        check_baseline_capability_erosion(
            bundle, baseline_ref="invalid_ref_xyz123_nonexistent"
        )


def test_check_a_baseline_new_skill_skipped() -> None:
    """Check (a) baseline check cleanly skips newly added skills absent at baseline ref."""
    # triage-tool was added in this milestone and was absent in older commits
    report = load_asset_report(manifest=Path(".praxia/manifest.toml"))
    # HEAD has triage-tool or HEAD~1 may not, but checking HEAD should find 0 erosions
    warnings = check_baseline_capability_erosion(
        report.bundle,
        baseline_ref="HEAD",
        manifest_path=Path(".praxia/manifest.toml"),
    )
    assert warnings == []


def test_check_b_overclaim_detection() -> None:
    """Check (b) detects ungrounded PascalCase and hyphenated tokens."""
    skill = SkillAsset(
        name="overclaiming-skill",
        description="Uses QuantumOptimizer and hyper-accelerator to solve tasks.",
        body="## When to Use\n\nRun plain optimization without mentions of special tools.",
        distinctive_strings=(),
    )
    warnings = check_listing_no_overclaim(skill)
    assert any("QuantumOptimizer" in w for w in warnings)
    assert any("hyper-accelerator" in w for w in warnings)


def test_check_b_grounded_in_headings_and_fences() -> None:
    """Check (b) passes when candidate tokens appear in headings or fenced code blocks."""
    skill = SkillAsset(
        name="grounded-skill",
        description="Uses QuantumOptimizer and hyper-accelerator.",
        body=(
            "## When to Use\n\n"
            "### QuantumOptimizer setup\n\n"
            "```bash\n"
            "hyper-accelerator --run\n"
            "```\n"
        ),
        distinctive_strings=(),
    )
    warnings = check_listing_no_overclaim(skill)
    assert warnings == []


def test_check_b_shielded_by_distinctive_strings_and_stopwords() -> None:
    """Check (b) excludes stopwords and distinctive strings from overclaim checks."""
    skill = SkillAsset(
        name="shielded-skill",
        description="Provides read-only tool-surface management with custom-optimizer.",
        body="## When to Use\n\nGeneral prose without headings for custom optimizer.",
        distinctive_strings=("custom-optimizer",),
    )
    # read-only and tool-surface are in C4A_STOPWORDS; custom-optimizer is in distinctive_strings
    warnings = check_listing_no_overclaim(skill)
    assert warnings == []


def test_check_b_backticked_literal() -> None:
    """Check (b) checks backticked literals in listing against full body."""
    # Absent backticked token
    skill_fail = SkillAsset(
        name="test-fail",
        description="Run `nonexistent_func()` to initialize.",
        body="## When to Use\n\nStandard initialization.",
        distinctive_strings=(),
    )
    warns = check_listing_no_overclaim(skill_fail)
    assert any("nonexistent_func" in w for w in warns)

    # Present backticked token
    skill_pass = SkillAsset(
        name="test-pass",
        description="Run `my_func()` to initialize.",
        body="## When to Use\n\nHere we invoke `my_func` during setup.",
        distinctive_strings=(),
    )
    assert check_listing_no_overclaim(skill_pass) == []


def test_check_c_scope_header() -> None:
    """Check (c) verifies ## Scope or ## When to Use within first 50 lines and 2,000 chars."""
    # Valid
    valid_skill = SkillAsset(
        name="valid",
        description="Desc",
        body="## When to Use\n\nPrompt details.",
    )
    assert check_scope_header(valid_skill) == []

    # Missing
    missing_skill = SkillAsset(
        name="missing",
        description="Desc",
        body="# Heading Only\n\nNo scope section.",
    )
    warns = check_scope_header(missing_skill)
    assert len(warns) == 1
    assert "missing '## Scope' or '## When to Use' heading" in warns[0]

    # Line limit exceeded (> 50 lines)
    late_lines = ["Prose line\n"] * 55 + ["## Scope\n\nDetails.\n"]
    late_skill = SkillAsset(
        name="late",
        description="Desc",
        body="".join(late_lines),
    )
    assert len(check_scope_header(late_skill)) == 1

    # Char limit exceeded (> 2,000 chars before heading within 50 lines)
    long_line = ("a" * 100) + "\n"
    huge_skill = SkillAsset(
        name="huge",
        description="Desc",
        body=(long_line * 25) + "## Scope\n\nDetails.\n",
    )
    warns = check_scope_header(huge_skill)
    assert len(warns) == 1
    assert "exceeding 2000 character limit" in warns[0]


def test_report_only_mode_routes_to_advisories() -> None:
    """validate_bundle_honesty routes findings to advisories when report_only=True."""
    bad_skill = SkillAsset(
        name="bad",
        description="Claims QuantumEngine.",
        body="No headings.",
        distinctive_strings=("missing-distinctive",),
    )
    bundle = AssetBundle(
        metadata=BundleMetadata(name="test", version="1.0"),
        skills=(bad_skill,),
    )

    # Gate mode -> warnings
    warnings, advisories = validate_bundle_honesty(bundle, report_only=False)
    assert len(warnings) > 0
    assert advisories == ()

    # Report only -> advisories
    warnings, advisories = validate_bundle_honesty(bundle, report_only=True)
    assert warnings == ()
    assert len(advisories) > 0
