"""Tests for export --surface (AC-M31b-8)."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def _invoke_app(args: list[str], *, exit_code: int = 0) -> None:
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code


def test_export_surface_cursor_writes_layout(tmp_path: Path) -> None:
    """AC-M31b-8: export --surface cursor writes Cursor plugin layout."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(
        [
            "assets",
            "export",
            "--surface",
            "cursor",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--out",
            str(out_dir),
        ]
    )

    assert (out_dir / ".cursor-plugin" / "plugin.json").is_file()
    assert (out_dir / ".cursor" / "hooks.json").is_file()
    assert (out_dir / "agents" / "recon.agent.md").is_file()


def test_export_surface_antigravity_writes_layout(tmp_path: Path) -> None:
    """M13.1: export --surface antigravity writes the real plugin layout (no agents)."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(
        [
            "assets",
            "export",
            "--surface",
            "antigravity",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--out",
            str(out_dir),
        ]
    )

    assert (out_dir / "plugin.json").is_file()
    assert (out_dir / "skills" / "demo-skill" / "SKILL.md").is_file()
    assert (out_dir / "hooks.json").is_file()
    assert not (out_dir / "agents").exists()
    assert not (out_dir / "gemini-extension.json").exists()


def test_export_unknown_surface_exits_two(tmp_path: Path) -> None:
    """L33: unknown export surface exits 2."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _invoke_app(
        [
            "assets",
            "export",
            "--surface",
            "linear",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--out",
            str(out_dir),
        ],
        exit_code=2,
    )
