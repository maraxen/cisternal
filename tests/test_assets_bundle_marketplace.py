"""Tests for MarketplaceAsset — local Claude Code marketplace metadata on AssetBundle."""

from __future__ import annotations

import pytest

from cisternal.assets.bundle import AssetBundle, BundleMetadata, MarketplaceAsset


def _meta() -> BundleMetadata:
    return BundleMetadata(name="test", version="1.0.0")


def test_marketplace_asset_is_frozen() -> None:
    marketplace = MarketplaceAsset(name="test-marketplace", owner_name="Someone")
    with pytest.raises(AttributeError):
        marketplace.name = "other"  # type: ignore[misc]


def test_marketplace_asset_defaults() -> None:
    marketplace = MarketplaceAsset(name="test-marketplace")
    assert marketplace.owner_name == ""
    assert marketplace.owner_email == ""
    assert marketplace.owner_url == ""


def test_bundle_marketplace_defaults_to_none() -> None:
    bundle = AssetBundle(metadata=_meta())
    assert bundle.marketplace is None


def test_bundle_marketplace_roundtrips() -> None:
    marketplace = MarketplaceAsset(name="test-marketplace", owner_name="Someone")
    bundle = AssetBundle(metadata=_meta(), marketplace=marketplace)
    assert bundle.marketplace is marketplace


def test_bundle_with_marketplace_is_hashable() -> None:
    bundle = AssetBundle(
        metadata=_meta(),
        marketplace=MarketplaceAsset(name="test-marketplace"),
    )
    hash(bundle)  # must not raise
