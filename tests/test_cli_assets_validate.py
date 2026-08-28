"""Tests for M3.1a validate CLI (AC-M31a-6, AC-M31a-8)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / ".praxia" / "manifest.toml"
)


def _invoke_app(args: list[str], *, exit_code: int = 0) -> None:
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code, (
        f"Expected exit {exit_code}; got {exc_info.value.code}"
    )


def test_validate_help() -> None:
    """validate --help exits zero."""
    from cisternal.cli import assets_app

    with pytest.raises(SystemExit) as exc_info:
        assets_app(["validate", "--help"])
    assert exc_info.value.code == 0


def test_validate_matches_golden_fixture() -> None:
    """AC-M31a-6: validate passes golden digest for manifest_minimal."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "claude",
        ]
    )


def test_validate_with_command_bodies_golden() -> None:
    """validate passes with_command_bodies golden for manifest_minimal."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "claude",
            "--emit-command-bodies",
        ]
    )


def test_validate_cursor_golden() -> None:
    """AC-M31b-4: validate --surface cursor passes golden."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "cursor",
        ]
    )


def test_validate_copilot_golden() -> None:
    """AC-M31b-4: validate --surface copilot passes golden."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "copilot",
        ]
    )


def test_validate_antigravity_golden() -> None:
    """AC-M31c-3: validate --surface antigravity passes golden."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "antigravity",
        ]
    )


def test_validate_unknown_surface_exits_two() -> None:
    """L33: unknown validate surface exits 2."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "linear",
        ],
        exit_code=2,
    )


def test_validate_cursor_missing_skill_path_exits_one(tmp_path: Path) -> None:
    """AC-M31b-7: missing skill path → validate exit 1 on cursor surface."""
    praxia = tmp_path / "plugin" / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.skills]]
name = "missing-skill"
path = "skills/missing/SKILL.md"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(praxia / "manifest.toml"),
            "--surface",
            "cursor",
        ],
        exit_code=1,
    )


def test_validate_missing_skill_path_exits_one(tmp_path: Path) -> None:
    """Missing skill path → validate exit 1 on claude surface."""
    praxia = tmp_path / "plugin" / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.skills]]
name = "missing-skill"
path = "skills/missing/SKILL.md"
""".strip()
        + "\n",
        encoding="utf-8",
    )

def test_validate_opencode_golden() -> None:
    """Validate --surface opencode passes golden."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "opencode",
        ]
    )


def test_validate_pi_golden() -> None:
    """Validate --surface pi passes golden."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "pi",
        ]
    )


def test_validate_jcode_golden() -> None:
    """Validate --surface jcode passes golden."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "jcode",
        ]
    )


def test_validate_non_claude_emit_command_bodies_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Validate --emit-command-bodies on non-claude surface resets bodies to False."""
    with caplog.at_level(logging.WARNING, logger="cisternal.cli"):
        _invoke_app(
            [
                "assets",
                "validate",
                "--manifest",
                str(FIXTURE_MANIFEST),
                "--surface",
                "opencode",
                "--emit-command-bodies",
            ]
        )
    assert "--emit-command-bodies ignored for surface 'opencode'" in caplog.text


def test_validate_external_manifest_skips_golden_comparison_and_exits_zero(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(#28) A well-formed external manifest -- not one of cisternal's own
    known fixtures/self-manifest, so there's no golden digest cisternal could
    possibly have pre-computed for it -- skips the golden-digest comparison
    and exits 0 (structural checks already passed), instead of the old
    exit-1 that made `validate` unusable for any downstream consumer's own
    manifest.

    Mirrors a realistic external repo layout (<repo>/.praxia/manifest.toml)
    with one real agent, so this exercises the golden-slug skip specifically
    -- not the separate empty-bundle check, which has its own test.
    """
    praxia_dir = tmp_path / ".praxia"
    praxia_dir.mkdir()
    (praxia_dir / "agents").mkdir()
    (praxia_dir / "agents" / "helper.md").write_text(
        "---\nname: helper\n---\nYou help with things.\n", encoding="utf-8"
    )
    unknown = praxia_dir / "manifest.toml"
    unknown.write_text(
        """
[plugin]
name = "unknown-slug-plugin"
version = "1.0.0"
description = "No golden slug exists"
requires_praxia = "0.0.0"

[[plugin.agents]]
name = "helper"
path = ".praxia/agents/helper.md"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.INFO, logger="cisternal.cli"):
        _invoke_app(
            [
                "assets",
                "validate",
                "--manifest",
                str(unknown),
                "--surface",
                "claude",
            ],
            exit_code=0,
        )
    assert "skipping golden-digest comparison" in caplog.text

