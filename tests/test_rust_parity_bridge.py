"""Tests for AssetBundle → PraxiaBundle bridge (M12.1)."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.bridge import (
    asset_bundle_to_praxia_json,
    load_conformance_bundle_json,
    normalize_praxia_json,
)
from cisternal.assets.load import load_asset_report


def test_bridge_matches_conformance_fixture() -> None:
    """AC-M12-1c: manifest_minimal bridge JSON matches conformance fixture."""
    manifest = Path("tests/fixtures/manifest_minimal/manifest.toml")
    report = load_asset_report(manifest=manifest)
    bridged = normalize_praxia_json(asset_bundle_to_praxia_json(report.bundle))
    expected = normalize_praxia_json(load_conformance_bundle_json())
    assert bridged == expected


def test_bridge_fixture_is_valid_json() -> None:
    fixture = Path("tests/conformance/manifest_minimal.bundle.json")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data["metadata"]["name"] == "fixture-plugin"
    assert data["workflows"] == []
    assert data["pipelines"] == []
