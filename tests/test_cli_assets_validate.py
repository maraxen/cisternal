"""Tests for M3.1a validate CLI (AC-M31a-6, AC-M31a-8)."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def _invoke_app(args: list[str], *, exit_code: int = 0) -> None:
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code, (
        f"Expected exit {exit_code}; got {exc_info.value.code}"
    )


def test_validate_help() -> None:
    """validate --help exits zero."""
    from cisterna.cli import assets_app

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


def test_validate_missing_command_path_exits_one(tmp_path: Path) -> None:
    """AC-M31a-8: missing manifest command path → validate exit 1."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[plugin.export_command]
claude_code = ["commands/missing.md"]
""".strip(),
        encoding="utf-8",
    )

    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(manifest_dir / "manifest.toml"),
            "--surface",
            "claude",
        ],
        exit_code=1,
    )
