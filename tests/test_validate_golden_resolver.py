"""Tests for manifest-scoped golden digest resolution (M4-GOLDEN)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cisterna.assets.validate_golden import golden_digest_path, resolve_golden_slug

MINIMAL = Path("tests/fixtures/manifest_minimal/manifest.toml")
SELF = Path(".praxia/manifest.toml")
DOGFOOD = Path("tests/fixtures/manifest_dogfood_praxia/manifest.toml")


def test_resolve_golden_slug_mapping() -> None:
    assert resolve_golden_slug(MINIMAL) == "legacy"
    assert resolve_golden_slug(SELF) == "self_manifest"
    assert resolve_golden_slug(DOGFOOD) == "dogfood_praxia"
    assert resolve_golden_slug(Path("/tmp/unknown/manifest.toml")) is None


def test_golden_paths_per_manifest() -> None:
    assert golden_digest_path("claude", manifest=MINIMAL).as_posix().endswith(
        "tests/golden/claude/names_only/digest.sha256"
    )
    assert golden_digest_path("claude", manifest=SELF).as_posix().endswith(
        "tests/golden/self_manifest/claude/names_only/digest.sha256"
    )
    assert golden_digest_path("cursor", manifest=DOGFOOD).as_posix().endswith(
        "tests/golden/dogfood_praxia/cursor/names_only/digest.sha256"
    )


def test_unknown_manifest_raises() -> None:
    with pytest.raises(ValueError, match="unknown manifest"):
        golden_digest_path("claude", manifest=Path("/tmp/nope/manifest.toml"))
