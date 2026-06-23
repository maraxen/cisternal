"""Tests for CompositeAssetSource merge behavior."""

from __future__ import annotations

from pathlib import Path

import cisterna
from cisterna.assets.composite import CompositeAssetSource


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

    @cisterna.tool
    def only_registry() -> None:
        """From registry."""

    report = CompositeAssetSource(manifest_dir / "manifest.toml").load()
    names = [c.name for c in report.bundle.commands]
    assert "only_registry" in names
    assert report.conflicts == ()
