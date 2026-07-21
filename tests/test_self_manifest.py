"""Tests for M4.1a self-manifest (.praxia/manifest.toml)."""

from __future__ import annotations

from pathlib import Path

import pytest

SELF_MANIFEST = Path(__file__).resolve().parents[1] / ".praxia" / "manifest.toml"


def test_self_manifest_loads_clean() -> None:
    """AC-M4-1a: load without conflicts or warnings; non-empty bundle."""
    from cisternal.assets.manifest import ManifestAssetSource

    report = ManifestAssetSource(SELF_MANIFEST).load()
    assert report.conflicts == ()
    assert report.warnings == ()
    bundle = report.bundle
    assert bundle.skills or bundle.agents
    assert len(bundle.skills) >= 1
    assert len(bundle.agents) >= 1


def test_self_manifest_inspect_metadata_name() -> None:
    """AC-M4-1b: inspect JSON metadata.name matches [plugin].name."""
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["assets", "inspect", "--manifest", str(SELF_MANIFEST)])
    assert exc_info.value.code == 0

    # Re-run with capture via load + report_to_dict for stable assertion
    from cisternal.assets.load import load_asset_report
    from cisternal.assets.inspect_json import report_to_dict

    report = load_asset_report(manifest=SELF_MANIFEST)
    payload = report_to_dict(report)
    assert payload["bundle"]["metadata"]["name"] == "cisternal"
