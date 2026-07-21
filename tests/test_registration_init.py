"""Tests for the cisternal top-level M2 public API surface (src/cisternal/__init__.py).

Verifies that all M2 symbols are importable from the cisternal top-level package
and that the exported objects are the canonical implementations.

Acceptance criteria exercised:
  AC-M2-1  — top-level tool is the same object as registration.decorator.tool
  AC-M2-7  — @cisternal.tool(registry="bathos") isolates to named registry
  AC-M2-9  — cisternal.wire() raises CisternalWireError on missing expected tools
  AC-M2-12 — cisternal.clear_registry() empties the default partition
"""

from __future__ import annotations

import asyncio

import fastmcp
import pytest

# --- M2 top-level imports (the public surface validated here) ---
import cisternal
from cisternal import (
    CisternalWireError,
    clear_registry,
    tool,
    wire,
)
from cisternal.registration.registry import _registry


# ---------------------------------------------------------------------------
# Fixture: clean state before and after each test (A7)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registries():
    """Wipe all known partitions before and after every test (A7)."""
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)
    yield
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)


# ---------------------------------------------------------------------------
# Top-level symbol availability
# ---------------------------------------------------------------------------

class TestTopLevelExports:
    """Verify all M2 symbols are reachable from the cisternal top-level package."""

    def test_tool_importable_from_top_level(self):
        """cisternal.tool is importable via top-level 'from cisternal import tool'."""
        assert callable(tool)

    def test_wire_importable_from_top_level(self):
        """cisternal.wire is importable via top-level 'from cisternal import wire'."""
        assert callable(wire)

    def test_cisternal_wire_error_importable(self):
        """cisternal.CisternalWireError is importable from top level."""
        assert issubclass(CisternalWireError, Exception)

    def test_clear_registry_importable_from_top_level(self):
        """cisternal.clear_registry is importable from top level."""
        assert callable(clear_registry)

    def test_wired_registry_accessible(self):
        """cisternal.WiredRegistry is accessible via lazy __getattr__."""
        WiredRegistry = cisternal.WiredRegistry
        assert WiredRegistry is not None

    def test_m1_exports_intact(self):
        """M1 telemetry exports are still present after M2 additions."""
        assert callable(cisternal.init)
        assert callable(cisternal.emit_event)
        assert callable(cisternal.span)
        assert callable(cisternal.aspan)
        assert callable(cisternal.status)

    def test_all_contains_m2_symbols(self):
        """__all__ includes all M2 public symbols."""
        assert "tool" in cisternal.__all__
        assert "wire" in cisternal.__all__
        assert "WiredRegistry" in cisternal.__all__
        assert "CisternalWireError" in cisternal.__all__
        assert "clear_registry" in cisternal.__all__

    def test_all_preserves_m1_symbols(self):
        """__all__ still includes all M1 telemetry public symbols."""
        assert "init" in cisternal.__all__
        assert "emit_event" in cisternal.__all__
        assert "span" in cisternal.__all__
        assert "aspan" in cisternal.__all__
        assert "status" in cisternal.__all__


# ---------------------------------------------------------------------------
# AC-M2-1: top-level tool is the canonical marker (pure passthrough)
# ---------------------------------------------------------------------------

class TestTopLevelToolIsCanonical:
    """AC-M2-1: cisternal.tool from the top level is the same object as
    cisternal.registration.decorator.tool, and decorated_fn is fn."""

    def test_top_level_tool_is_registration_tool(self):
        """cisternal.tool is the same object as cisternal.registration.decorator.tool."""
        from cisternal.registration.decorator import tool as reg_tool
        assert tool is reg_tool

    def test_tool_decorator_identity_via_top_level(self):
        """AC-M2-1: using top-level cisternal.tool — decorated_fn is fn."""
        def my_fn(x: int) -> int:
            return x

        decorated = tool(my_fn)
        assert decorated is my_fn

    def test_tool_iscoroutinefunction_preserved_via_top_level(self):
        """AC-M2-1: iscoroutinefunction not changed by cisternal.tool (top-level)."""
        @tool
        def sync_fn() -> None:
            pass

        @tool
        async def async_fn() -> None:
            pass

        assert not asyncio.iscoroutinefunction(sync_fn)
        assert asyncio.iscoroutinefunction(async_fn)


# ---------------------------------------------------------------------------
# AC-M2-7: named registry isolation via top-level @cisternal.tool
# ---------------------------------------------------------------------------

class TestNamedRegistryViaTopLevel:
    """AC-M2-7: @cisternal.tool(registry="bathos") isolates to named partition."""

    def test_named_registry_isolation_via_top_level_import(self):
        """AC-M2-7: using top-level 'tool' — named partition is isolated."""

        @tool(registry="bathos")
        def bathos_fn() -> None:
            pass

        assert "bathos_fn" in _registry("bathos")
        assert "bathos_fn" not in _registry("default")


# ---------------------------------------------------------------------------
# AC-M2-9: CisternalWireError from top-level wire()
# ---------------------------------------------------------------------------

class TestWireErrorViaTopLevel:
    """AC-M2-9: cisternal.wire() raises CisternalWireError on missing expected tools."""

    def test_wire_raises_cisternalwireerror_missing_tool(self):
        """AC-M2-9: top-level wire() raises CisternalWireError with .missing attribute."""

        @tool
        def present_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-init-wire-error")
        with pytest.raises(CisternalWireError) as exc_info:
            wire(server, expected=["missing_tool", "present_tool"])

        err = exc_info.value
        assert hasattr(err, "missing")
        assert "missing_tool" in err.missing
        assert "present_tool" not in err.missing


# ---------------------------------------------------------------------------
# AC-M2-12: top-level clear_registry()
# ---------------------------------------------------------------------------

class TestClearRegistryViaTopLevel:
    """AC-M2-12: cisternal.clear_registry() empties the default registry."""

    def test_clear_registry_empties_default_partition(self):
        """AC-M2-12: calling cisternal.clear_registry() from top-level empties 'default'."""

        @tool
        def my_tool() -> None:
            pass

        assert "my_tool" in _registry("default")
        clear_registry()
        assert len(_registry("default")) == 0

    def test_clear_registry_named_partition_via_top_level(self):
        """AC-M2-13: clear_registry(name='bathos') via top-level leaves 'default' untouched."""

        @tool
        def default_tool() -> None:
            pass

        @tool(registry="bathos")
        def bathos_tool() -> None:
            pass

        clear_registry(name="bathos")
        assert len(_registry("bathos")) == 0
        assert "default_tool" in _registry("default")
