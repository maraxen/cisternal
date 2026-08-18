"""Tests for CompositeAssetSource merge when the manifest has no commands."""

from __future__ import annotations

from pathlib import Path

import cisternal
from cisternal.assets.composite import CompositeAssetSource


def test_validate_conflict_no_manifest_commands(tmp_path: Path) -> None:
    """Registry tools plus a command-less manifest produce no conflicts."""
    praxia = tmp_path / "plugin" / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    @cisternal.tool
    def foo() -> None:
        """Registry foo."""

    report = CompositeAssetSource(praxia / "manifest.toml").load()
    assert report.conflicts == ()
    assert any(c.name == "foo" for c in report.bundle.commands)
