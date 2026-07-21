"""M3.2 regression: registry dispatch smoke (AC-M32-7).

Full manifest×surface×mode golden coverage lives in ``tests/test_golden_matrix.py`` (M11).
"""

from __future__ import annotations

from pathlib import Path

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.registry import get_emitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_registry_dispatch_claude_emits() -> None:
    """AC-M32-7: get_emitter still dispatches claude after entry-point registry."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    emitter = get_emitter("claude")
    assert emitter is not None
    files = emitter.emit(bundle)
    assert files
