"""Tests for M3.3a public registration.snapshot() API (AC-M33a-1..3)."""

from __future__ import annotations

import cisternal
from cisternal.assets.source import registry_assets
from cisternal.registration.registry import (
    _REGISTRIES,
    list_registries,
    snapshot,
)


def test_snapshot_is_shallow_copy() -> None:
    """AC-M33a-1: mutating returned dict does not affect live registry."""
    cisternal.clear_registry("snap_test")
    try:

        @cisternal.tool(registry="snap_test")
        def alpha() -> None:
            """Alpha."""

        before = snapshot("snap_test")
        assert "alpha" in before
        before["injected"] = before["alpha"]  # type: ignore[index]
        after = snapshot("snap_test")
        assert "injected" not in after
    finally:
        cisternal.clear_registry("snap_test")


def test_list_registries_excludes_unknown() -> None:
    """AC-M33a-2: unknown partition not listed until created."""
    assert "never_created_partition" not in list_registries()


def test_registry_assets_unknown_does_not_create_partition() -> None:
    """AC-M33a-3: registry_assets on unknown name returns () without side effect."""
    name = "m33a_unknown_registry"
    assert name not in _REGISTRIES
    assert registry_assets(name) == ()
    assert name not in list_registries()
