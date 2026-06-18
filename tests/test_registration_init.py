"""Tests for the cisterna top-level M2 public API surface (src/cisterna/__init__.py).

Verifies that all M2 symbols are importable from the cisterna top-level package
and that the exported objects are the canonical implementations.

Acceptance criteria exercised:
  AC-M2-1  — top-level tool is the same object as registration.decorator.tool
  AC-M2-7  — @cisterna.tool(registry="bathos") isolates to named registry
  AC-M2-9  — cisterna.wire() raises CisternaWireError on missing expected tools
  AC-M2-12 — cisterna.clear_registry() empties the default partition
"""

from __future__ import annotations

import asyncio

import fastmcp
import pytest

# --- M2 top-level imports (the public surface validated here) ---
import cisterna
from cisterna import (
    CisternaWireError,
    clear_registry,
    tool,
    wire,
)
from cisterna.registration.registry import _registry


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
    """Verify all M2 symbols are reachable from the cisterna top-level package."""

    def test_tool_importable_from_top_level(self):
        """cisterna.tool is importable via top-level 'from cisterna import tool'."""
        assert callable(tool)

    def test_wire_importable_from_top_level(self):
        """cisterna.wire is importable via top-level 'from cisterna import wire'."""
        assert callable(wire)

    def test_cisterna_wire_error_importable(self):
        """cisterna.CisternaWireError is importable from top level."""
        assert issubclass(CisternaWireError, Exception)

    def test_clear_registry_importable_from_top_level(self):
        """cisterna.clear_registry is importable from top level."""
        assert callable(clear_registry)

    def test_wired_registry_accessible(self):
        """cisterna.WiredRegistry is accessible via lazy __getattr__."""
        WiredRegistry = cisterna.WiredRegistry
        assert WiredRegistry is not None

    def test_m1_exports_intact(self):
        """M1 telemetry exports are still present after M2 additions."""
        assert callable(cisterna.init)
        assert callable(cisterna.emit_event)
        assert callable(cisterna.span)
        assert callable(cisterna.aspan)
        assert callable(cisterna.status)

    def test_all_contains_m2_symbols(self):
        """__all__ includes all M2 public symbols."""
        assert "tool" in cisterna.__all__
        assert "wire" in cisterna.__all__
        assert "WiredRegistry" in cisterna.__all__
        assert "CisternaWireError" in cisterna.__all__
        assert "clear_registry" in cisterna.__all__

    def test_all_preserves_m1_symbols(self):
        """__all__ still includes all M1 telemetry public symbols."""
        assert "init" in cisterna.__all__
        assert "emit_event" in cisterna.__all__
        assert "span" in cisterna.__all__
        assert "aspan" in cisterna.__all__
        assert "status" in cisterna.__all__


# ---------------------------------------------------------------------------
# AC-M2-1: top-level tool is the canonical marker (pure passthrough)
# ---------------------------------------------------------------------------

class TestTopLevelToolIsCanonical:
    """AC-M2-1: cisterna.tool from the top level is the same object as
    cisterna.registration.decorator.tool, and decorated_fn is fn."""

    def test_top_level_tool_is_registration_tool(self):
        """cisterna.tool is the same object as cisterna.registration.decorator.tool."""
        from cisterna.registration.decorator import tool as reg_tool
        assert tool is reg_tool

    def test_tool_decorator_identity_via_top_level(self):
        """AC-M2-1: using top-level cisterna.tool — decorated_fn is fn."""
        def my_fn(x: int) -> int:
            return x

        decorated = tool(my_fn)
        assert decorated is my_fn

    def test_tool_iscoroutinefunction_preserved_via_top_level(self):
        """AC-M2-1: iscoroutinefunction not changed by cisterna.tool (top-level)."""
        @tool
        def sync_fn() -> None:
            pass

        @tool
        async def async_fn() -> None:
            pass

        assert not asyncio.iscoroutinefunction(sync_fn)
        assert asyncio.iscoroutinefunction(async_fn)


# ---------------------------------------------------------------------------
# AC-M2-7: named registry isolation via top-level @cisterna.tool
# ---------------------------------------------------------------------------

class TestNamedRegistryViaTopLevel:
    """AC-M2-7: @cisterna.tool(registry="bathos") isolates to named partition."""

    def test_named_registry_isolation_via_top_level_import(self):
        """AC-M2-7: using top-level 'tool' — named partition is isolated."""

        @tool(registry="bathos")
        def bathos_fn() -> None:
            pass

        assert "bathos_fn" in _registry("bathos")
        assert "bathos_fn" not in _registry("default")


# ---------------------------------------------------------------------------
# AC-M2-9: CisternaWireError from top-level wire()
# ---------------------------------------------------------------------------

class TestWireErrorViaTopLevel:
    """AC-M2-9: cisterna.wire() raises CisternaWireError on missing expected tools."""

    def test_wire_raises_cisternawireerror_missing_tool(self):
        """AC-M2-9: top-level wire() raises CisternaWireError with .missing attribute."""

        @tool
        def present_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-init-wire-error")
        with pytest.raises(CisternaWireError) as exc_info:
            wire(server, expected=["missing_tool", "present_tool"])

        err = exc_info.value
        assert hasattr(err, "missing")
        assert "missing_tool" in err.missing
        assert "present_tool" not in err.missing


# ---------------------------------------------------------------------------
# AC-M2-12: top-level clear_registry()
# ---------------------------------------------------------------------------

class TestClearRegistryViaTopLevel:
    """AC-M2-12: cisterna.clear_registry() empties the default registry."""

    def test_clear_registry_empties_default_partition(self):
        """AC-M2-12: calling cisterna.clear_registry() from top-level empties 'default'."""

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
