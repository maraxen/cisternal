"""Shared pytest fixtures and helpers for cisterna registration tests.

Provides a single shared SpyAdapter class used across test modules to avoid
duplication and ensure consistent spy behavior.

Also provides an autouse fixture that clears ALL registry partitions before
and after each test (B3 resolution, spec §test-infrastructure).  This makes
test_assets_*.py and test_export_*.py order-independent regardless of how
many named partitions are created during a test run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class SpyAdapter:
    """Minimal spy adapter for asserting no adapter methods are called.

    Tracks all calls to emit_start, emit_end, emit_error, shape_ok, shape_error.
    Does NOT subclass cisterna.adapters.base.AdapterBase to avoid a hard import
    dependency on adapters from other repos.  wire() and compose_mcp_callable()
    accept any object for the 'adapter' parameter and intentionally never call
    any method on it (C5 / AC-M2-6).
    """

    calls: list[str] = field(default_factory=list)

    def emit_start(self, *a: Any, **kw: Any) -> None:
        self.calls.append("emit_start")

    def emit_end(self, *a: Any, **kw: Any) -> None:
        self.calls.append("emit_end")

    def emit_error(self, *a: Any, **kw: Any) -> None:
        self.calls.append("emit_error")

    def shape_ok(self, *a: Any, **kw: Any) -> Any:
        self.calls.append("shape_ok")

    def shape_error(self, *a: Any, **kw: Any) -> Any:
        self.calls.append("shape_error")


@pytest.fixture()
def spy_adapter() -> SpyAdapter:
    """Return a fresh SpyAdapter instance for asserting no adapter methods are called."""
    return SpyAdapter()


# ---------------------------------------------------------------------------
# Registry isolation (B3 / spec §test-infrastructure)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_all_registries() -> Any:
    """Clear ALL registry partitions before and after each test.

    This prevents cross-test registry contamination when tests register tools
    in various named partitions.  The fixture runs at function scope (default)
    so each test starts with a clean slate.

    Implementation: accesses cisterna.registration.registry._REGISTRIES
    directly to discover and clear ALL partitions, not just "default".
    cisterna.clear_registry() only clears one partition at a time, so we
    call it for each known partition, then also clear the live dict entirely.
    """
    from cisterna.registration.registry import _REGISTRIES

    # --- SETUP: clear before the test ---
    _REGISTRIES.clear()

    yield

    # --- TEARDOWN: clear after the test ---
    _REGISTRIES.clear()
