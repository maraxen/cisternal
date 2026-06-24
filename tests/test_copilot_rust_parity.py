"""Copilot rust-parity emit and digest tests (M12.3)."""

from __future__ import annotations

import pytest

from cisterna.assets.bridge import (
    conformance_expected_path,
    conformance_manifest_path,
    resolve_bundle_hash_bin,
    rust_surface_digest,
)
from cisterna.assets.load import load_asset_report
from cisterna.assets.validate_golden import (
    emit_rust_parity_files,
    rust_parity_golden_digest_path,
    surface_digest_rust_parity,
)
from cisterna.export.copilot import CopilotEmitter

_MANIFEST = conformance_manifest_path()


def test_copilot_rust_parity_emit_matches_conformance_digest() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "copilot")
    expected = conformance_expected_path("copilot").read_text(encoding="utf-8").strip()
    assert digest == expected


def test_copilot_rust_parity_golden_tree() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "copilot")
    golden = rust_parity_golden_digest_path("copilot", manifest=_MANIFEST)
    assert golden.read_text(encoding="utf-8").strip() == digest


def test_copilot_legacy_emit_unchanged() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = CopilotEmitter().emit(bundle)
    assert "agents/recon.agent.md" in files
    assert "plugin.json" in files


def test_copilot_rust_parity_emit_file_set() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = emit_rust_parity_files(bundle, "copilot")
    assert set(files) == {
        "plugin.json",
        "agents/recon.agent.md",
        "skills/demo-skill/SKILL.md",
    }


@pytest.mark.skipif(
    resolve_bundle_hash_bin() is None,
    reason="CISTERNA_PRAXIA_ASSETS_BIN unset",
)
def test_copilot_rust_parity_matches_subprocess() -> None:
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    assert surface_digest_rust_parity(bundle, "copilot") == rust_surface_digest(
        bundle, "copilot"
    )
