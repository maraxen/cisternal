"""Tests for CompositeAssetSource merge behavior."""

from __future__ import annotations

from pathlib import Path

import cisternal
from cisternal.assets.bundle import BundleMetadata
from cisternal.assets.composite import CompositeAssetSource


def test_composite_fills_registry_only_commands(tmp_path: Path) -> None:
    """Registry-only tools appear when not declared in manifest."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"
""".strip(),
        encoding="utf-8",
    )

    @cisternal.tool
    def only_registry() -> None:
        """From registry."""

    report = CompositeAssetSource(manifest_dir / "manifest.toml").load()
    names = [c.name for c in report.bundle.commands]
    assert "only_registry" in names
    assert report.conflicts == ()


def test_composite_metadata_override_applies_to_final_bundle(tmp_path: Path) -> None:
    """An explicit metadata override wins over the manifest's own (stale) fields.

    Regression: load() previously computed registry_meta from the override
    only to build the registry-side bundle for command merging, then
    discarded it when assembling the final bundle — silently ignoring
    --name/--version whenever --manifest was also given.
    """
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "stale-name"
version = "0.0.1"
description = "stale description"
requires_praxia = "0.0.0"
""".strip(),
        encoding="utf-8",
    )

    override = BundleMetadata(name="fresh-name", version="9.9.9", description="stale description")
    report = CompositeAssetSource(manifest_dir / "manifest.toml", metadata=override).load()

    assert report.bundle.metadata.name == "fresh-name"
    assert report.bundle.metadata.version == "9.9.9"
