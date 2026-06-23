"""Tests for minimal_emitter example package."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "manifest_minimal"
    / "manifest.toml"
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_minimal_emitter_installed() -> None:
    import shutil
    import subprocess

    example_root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not available for minimal_emitter install")
    subprocess.run(
        [uv, "pip", "install", "-e", str(example_root), "-q"],
        check=True,
    )


def test_minimal_surface_registered() -> None:
    """AC-M4-4b: minimal appears in list_emitter_surfaces when installed."""
    from cisterna.export.registry import list_emitter_surfaces

    surfaces = list_emitter_surfaces()
    assert "minimal" in surfaces
    assert "claude" in surfaces


def test_minimal_emitter_emits_file() -> None:
    """AC-M4-4c: get_emitter('minimal').emit(bundle) returns ≥1 file."""
    from cisterna.assets.load import load_asset_report
    from cisterna.export.registry import get_emitter

    report = load_asset_report(manifest=FIXTURE_MANIFEST)
    emitter = get_emitter("minimal")
    assert emitter is not None
    files = emitter.emit(report.bundle)
    assert "minimal-plugin.json" in files
