"""M3.2 regression: all golden digests unchanged after registry dispatch (AC-M32-7)."""

from __future__ import annotations

from pathlib import Path

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.assets.validate_golden import golden_digest_path, surface_digest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_all_golden_digests_unchanged_after_m32() -> None:
    """AC-M32-7: five golden modes still match manifest_minimal emission."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    cases = [
        ("claude", "names_only", False),
        ("claude", "with_command_bodies", True),
        ("cursor", "names_only", False),
        ("copilot", "names_only", False),
        ("antigravity", "names_only", False),
    ]
    for surface, mode, bodies in cases:
        digest = surface_digest(bundle, surface, emit_command_bodies=bodies)
        golden = golden_digest_path(surface, mode)
        assert digest == golden.read_text(encoding="utf-8").strip(), surface
