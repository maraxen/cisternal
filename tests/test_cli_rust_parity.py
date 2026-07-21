"""CLI tests for validate --rust-parity (M12.1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cisternal.assets.bridge import resolve_bundle_hash_bin


def _bundle_hash_available() -> bool:
    return resolve_bundle_hash_bin() is not None


def test_validate_rust_parity_missing_bin_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M12-1g: missing bundle-hash exits 1 with guidance."""
    monkeypatch.delenv("CISTERNAL_PRAXIA_ASSETS_BIN", raising=False)
    from cisternal.cli import app

    manifest = Path("tests/fixtures/manifest_minimal/manifest.toml")
    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(manifest),
                "--surface",
                "claude",
                "--rust-parity",
            ]
        )
    assert exc_info.value.code == 1


@pytest.mark.parametrize("surface", ["claude", "cursor", "copilot", "antigravity"])
@pytest.mark.skipif(
    not _bundle_hash_available(),
    reason="CISTERNAL_PRAXIA_ASSETS_BIN unset",
)
def test_validate_rust_parity_manifest_minimal_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """AC-M12-1f / AC-M12-3f: rust parity validate passes on conformance manifest."""
    bin_path = os.environ.get("CISTERNAL_PRAXIA_ASSETS_BIN", "")
    monkeypatch.setenv("CISTERNAL_PRAXIA_ASSETS_BIN", bin_path)
    from cisternal.cli import app

    manifest = Path("tests/fixtures/manifest_minimal/manifest.toml")
    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(manifest),
                "--surface",
                surface,
                "--rust-parity",
            ]
        )
    assert exc_info.value.code == 0

