"""Tests for cisternal.registration — registry.py + decorator.py.

Acceptance criteria covered:
  AC-M2-1   — @tool is a pure marker: decorated_fn is fn, iscoroutinefunction unchanged.
  AC-M2-7   — Named isolation: @tool(registry="bathos") does NOT pollute "default".
  AC-M2-8   — Registry-scoped selection precursor: _snapshot("contemplex") is isolated.
  AC-M2-11  — Snapshot semantics: tools decorated after a snapshot are absent from it.
  AC-M2-12  — clear_registry() empties "default" only; other partitions survive.
  AC-M2-13  — clear_registry(name="bathos") empties "bathos" only; "default" survives.
  AC-M2-14  — Direct call passthrough: calling a @tool-decorated fn returns original value.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from cisternal.registration.registry import (
    _registry,
    _snapshot,
    clear_registry,
)
from cisternal.registration.decorator import tool


# ---------------------------------------------------------------------------
# Fixture: clean slate before and after every test (A7)
# ---------------------------------------------------------------------------

# Track all partition names we touch across the test session so teardown can
# clean them reliably.
_KNOWN_PARTITIONS = {"default", "bathos", "contemplex", "other"}


@pytest.fixture(autouse=True)
def clean_registries():
    """Wipe all known partitions before each test; re-wipe after (A7)."""
    # Pre-test cleanup
    for partition in _KNOWN_PARTITIONS:
        clear_registry(name=partition)

    yield

    # Post-test teardown
    for partition in _KNOWN_PARTITIONS:
        clear_registry(name=partition)


# ---------------------------------------------------------------------------
# AC-M2-1: purity for sync and async functions
# ---------------------------------------------------------------------------

class TestPurity:
    def test_bare_decorator_returns_fn_unchanged_sync(self):
        """@tool (bare) on a sync fn: decorated_fn is fn."""
        def my_sync(x: int) -> int:
            return x * 2

        result = tool(my_sync)
        assert result is my_sync

    def test_bare_decorator_returns_fn_unchanged_async(self):
        """@tool (bare) on an async fn: decorated_fn is fn."""
        async def my_async(x: int) -> int:
            return x * 2

        result = tool(my_async)
        assert result is my_async

    def test_parameterised_decorator_returns_fn_unchanged_sync(self):
        """@tool(registry='r') on a sync fn: decorated_fn is fn."""
        def my_sync(x: int) -> int:
            return x

        result = tool(registry="other")(my_sync)
        assert result is my_sync

    def test_parameterised_decorator_returns_fn_unchanged_async(self):
        """@tool(registry='r') on an async fn: decorated_fn is fn."""
        async def my_async(x: int) -> int:
            return x

        result = tool(registry="other")(my_async)
        assert result is my_async

    def test_iscoroutinefunction_preserved_sync(self):
        """iscoroutinefunction is False for a sync fn after @tool."""
        @tool
        def sync_fn() -> None:
            pass

        assert not asyncio.iscoroutinefunction(sync_fn)

    def test_iscoroutinefunction_preserved_async(self):
        """iscoroutinefunction is True for an async fn after @tool."""
        @tool
        async def async_fn() -> None:
            pass

        assert asyncio.iscoroutinefunction(async_fn)


# ---------------------------------------------------------------------------
# AC-M2-7: named isolation
# ---------------------------------------------------------------------------

class TestNamedIsolation:
    def test_tool_in_named_registry_not_in_default(self):
        """@tool(registry='bathos') registers in 'bathos', not in 'default'."""
        @tool(registry="bathos")
        def bathos_fn() -> None:
            pass

        assert "bathos_fn" in _registry("bathos")
        assert "bathos_fn" not in _registry("default")

    def test_default_tool_not_in_named_registry(self):
        """@tool (default) registers in 'default', not in 'bathos'."""
        @tool
        def default_fn() -> None:
            pass

        assert "default_fn" in _registry("default")
        assert "default_fn" not in _registry("bathos")


# ---------------------------------------------------------------------------
# AC-M2-8: registry-scoped selection precursor
# ---------------------------------------------------------------------------

class TestRegistryScopedSelection:
    def test_snapshot_contemplex_contains_only_contemplex_tools(self):
        """_snapshot('contemplex') contains only tools registered to 'contemplex'."""
        @tool(registry="contemplex")
        def contemplex_only() -> None:
            pass

        @tool
        def default_tool() -> None:
            pass

        snap = _snapshot("contemplex")
        assert "contemplex_only" in snap
        assert "default_tool" not in snap

    def test_snapshot_returns_tool_entries_with_correct_registry(self):
        """Entries in _snapshot carry the correct registry name."""
        @tool(registry="contemplex")
        def my_tool() -> int:
            return 42

        snap = _snapshot("contemplex")
        entry = snap["my_tool"]
        assert entry.registry == "contemplex"
        assert entry.fn is my_tool


# ---------------------------------------------------------------------------
# AC-M2-11: snapshot semantics
# ---------------------------------------------------------------------------

class TestSnapshotSemantics:
    def test_tool_decorated_after_snapshot_absent_from_snapshot(self):
        """A tool registered AFTER a snapshot is NOT visible in that snapshot."""
        @tool
        def before_snap() -> None:
            pass

        snap = _snapshot("default")

        # Register a new tool AFTER taking the snapshot.
        @tool
        def after_snap() -> None:
            pass

        # The snapshot should still be frozen at its original state.
        assert "before_snap" in snap
        assert "after_snap" not in snap

    def test_snapshot_is_a_copy_not_live_view(self):
        """Mutating the snapshot dict does not mutate the live registry."""
        @tool
        def original_tool() -> None:
            pass

        snap = _snapshot("default")
        snap.pop("original_tool", None)

        # Live registry is unaffected.
        assert "original_tool" in _registry("default")


# ---------------------------------------------------------------------------
# AC-M2-12: clear_registry() clears "default" only
# ---------------------------------------------------------------------------

class TestClearRegistryDefault:
    def test_clear_default_empties_default_partition(self):
        """clear_registry() with no args empties the 'default' partition."""
        @tool
        def default_tool() -> None:
            pass

        clear_registry()
        assert len(_registry("default")) == 0

    def test_clear_default_leaves_bathos_untouched(self):
        """clear_registry() does not touch 'bathos' partition."""
        @tool(registry="bathos")
        def bathos_tool() -> None:
            pass

        @tool
        def default_tool() -> None:
            pass

        clear_registry()  # clears only "default"
        assert "bathos_tool" in _registry("bathos")

    def test_clear_default_via_name_none(self):
        """clear_registry(name=None) is equivalent to clear_registry()."""
        @tool
        def some_tool() -> None:
            pass

        clear_registry(name=None)
        assert len(_registry("default")) == 0


# ---------------------------------------------------------------------------
# AC-M2-13: clear_registry(name="bathos") clears "bathos" only
# ---------------------------------------------------------------------------

class TestClearRegistryNamed:
    def test_clear_named_empties_named_partition(self):
        """clear_registry(name='bathos') empties the 'bathos' partition."""
        @tool(registry="bathos")
        def bathos_tool() -> None:
            pass

        clear_registry(name="bathos")
        assert len(_registry("bathos")) == 0

    def test_clear_named_leaves_default_untouched(self):
        """clear_registry(name='bathos') does not touch 'default'."""
        @tool
        def default_tool() -> None:
            pass

        @tool(registry="bathos")
        def bathos_tool() -> None:
            pass

        clear_registry(name="bathos")
        assert "default_tool" in _registry("default")

    def test_clear_nonexistent_partition_is_noop(self):
        """clear_registry(name='nonexistent') is a no-op and does not raise."""
        clear_registry(name="nonexistent_xyz_partition")


# ---------------------------------------------------------------------------
# AC-M2-14: direct call passthrough
# ---------------------------------------------------------------------------

class TestDirectCallPassthrough:
    def test_sync_tool_returns_correct_value(self):
        """Calling a @tool-decorated sync fn returns the original return value."""
        @tool
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    @pytest.mark.asyncio
    async def test_async_tool_returns_correct_value(self):
        """Calling a @tool-decorated async fn returns the original return value."""
        @tool
        async def multiply(a: int, b: int) -> int:
            return a * b

        result = await multiply(3, 4)
        assert result == 12

    def test_sync_tool_with_side_effects(self):
        """@tool does not suppress side effects of the original fn."""
        calls: list[Any] = []

        @tool
        def side_effect_fn(value: Any) -> None:
            calls.append(value)

        side_effect_fn("hello")
        assert calls == ["hello"]


# ---------------------------------------------------------------------------
# Misc: ToolEntry dataclass coverage
# ---------------------------------------------------------------------------

class TestToolEntry:
    def test_registry_stores_tool_entry(self):
        """The registry stores ToolEntry objects with correct fields."""
        @tool
        def registered_fn(x: int) -> int:
            return x

        entry = _registry("default")["registered_fn"]
        assert entry.name == "registered_fn"
        assert entry.fn is registered_fn
        assert entry.registry == "default"

    def test_named_registry_stores_correct_entry(self):
        """Named-registry ToolEntry carries the right partition name."""
        @tool(registry="bathos")
        def named_fn() -> None:
            pass

        entry = _registry("bathos")["named_fn"]
        assert entry.name == "named_fn"
        assert entry.fn is named_fn
        assert entry.registry == "bathos"


# ---------------------------------------------------------------------------
# name= override: registered/exposed name can differ from fn.__name__
# ---------------------------------------------------------------------------

class TestNameOverride:
    def test_name_override_stores_under_given_name(self):
        """@tool(name=...) stores the ToolEntry under the override, not fn.__name__."""
        @tool(registry="bathos", name="list_runs")
        def mcp_list_runs_tool(x: int) -> int:
            return x

        assert "list_runs" in _registry("bathos")
        assert "mcp_list_runs_tool" not in _registry("bathos")

        entry = _registry("bathos")["list_runs"]
        assert entry.name == "list_runs"
        assert entry.fn is mcp_list_runs_tool
        assert entry.registry == "bathos"

    def test_no_name_override_defaults_to_fn_name(self):
        """Omitting name= still defaults to fn.__name__ (backward compatible)."""
        @tool(registry="bathos")
        def default_named_fn() -> None:
            pass

        assert "default_named_fn" in _registry("bathos")

    def test_name_override_purity_preserved(self):
        """AC-M2-1 still holds with name=: decorated_fn is fn."""
        @tool(registry="bathos", name="exposed_name")
        def internal_fn(x: int) -> int:
            return x * 2

        assert internal_fn(3) == 6
        assert asyncio.iscoroutinefunction(internal_fn) is False
