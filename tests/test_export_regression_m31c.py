"""M3.1c regression: prior surface goldens unchanged (AC-M31c-4)."""

from __future__ import annotations

from pathlib import Path

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.assets.validate_golden import golden_digest_path, surface_digest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_prior_surface_goldens_unchanged() -> None:
    """AC-M31c-4: claude, cursor, copilot digests still match after antigravity."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    for surface in ("claude", "cursor", "copilot"):
        digest = surface_digest(bundle, surface)
        golden = golden_digest_path(surface, "names_only")
        assert digest == golden.read_text(encoding="utf-8").strip()
