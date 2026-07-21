"""Export trust golden matrix (M11).

When ``.praxia/manifest.toml`` or ``tests/fixtures/manifest_dogfood_praxia/``
changes, refresh affected digests with ``write_golden_digest`` before merge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.assets.load import load_asset_report
from cisternal.assets.validate_golden import (
    golden_digest_path,
    resolve_golden_slug,
    surface_digest,
)

_TESTS = Path(__file__).parent
_LEGACY_MANIFEST = _TESTS / "fixtures" / "manifest_minimal" / "manifest.toml"
_DOGFOOD_MANIFEST = _TESTS / "fixtures" / "manifest_dogfood_praxia" / "manifest.toml"
_SELF_MANIFEST = Path(".praxia/manifest.toml")

_BUILTIN_SURFACES = ("antigravity", "claude", "copilot", "cursor")


def _golden_matrix_cases() -> list[tuple[Path, str, bool]]:
    cases: list[tuple[Path, str, bool]] = []
    for manifest in (_LEGACY_MANIFEST, _DOGFOOD_MANIFEST, _SELF_MANIFEST):
        for surface in _BUILTIN_SURFACES:
            cases.append((manifest, surface, False))
        cases.append((manifest, "claude", True))
    return cases


GOLDEN_MATRIX_CASES = _golden_matrix_cases()


def _case_id(manifest: Path, surface: str, emit_command_bodies: bool) -> str:
    slug = resolve_golden_slug(manifest) or "unknown"
    mode = "with_command_bodies" if emit_command_bodies else "names_only"
    return f"{slug}-{surface}-{mode}"


@pytest.mark.golden_matrix
@pytest.mark.parametrize(
    ("manifest", "surface", "emit_command_bodies"),
    GOLDEN_MATRIX_CASES,
    ids=[_case_id(m, s, b) for m, s, b in GOLDEN_MATRIX_CASES],
)
def test_golden_matrix_digest(
    manifest: Path,
    surface: str,
    emit_command_bodies: bool,
) -> None:
    """AC-M11-1: load, structural checks, and digest parity for each matrix tuple."""
    report = load_asset_report(manifest=manifest)
    assert report.conflicts == ()
    assert report.warnings == ()

    mode = "with_command_bodies" if emit_command_bodies else "names_only"
    slug = resolve_golden_slug(manifest)
    digest = surface_digest(
        report.bundle,
        surface,
        emit_command_bodies=emit_command_bodies,
    )
    golden_path = golden_digest_path(surface, mode, manifest=manifest)
    assert golden_path.is_file(), f"missing golden digest: {golden_path}"
    expected = golden_path.read_text(encoding="utf-8").strip()
    assert digest == expected, f"digest mismatch: {slug}/{surface}/{mode}"
