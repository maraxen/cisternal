"""Tests for manifest-scoped golden digest resolution (M4-GOLDEN)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.assets.validate_golden import golden_digest_path, resolve_golden_slug

MINIMAL = Path("tests/fixtures/manifest_minimal/.praxia/manifest.toml")
SELF = Path(".praxia/manifest.toml")
DOGFOOD = Path("tests/fixtures/manifest_dogfood_praxia/.praxia/manifest.toml")


def test_resolve_golden_slug_mapping() -> None:
    assert resolve_golden_slug(MINIMAL) == "legacy"
    assert resolve_golden_slug(SELF) == "self_manifest"
    assert resolve_golden_slug(DOGFOOD) == "dogfood_praxia"
    assert resolve_golden_slug(Path("/tmp/unknown/manifest.toml")) is None


def test_golden_paths_per_manifest() -> None:
    assert (
        golden_digest_path("claude", manifest=MINIMAL)
        .as_posix()
        .endswith("tests/golden/claude/names_only/digest.sha256")
    )
    assert (
        golden_digest_path("claude", manifest=SELF)
        .as_posix()
        .endswith("tests/golden/self_manifest/claude/names_only/digest.sha256")
    )
    assert (
        golden_digest_path("cursor", manifest=DOGFOOD)
        .as_posix()
        .endswith("tests/golden/dogfood_praxia/cursor/names_only/digest.sha256")
    )


def test_unknown_manifest_raises() -> None:
    with pytest.raises(ValueError, match="unknown manifest"):
        golden_digest_path("claude", manifest=Path("/tmp/nope/manifest.toml"))


def test_tmp_praxia_manifest_is_not_self_slug(tmp_path: Path) -> None:
    """Only this repo's ``.praxia/manifest.toml`` maps to self_manifest."""
    nested = tmp_path / "plugin" / ".praxia" / "manifest.toml"
    nested.parent.mkdir(parents=True)
    nested.write_text('[plugin]\nname = "x"\n', encoding="utf-8")
    assert resolve_golden_slug(nested) is None
