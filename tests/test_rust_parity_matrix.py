"""Rust-parity golden matrix (M12.5).

When ``.praxia/manifest.toml`` or ``tests/fixtures/manifest_dogfood_praxia/``
changes, refresh affected digests with ``write_rust_parity_golden_digest`` before merge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cisterna.assets.load import load_asset_report
from cisterna.assets.validate_golden import (
    resolve_golden_slug,
    rust_parity_golden_digest_path,
    surface_digest_rust_parity,
)

_TESTS = Path(__file__).parent
_LEGACY_MANIFEST = _TESTS / "fixtures" / "manifest_minimal" / "manifest.toml"
_DOGFOOD_MANIFEST = _TESTS / "fixtures" / "manifest_dogfood_praxia" / "manifest.toml"
_SELF_MANIFEST = Path(".praxia/manifest.toml")

_BUILTIN_SURFACES = ("antigravity", "claude", "copilot", "cursor")


def _rust_parity_matrix_cases() -> list[tuple[Path, str]]:
    cases: list[tuple[Path, str]] = []
    for manifest in (_LEGACY_MANIFEST, _DOGFOOD_MANIFEST, _SELF_MANIFEST):
        for surface in _BUILTIN_SURFACES:
            cases.append((manifest, surface))
    return cases


RUST_PARITY_MATRIX_CASES = _rust_parity_matrix_cases()


def _case_id(manifest: Path, surface: str) -> str:
    slug = resolve_golden_slug(manifest) or "unknown"
    return f"{slug}-{surface}"


@pytest.mark.parametrize(
    ("manifest", "surface"),
    RUST_PARITY_MATRIX_CASES,
    ids=[_case_id(m, s) for m, s in RUST_PARITY_MATRIX_CASES],
)
def test_rust_parity_matrix_digest(manifest: Path, surface: str) -> None:
    """AC-M12.5: in-process rust-parity digest matches golden for each slug × surface."""
    report = load_asset_report(manifest=manifest)
    assert report.conflicts == ()
    assert report.warnings == ()

    slug = resolve_golden_slug(manifest)
    digest = surface_digest_rust_parity(report.bundle, surface)
    golden_path = rust_parity_golden_digest_path(surface, manifest=manifest)
    assert golden_path.is_file(), f"missing rust-parity golden: {golden_path}"
    expected = golden_path.read_text(encoding="utf-8").strip()
    assert digest == expected, f"rust-parity digest mismatch: {slug}/{surface}"
