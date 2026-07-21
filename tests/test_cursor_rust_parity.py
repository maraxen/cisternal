"""Cursor rust-parity emit and digest tests (M12.3)."""

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
from cisternal.export.cursor import CursorEmitter

_MANIFEST = conformance_manifest_path()


def test_cursor_rust_parity_emit_matches_conformance_digest() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "cursor")
    expected = conformance_expected_path("cursor").read_text(encoding="utf-8").strip()
    assert digest == expected


def test_cursor_rust_parity_golden_tree() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "cursor")
    golden = rust_parity_golden_digest_path("cursor", manifest=_MANIFEST)
    assert golden.read_text(encoding="utf-8").strip() == digest


def test_cursor_legacy_emit_unchanged() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = CursorEmitter().emit(bundle)
    assert "agents/recon.agent.md" in files


def test_cursor_rust_parity_emit_file_set() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = emit_rust_parity_files(bundle, "cursor")
    assert set(files) == {
        ".cursor-plugin/plugin.json",
        ".cursor/hooks.json",
        "skills/demo-skill/SKILL.md",
    }
    assert "agents/recon.agent.md" not in files


@pytest.mark.skipif(
    resolve_bundle_hash_bin() is None,
    reason="CISTERNAL_PRAXIA_ASSETS_BIN unset",
)
def test_cursor_rust_parity_matches_subprocess() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    assert surface_digest_rust_parity(bundle, "cursor") == rust_surface_digest(
        bundle, "cursor"
    )
