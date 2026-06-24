"""Rust parity digest tests via praxia bundle-hash (M12.1).

Requires ``CISTERNA_PRAXIA_ASSETS_BIN`` pointing at a built ``bundle-hash``
binary (see ``tests/conformance/README.md``). Subprocess integration tests skip
when unset; in-process emit parity tests always run.

Dual-lane export trust: ``golden_matrix`` (pytest marker) gates Python-canonical
legacy digests; the ``rust-parity`` CI job gates praxia byte parity (M12.4 blocking).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cisterna.assets.bridge import (
    conformance_expected_path,
    conformance_manifest_path,
    resolve_bundle_hash_bin,
    rust_surface_digest,
)
from cisterna.assets.load import load_asset_report

_SURFACES = ("claude", "cursor", "copilot", "antigravity")


def _bundle_hash_available() -> bool:
    return resolve_bundle_hash_bin() is not None


pytestmark = pytest.mark.skipif(
    not _bundle_hash_available(),
    reason="CISTERNA_PRAXIA_ASSETS_BIN unset — skip rust parity integration",
)


@pytest.mark.parametrize("surface", _SURFACES)
def test_rust_parity_manifest_minimal_digest(surface: str) -> None:
    """AC-M12-1j: subprocess digest matches pinned conformance expected."""
    manifest = conformance_manifest_path()
    report = load_asset_report(manifest=manifest)
    actual = rust_surface_digest(report.bundle, surface)
    expected = conformance_expected_path(surface).read_text(encoding="utf-8").strip()
    assert actual == expected


def test_rust_parity_digest_stable_on_repeat() -> None:
    """AC-M12-1f: two subprocess calls return the same digest."""
    manifest = conformance_manifest_path()
    bundle = load_asset_report(manifest=manifest).bundle
    first = rust_surface_digest(bundle, "claude")
    second = rust_surface_digest(bundle, "claude")
    assert first == second


def test_resolve_bundle_hash_bin_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CISTERNA_PRAXIA_ASSETS_BIN", "/tmp/bundle-hash")
    assert resolve_bundle_hash_bin() == "/tmp/bundle-hash"
