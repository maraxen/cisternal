"""Tests for cisternal.registration — wire() + WiredRegistry (M2-WIRE, item 2143).

Acceptance criteria covered:
  AC-M2-8   — wire(server, registry="contemplex") registers ONLY contemplex tools
               (not tools from other partitions such as "default").
  AC-M2-9   — wire(server, expected=["tool_a", "tool_b"]) with only "tool_b"
               registered raises CisternalWireError; err.missing == ["tool_a"].
  AC-M2-10  — same setup with validate=False -> NO raise; WARNING is logged to
               "cisternal.registration" (verified via caplog).
  AC-M2-11  — post-wire decoration excluded from snapshot: tool decorated AFTER
               wire() is NOT on the wired server (tool list unchanged).
  AC-M2-12  — after wire(), clear_registry() empties the metadata partition.
  AC-M2-13  — after clear_registry(), the already-wired server RETAINS its tools.
  AC-M2-6/C5 — adapter methods never called: wire() with a spy adapter must not
               invoke any adapter emit_*/shape_* methods.
"""

from __future__ import annotations

import inspect
import logging

import fastmcp
import pytest
from cyclopts import App

from cisternal.registration.decorator import tool
from cisternal.registration.errors import CisternalWireError
from cisternal.registration.registry import clear_registry
from cisternal.registration.wired import WiredRegistry, wire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _tool_names(server: fastmcp.FastMCP) -> list[str]:
    """Return the list of tool names registered on *server*."""
    tools = await server.list_tools()
    return [t.name for t in tools]


# ---------------------------------------------------------------------------
# Fixture: registry cleanup (A7)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registries():
    """Wipe all known partitions before and after every test (A7)."""
    for partition in ("default", "contemplex", "bathos"):
        clear_registry(name=partition)
    yield
    for partition in ("default", "contemplex", "bathos"):
        clear_registry(name=partition)


# ---------------------------------------------------------------------------
# AC-M2-8: named partition isolation
# ---------------------------------------------------------------------------

class TestNamedPartitionIsolation:
    """wire(server, registry="contemplex") registers ONLY contemplex tools."""

    @pytest.mark.asyncio
    async def test_only_contemplex_tools_wired(self):
        """AC-M2-8: contemplex partition — only its tools appear on the server."""

        @tool(registry="contemplex")
        def contemplex_tool_alpha(x: int) -> int:
            return x

        @tool(registry="default")
        def default_tool_beta(y: str) -> str:
            return y

        server = fastmcp.FastMCP("test-partition-isolation")
        wire(server, registry="contemplex")

        names = await _tool_names(server)
        assert "contemplex_tool_alpha" in names, (
            f"Expected contemplex_tool_alpha on server, got: {names}"
        )
        assert "default_tool_beta" not in names, (
            f"default_tool_beta should NOT be on the contemplex-wired server, got: {names}"
        )

    @pytest.mark.asyncio
    async def test_wired_registry_reflects_partition(self):
        """AC-M2-8: WiredRegistry.registry_name matches the requested partition."""

        @tool(registry="contemplex")
        def my_contemplex_tool(z: float) -> float:
            return z * 2

        server = fastmcp.FastMCP("test-wired-registry-name")
        result = wire(server, registry="contemplex")

        assert result.registry_name == "contemplex"
        assert "my_contemplex_tool" in result.mcp_tools

    @pytest.mark.asyncio
    async def test_default_partition_unaffected(self):
        """AC-M2-8: wiring contemplex leaves default partition tools unregistered."""

        @tool
        def default_only(a: int) -> int:
            return a

        @tool(registry="contemplex")
        def contemplex_only(b: int) -> int:
            return b

        server = fastmcp.FastMCP("test-default-unaffected")
        wire(server, registry="contemplex")

        names = await _tool_names(server)
        assert "default_only" not in names
        assert "contemplex_only" in names


# ---------------------------------------------------------------------------
# AC-M2-9: CisternalWireError on missing expected tools (validate=True)
# ---------------------------------------------------------------------------

class TestExpectedValidationRaises:
    """wire(server, expected=[...], validate=True) raises on missing tools."""

    def test_missing_expected_tool_raises(self):
        """AC-M2-9: only tool_b decorated — missing tool_a raises CisternalWireError."""

        @tool
        def tool_b(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-expected-raises")
        with pytest.raises(CisternalWireError) as exc_info:
            wire(server, expected=["tool_a", "tool_b"])

        err = exc_info.value
        assert "tool_a" in err.missing, (
            f"Expected 'tool_a' in err.missing, got: {err.missing}"
        )
        assert "tool_b" not in err.missing, (
            f"'tool_b' is registered and should not be in err.missing: {err.missing}"
        )

    def test_missing_list_exact(self):
        """AC-M2-9: err.missing contains exactly the absent names."""

        server = fastmcp.FastMCP("test-missing-exact")
        with pytest.raises(CisternalWireError) as exc_info:
            wire(server, expected=["tool_x", "tool_y", "tool_z"])

        err = exc_info.value
        assert set(err.missing) == {"tool_x", "tool_y", "tool_z"}

    def test_no_error_when_all_expected_present(self):
        """AC-M2-9: no error when all expected tools are registered."""

        @tool
        def tool_a(x: int) -> int:
            return x

        @tool
        def tool_b(y: str) -> str:
            return y

        server = fastmcp.FastMCP("test-no-error-expected")
        # Must not raise
        result = wire(server, expected=["tool_a", "tool_b"])
        assert isinstance(result, WiredRegistry)


# ---------------------------------------------------------------------------
# AC-M2-10: warning logged, no raise, when validate=False
# ---------------------------------------------------------------------------

class TestExpectedValidationWarns:
    """wire(server, expected=[...], validate=False) warns but does not raise."""

    def test_validate_false_no_raise(self, caplog):
        """AC-M2-10: missing tools with validate=False do not raise."""

        @tool
        def tool_b(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-validate-false-no-raise")
        with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
            result = wire(server, expected=["tool_a", "tool_b"], validate=False)

        # No exception — must return WiredRegistry
        assert isinstance(result, WiredRegistry)

    def test_validate_false_warning_logged(self, caplog):
        """AC-M2-10: a WARNING is logged to 'cisternal.registration'."""

        @tool
        def tool_b(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-validate-false-warning")
        with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
            wire(server, expected=["tool_a", "tool_b"], validate=False)

        warning_records = [
            r for r in caplog.records
            if r.name == "cisternal.registration" and r.levelno == logging.WARNING
        ]
        assert warning_records, (
            "Expected a WARNING record from 'cisternal.registration', "
            f"got records: {caplog.records}"
        )
        # The warning message should mention the missing tool name
        combined = " ".join(r.getMessage() for r in warning_records)
        assert "tool_a" in combined, (
            f"WARNING should mention 'tool_a', got: {combined!r}"
        )

    def test_validate_false_registered_tools_still_wired(self, caplog):
        """AC-M2-10: the tools that ARE registered still get wired even if others are missing."""

        @tool
        def tool_b(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-validate-false-partial-wire")
        with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
            result = wire(server, expected=["tool_a", "tool_b"], validate=False)

        assert "tool_b" in result.mcp_tools


# ---------------------------------------------------------------------------
# AC-M2-11: snapshot semantics — post-wire decoration excluded
# ---------------------------------------------------------------------------

class TestSnapshotSemantics:
    """Tools decorated AFTER wire() are NOT on the wired server."""

    @pytest.mark.asyncio
    async def test_post_wire_tool_excluded(self):
        """AC-M2-11: decorating a NEW tool after wire() does NOT affect the server."""

        @tool
        def pre_wire_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-snapshot")
        wire(server)

        # Decorate a new tool AFTER wire()
        @tool
        def post_wire_tool(y: int) -> int:
            return y

        names_after = await _tool_names(server)
        assert "pre_wire_tool" in names_after, (
            f"pre_wire_tool should be on the server: {names_after}"
        )
        assert "post_wire_tool" not in names_after, (
            f"post_wire_tool decorated AFTER wire() should NOT be on server: {names_after}"
        )

    @pytest.mark.asyncio
    async def test_server_tool_count_frozen_at_wire_time(self):
        """AC-M2-11: the server's tool count doesn't change when new tools are decorated."""

        @tool
        def alpha(a: int) -> int:
            return a

        @tool
        def beta(b: int) -> int:
            return b

        server = fastmcp.FastMCP("test-count-frozen")
        wire(server)

        count_at_wire = len(await _tool_names(server))

        # Add more tools after wiring
        @tool
        def gamma(c: int) -> int:
            return c

        @tool
        def delta(d: int) -> int:
            return d

        count_after = len(await _tool_names(server))
        assert count_after == count_at_wire, (
            f"Server tool count should remain {count_at_wire} after post-wire "
            f"decorations, but got {count_after}"
        )


# ---------------------------------------------------------------------------
# AC-M2-12 / AC-M2-13: clear_registry after wire
# ---------------------------------------------------------------------------

class TestClearRegistryAfterWire:
    """clear_registry() empties the metadata partition; wired server is unaffected."""

    @pytest.mark.asyncio
    async def test_clear_registry_empties_partition(self):
        """AC-M2-12: clear_registry() empties the metadata partition."""
        from cisternal.registration.registry import _snapshot

        @tool
        def my_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-clear-empty")
        wire(server)

        # Verify tool is in registry before clearing
        before = _snapshot("default")
        assert "my_tool" in before

        clear_registry(name="default")

        # After clear, snapshot is empty
        after = _snapshot("default")
        assert len(after) == 0, (
            f"Registry should be empty after clear_registry(), got: {after}"
        )

    @pytest.mark.asyncio
    async def test_wired_server_retains_tools_after_clear(self):
        """AC-M2-13: already-wired server retains its tools even after clear_registry()."""

        @tool
        def my_retained_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-retain-after-clear")
        wire(server)

        # Sanity: tool is on server before clearing
        names_before = await _tool_names(server)
        assert "my_retained_tool" in names_before

        clear_registry(name="default")

        # Server must still have the tool
        names_after = await _tool_names(server)
        assert "my_retained_tool" in names_after, (
            f"Wired server should retain tools after clear_registry(); "
            f"got: {names_after}"
        )

    @pytest.mark.asyncio
    async def test_clear_does_not_affect_other_partitions(self):
        """AC-M2-12: clearing 'default' does not touch 'contemplex' partition."""
        from cisternal.registration.registry import _snapshot

        @tool
        def default_tool(x: int) -> int:
            return x

        @tool(registry="contemplex")
        def contemplex_tool(y: int) -> int:
            return y

        server = fastmcp.FastMCP("test-clear-isolation")
        wire(server)

        clear_registry(name="default")

        contemplex_snap = _snapshot("contemplex")
        assert "contemplex_tool" in contemplex_snap, (
            f"clear_registry('default') should not affect 'contemplex' partition: "
            f"{contemplex_snap}"
        )


# ---------------------------------------------------------------------------
# WiredRegistry structure tests
# ---------------------------------------------------------------------------

class TestWiredRegistryStructure:
    """WiredRegistry is a dataclass with expected fields."""

    @pytest.mark.asyncio
    async def test_wired_registry_has_required_fields(self):
        """WiredRegistry exposes registry_name, mcp_tools, cli_commands."""

        @tool
        def some_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-wr-fields")
        result = wire(server)

        assert hasattr(result, "registry_name")
        assert hasattr(result, "mcp_tools")
        assert hasattr(result, "cli_commands")
        assert result.registry_name == "default"
        assert "some_tool" in result.mcp_tools

    @pytest.mark.asyncio
    async def test_cli_commands_empty_without_app(self):
        """WiredRegistry.cli_commands is empty when no app is given."""

        @tool
        def another_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-wr-no-app")
        result = wire(server)

        assert result.cli_commands == []

    @pytest.mark.asyncio
    async def test_cli_commands_populated_with_app(self):
        """WiredRegistry.cli_commands is populated when an App is given (TBD-M2-1: dual-transport)."""

        @tool
        def cli_registered_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-wr-with-app")
        app = App()
        result = wire(server, app)

        # TBD-M2-1: a single wire(server, app) call must populate BOTH transports.
        assert "cli_registered_tool" in result.cli_commands
        assert "cli_registered_tool" in result.mcp_tools
        names = await _tool_names(server)
        assert "cli_registered_tool" in names, (
            f"Expected cli_registered_tool on FastMCP server (dual-transport), got: {names}"
        )


# ---------------------------------------------------------------------------
# Adapter invariant — C5 / AC-M2-6
# ---------------------------------------------------------------------------

class TestAdapterNotCalled:
    """Passing an adapter to wire() must not invoke any adapter methods (C5/AC-M2-6)."""

    @pytest.mark.asyncio
    async def test_adapter_methods_never_called(self, spy_adapter):
        """AC-M2-6/C5: wire() with a spy adapter must call zero adapter methods."""

        @tool
        def spy_target(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-adapter-not-called")
        wire(server, adapter=spy_adapter)

        assert spy_adapter.calls == [], (
            f"wire() must not call any adapter methods (C5/AC-M2-6); "
            f"got calls: {spy_adapter.calls}"
        )


# ---------------------------------------------------------------------------
# Module-level helpers for TestCLISignatureInjection
# (defined at module scope so __globals__ includes Annotated/Field for pydantic)
# ---------------------------------------------------------------------------


def _greet_cli_original(name: str, times: int = 3) -> str:
    """Module-level original function for CLI signature injection test.

    Defined at module scope so Cyclopts' get_type_hints() can resolve
    annotations from this module's globals.  The 'times' param has a default
    value, satisfying the 'defaulted param' requirement.
    """
    return (name + " ") * times


# ---------------------------------------------------------------------------
# F1: CLI callable signature injection (mirrors AC-M2-4 for MCP)
# ---------------------------------------------------------------------------


class TestCLISignatureInjection:
    """F1: CLI callable registered by wire() must carry inspect.signature ==
    the original function's signature (mirrors H1/AC-M2-4 for the MCP callable).

    Cyclopts uses inspect.signature() to build arg parsers; explicit injection
    prevents reliance on __wrapped__ traversal which is not guaranteed across
    Cyclopts versions.
    """

    def test_cli_callable_signature_matches_original(self):
        """F1: CLI callable has inspect.signature() equal to the original fn's signature,
        including a defaulted param.

        Mirrors AC-M2-4: the explicit __signature__ injection on the CLI callable
        mirrors H1 on the MCP callable so Cyclopts can build arg parsers without
        relying on __wrapped__ traversal.

        _greet_cli_original is defined at module scope so Cyclopts' get_type_hints()
        can resolve its annotations from this module's globals.
        """
        # Register the module-level original function as a tool.
        tool(_greet_cli_original)

        server = fastmcp.FastMCP("test-cli-sig")
        app = App()
        wire(server, app)

        # Cyclopts stores the registered callable on the sub-App's default_command.
        # wire() registers with name=entry.name (the Python function name, underscored).
        registered_fn = app["_greet_cli_original"].default_command  # type: ignore[attr-defined]

        original_sig = inspect.signature(_greet_cli_original)
        cli_sig = inspect.signature(registered_fn)

        assert cli_sig == original_sig, (
            f"CLI callable signature mismatch.\n"
            f"  original:  {original_sig}\n"
            f"  cli:       {cli_sig}"
        )
        # Verify params are preserved: 'name' (required) and 'times' (defaulted).
        params = cli_sig.parameters
        assert "name" in params
        assert "times" in params
        # 'times' has a default of 3 — verify it round-trips through the injection.
        assert params["times"].default == 3
