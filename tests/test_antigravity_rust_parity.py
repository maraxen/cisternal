"""Antigravity rust-parity emit and digest tests (M12.3)."""

from __future__ import annotations

import pytest

from cisternal.assets.bridge import (
    conformance_expected_path,
    conformance_manifest_path,
    resolve_bundle_hash_bin,
    rust_surface_digest,
)
from cisternal.assets.load import load_asset_report
from cisternal.assets.validate_golden import (
    emit_rust_parity_files,
    rust_parity_golden_digest_path,
    surface_digest_rust_parity,
)
from cisternal.export.antigravity import AntigravityEmitter

_MANIFEST = conformance_manifest_path()


def test_antigravity_rust_parity_emit_matches_conformance_digest() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "antigravity")
    expected = conformance_expected_path("antigravity").read_text(encoding="utf-8").strip()
    assert digest == expected


def test_antigravity_rust_parity_golden_tree() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "antigravity")
    golden = rust_parity_golden_digest_path("antigravity", manifest=_MANIFEST)
    assert golden.read_text(encoding="utf-8").strip() == digest


def test_antigravity_legacy_emit_reflects_m13_1_real_plugin_format() -> None:
    """M13.1 intentionally diverges legacy (non-rust-parity) mode from the
    frozen rust-parity shape below: real Antigravity plugins have no
    file-based agent registration and use a root ``hooks.json``, not
    ``hooks/hooks.json``. The rust-parity path (exercised by the other tests
    in this file) is untouched — it stays pinned to praxia's last-committed
    Antigravity adapter until that side lands its own M13.1-equivalent
    rewrite and conformance goldens are regenerated.
    """
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = AntigravityEmitter().emit(bundle)
    assert "agents/recon.md" not in files
    assert not any(path.startswith("agents/") for path in files)
    assert "hooks.json" in files
    assert "hooks/hooks.json" not in files


def test_antigravity_rust_parity_emit_file_set() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = emit_rust_parity_files(bundle, "antigravity")
    assert set(files) == {
        "gemini-extension.json",
        "agents/recon.md",
        "skills/demo-skill/SKILL.md",
        "hooks/hooks.json",
    }


@pytest.mark.skipif(
    resolve_bundle_hash_bin() is None,
    reason="CISTERNAL_PRAXIA_ASSETS_BIN unset",
)
def test_antigravity_rust_parity_matches_subprocess() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    assert surface_digest_rust_parity(bundle, "antigravity") == rust_surface_digest(
        bundle, "antigravity"
    )
