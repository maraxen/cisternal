"""Claude rust-parity emit and digest tests (M12.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.assets.bridge import (
    conformance_expected_path,
    conformance_manifest_path,
    resolve_bundle_hash_bin,
    rust_surface_digest,
)
from cisternal.assets.load import load_asset_report
from cisternal.assets.validate_golden import (
    emit_claude_rust_parity_files,
    rust_parity_golden_digest_path,
    surface_digest_rust_parity,
)
from cisternal.export._hash import bundle_sha256, bundle_sha256_rust
from cisternal.export.claude import ClaudeEmitter

_MANIFEST = conformance_manifest_path()


def test_bundle_sha256_rust_differs_from_python_canonical() -> None:
    """Rust and Python hash algos diverge on the same file dict (spike baseline)."""
    files = {"a.txt": "hello"}
    assert bundle_sha256(files) != bundle_sha256_rust(files)


def test_claude_rust_parity_emit_matches_conformance_digest() -> None:
    """AC-M12-2a/2c: in-process emit + rust hash matches pinned conformance expected."""
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "claude")
    expected = conformance_expected_path("claude").read_text(encoding="utf-8").strip()
    assert digest == expected


def test_claude_rust_parity_golden_tree() -> None:
    """AC-M12-2c: tests/golden/rust_parity/ legacy claude digest matches emit."""
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    digest = surface_digest_rust_parity(bundle, "claude")
    golden = rust_parity_golden_digest_path("claude", manifest=_MANIFEST)
    assert golden.read_text(encoding="utf-8").strip() == digest


def test_claude_legacy_emit_still_has_provenance_sidecar() -> None:
    """Default (non-rust-parity) ClaudeEmitter still emits the provenance sidecar.

    M13 note: prior to M13 this test also asserted ``agents/recon.md`` was
    absent from the legacy emit path — that was the M3.1b-frozen, non-standard
    plugin.json-only shape. M13 intentionally reverses that freeze (see
    ``cisternal.export.claude`` module docstring): the legacy path now emits
    ``agents/<name>.md``/``skills/<name>/SKILL.md``/``hooks/hooks.json``/
    ``.mcp.json`` just like the rust-parity path does, modulo the provenance
    sidecar (which rust-parity omits and legacy keeps).
    """
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = ClaudeEmitter().emit(bundle)
    assert ".claude-plugin/cisternal-provenance.json" in files
    assert "agents/recon.md" in files


def test_claude_rust_parity_emit_file_set() -> None:
    """Rust parity emit includes praxia-shaped paths, no provenance."""
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    files = emit_claude_rust_parity_files(bundle)
    assert set(files) == {
        ".claude-plugin/plugin.json",
        "agents/recon.md",
        "skills/demo-skill/SKILL.md",
        "hooks/hooks.json",
    }
    assert "cisternal-provenance" not in "".join(files)


@pytest.mark.skipif(
    resolve_bundle_hash_bin() is None,
    reason="CISTERNAL_PRAXIA_ASSETS_BIN unset",
)
def test_claude_rust_parity_matches_subprocess() -> None:
    """AC-M12-2b: Python rust-parity digest matches bundle-hash subprocess."""
    bundle = load_asset_report(manifest=_MANIFEST).bundle
    in_process = surface_digest_rust_parity(bundle, "claude")
    subprocess_digest = rust_surface_digest(bundle, "claude")
    assert in_process == subprocess_digest


def test_rust_parity_golden_path_layout() -> None:
    path = rust_parity_golden_digest_path("claude", manifest=_MANIFEST)
    assert path == (
        Path(__file__).resolve().parents[0]
        / "golden"
        / "rust_parity"
        / "legacy"
        / "claude"
        / "digest.sha256"
    )
