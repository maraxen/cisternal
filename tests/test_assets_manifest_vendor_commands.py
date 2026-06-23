"""Tests for M3.3c vendor export_command path loading."""

from __future__ import annotations

from pathlib import Path

from cisterna.assets.manifest import ManifestAssetSource

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "manifest_vendor_commands"
MANIFEST = FIXTURE_ROOT / "manifest.toml"


def test_vendor_export_commands_claude_and_cursor() -> None:
    """AC-M33c-1: fixture loads commands from claude_code + cursor keys."""
    report = ManifestAssetSource(MANIFEST).load()
    commands = report.bundle.commands
    by_name = {c.name: c for c in commands}
    assert set(by_name) == {"foo", "cursor-cmd"}
    assert "Claude vendor command" in by_name["foo"].body
    assert "Cursor vendor command" in by_name["cursor-cmd"].body


def test_vendor_export_dedupe_first_wins(tmp_path: Path) -> None:
    """Duplicate command stems across vendors: first vendor key wins."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    cmd_dir = manifest_dir / "commands"
    cmd_dir.mkdir()
    nested = cmd_dir / "nested"
    nested.mkdir()
    (cmd_dir / "shared.md").write_text("claude body\n", encoding="utf-8")
    (nested / "shared.md").write_text("cursor body\n", encoding="utf-8")
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[plugin.export_command]
claude_code = ["commands/shared.md"]
cursor = ["commands/nested/shared.md"]
""".strip(),
        encoding="utf-8",
    )

    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert len(report.bundle.commands) == 1
    assert report.bundle.commands[0].name == "shared"
    assert report.bundle.commands[0].body == "claude body\n"


def test_vendor_export_missing_path_warns(tmp_path: Path) -> None:
    """Missing command path produces warning and empty body."""
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
cursor = ["commands/missing.md"]
""".strip(),
        encoding="utf-8",
    )

    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert report.bundle.commands[0].name == "missing"
    assert report.bundle.commands[0].body == ""
    assert any("missing" in w for w in report.warnings)
