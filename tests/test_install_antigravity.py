"""Tests for cisternal assets install --surface antigravity."""

from __future__ import annotations

from pathlib import Path

from cyclopts import App
from cisternal.cli import assets_app

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / ".praxia" / "manifest.toml"
)


def test_install_antigravity_dry_run(capsys) -> None:
    """Test assets install --surface antigravity --dry-run prints expected paths."""
    app = App()
    app.command(assets_app)

    app(
        [
            "assets",
            "install",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "antigravity",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert "plugin.json" in captured.out
    assert "skills/demo-skill/SKILL.md" in captured.out
    assert "would write antigravity plugin bundle to" in captured.out


def test_install_antigravity_writes_bundle(tmp_path: Path) -> None:
    """Test assets install --surface antigravity writes files to target out dir."""
    app = App()
    app.command(assets_app)

    out_dir = tmp_path / "my_plugin"

    app(
        [
            "assets",
            "install",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "antigravity",
            "--out",
            str(out_dir),
        ]
    )

    assert (out_dir / "plugin.json").is_file()
    assert (out_dir / "skills" / "demo-skill" / "SKILL.md").is_file()


def test_install_antigravity_scopes(capsys) -> None:
    """Test scope resolution for project vs user scope in antigravity install dry-run."""
    app = App()
    app.command(assets_app)

    # Project scope -> .agents/plugins/fixture-plugin
    app(
        [
            "assets",
            "install",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "antigravity",
            "--scope",
            "project",
            "--dry-run",
        ]
    )

    out_project = capsys.readouterr().out
    assert ".agents/plugins/fixture-plugin" in out_project

    # User scope -> .gemini/config/plugins/fixture-plugin
    app(
        [
            "assets",
            "install",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "antigravity",
            "--scope",
            "user",
            "--dry-run",
        ]
    )

    out_user = capsys.readouterr().out
    assert ".gemini/config/plugins/fixture-plugin" in out_user

    # Global scope alias -> .gemini/config/plugins/fixture-plugin
    app(
        [
            "assets",
            "install",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "antigravity",
            "--scope",
            "global",
            "--dry-run",
        ]
    )

    out_global = capsys.readouterr().out
    assert ".gemini/config/plugins/fixture-plugin" in out_global


def test_install_unsupported_surface() -> None:
    """Test assets install exits with code 2 on unsupported surface."""
    import pytest

    app = App()
    app.command(assets_app)

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "install",
                "--manifest",
                str(FIXTURE_MANIFEST),
                "--surface",
                "unsupported_surface",
            ]
        )

    assert exc_info.value.code == 2

