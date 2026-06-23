"""M3.1b regression: Claude surface unchanged (AC-M31b-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.assets.validate_golden import golden_digest_path, surface_digest
from cisterna.export.claude import ClaudeEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_claude_emitter_default_unchanged_vs_explicit_false() -> None:
    """ClaudeEmitter() matches emit_command_bodies=False (M3 parity)."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    default = ClaudeEmitter().emit(bundle)
    explicit = ClaudeEmitter(emit_command_bodies=False).emit(bundle)
    assert default == explicit


def test_claude_golden_names_only_still_valid() -> None:
    """validate golden claude/names_only digest unchanged after M3.1b emitters."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    digest = surface_digest(bundle, "claude")
    golden = golden_digest_path("claude", "names_only")
    assert digest == golden.read_text(encoding="utf-8").strip()


def test_validate_cli_claude_golden(tmp_path: Path) -> None:
    """CLI validate --surface claude still exits 0 for manifest_minimal."""
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(FIXTURE_MANIFEST),
                "--surface",
                "claude",
            ]
        )
    assert exc_info.value.code == 0
