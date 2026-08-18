"""Tests for M4.1b praxia-scale dogfood fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

DOGFOOD_MANIFEST = (
    Path(__file__).parent
    / "fixtures"
    / "manifest_dogfood_praxia"
    / ".praxia"
    / "manifest.toml"
)


def test_dogfood_praxia_fixture_richness() -> None:
    """AC-M4-1c: fixture has skills, agents, hooks, L14 extensions."""
    from cisternal.assets.load import load_asset_report
    from cisternal.assets.manifest import ManifestAssetSource

    report = load_asset_report(manifest=DOGFOOD_MANIFEST)
    assert report.warnings == ()
    bundle = report.bundle
    assert len(bundle.skills) >= 2
    assert len(bundle.agents) >= 1
    assert len(bundle.hook_specs) >= 1
    assert ManifestAssetSource(DOGFOOD_MANIFEST).load().bundle.commands == ()


def test_dogfood_missing_workflow_validate_exits_one(tmp_path: Path) -> None:
    """AC-M4-1d: missing workflow path → validate exit 1."""
    praxia = tmp_path / "broken" / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "broken"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.workflows]]
name = "missing"
path = "workflows/missing.toml"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(praxia / "manifest.toml"),
                "--surface",
                "claude",
            ]
        )
    assert exc_info.value.code == 1
