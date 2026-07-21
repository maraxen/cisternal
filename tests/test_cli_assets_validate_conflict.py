"""Tests for validate exit 1 on composite command conflicts (debt #235)."""

from __future__ import annotations

from pathlib import Path

import cisternal
import pytest


def test_validate_conflict_exits_one(tmp_path: Path) -> None:
    """AC-M31a-2 validate path: conflicts → exit 1."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "commands").mkdir()
    (manifest_dir / "commands" / "foo.md").write_text("manifest body\n", encoding="utf-8")
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[plugin.export_command]
claude_code = ["commands/foo.md"]
""".strip(),
        encoding="utf-8",
    )

    @cisternal.tool
    def foo() -> None:
        """Registry foo."""

    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(manifest_dir / "manifest.toml"),
                "--surface",
                "claude",
            ]
        )
    assert exc_info.value.code == 1
