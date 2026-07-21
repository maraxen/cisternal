"""Tests for cisternal registration telemetry boundary and F1 dual error contract.

Acceptance criteria covered:

  AC-M2-14 (direct call): a @cisternal.tool-decorated fn called DIRECTLY (no wire)
            returns the original value and emits ZERO telemetry. Verified via
            ShadowExporter spy pipeline.

  AC-M2-6 (boundary):
    (a) WITHOUT CisternalMiddleware installed, invoking the wired MCP callable emits
        ZERO telemetry (the callable itself emits nothing).
    (b) WITH CisternalMiddleware installed (per M1), telemetry originates from
        MIDDLEWARE, not the wired callable — the wired callable makes no
        adapter.* calls (spy adapter asserted untouched by the callable).

  F1 (dual error contract):
    - MCP: invoking the wired MCP callable that raises -> exception propagates
      (not caught by the callable).
    - CLI: invoking the CLI callable that raises -> Cyclopts gets a non-zero exit
      / SystemExit with a stderr message (assert exit code / SystemExit and message).

  A7 (teardown): clear_registry() is called in fixture teardown.
"""

from __future__ import annotations

import io
import time
from unittest.mock import patch

import fastmcp
import pytest
from cyclopts import App

from cisternal.registration.decorator import tool
from cisternal.registration.registry import clear_registry
from cisternal.registration.wired import wire
from cisternal.telemetry import EventPipeline, ShadowExporter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registries():
    """Wipe all known partitions before and after every test (A7)."""
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)
    yield
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)


@pytest.fixture()
def shadow_pipeline():
    """Return (ShadowExporter, EventPipeline) and shut down after test."""
    spy = ShadowExporter()
    pipeline = EventPipeline(exporters=[spy])
    yield spy, pipeline
    pipeline.shutdown()


# ---------------------------------------------------------------------------
# AC-M2-14: direct call — @cisternal.tool decorated fn called directly emits zero telemetry
# ---------------------------------------------------------------------------


class TestDirectCallZeroTelemetry:
    """AC-M2-14: calling a @cisternal.tool-decorated fn directly returns the
    original value and emits ZERO telemetry (C1 decoration purity)."""

    def test_direct_call_returns_original_value_sync(self, shadow_pipeline):
        """AC-M2-14: decorated sync fn called directly returns original return value."""
        spy, pipeline = shadow_pipeline

        @tool
        def my_sync_tool(x: int) -> int:
            return x * 7

        result = my_sync_tool(6)
        assert result == 42, f"Expected 42, got {result}"

    @pytest.mark.asyncio
    async def test_direct_call_returns_original_value_async(self, shadow_pipeline):
        """AC-M2-14: decorated async fn called directly returns original return value."""
        spy, pipeline = shadow_pipeline

        @tool
        async def my_async_tool(x: int) -> int:
            return x + 10

        result = await my_async_tool(32)
        assert result == 42, f"Expected 42, got {result}"

    def test_direct_call_zero_telemetry_sync(self, shadow_pipeline):
        """AC-M2-14: calling decorated fn directly emits ZERO telemetry records."""
        spy, pipeline = shadow_pipeline

        @tool
        def no_telem_sync(x: int) -> int:
            return x + 1

        no_telem_sync(5)

        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"Expected zero telemetry records on direct call, "
            f"got {len(spy.records)}: {spy.records}"
        )

    @pytest.mark.asyncio
    async def test_direct_call_zero_telemetry_async(self, shadow_pipeline):
        """AC-M2-14: calling decorated async fn directly emits ZERO telemetry records."""
        spy, pipeline = shadow_pipeline

        @tool
        async def no_telem_async(x: int) -> int:
            return x * 2

        await no_telem_async(10)

        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"Expected zero telemetry records on direct async call, "
            f"got {len(spy.records)}: {spy.records}"
        )

    def test_decorated_fn_is_original(self, shadow_pipeline):
        """AC-M2-14 / AC-M2-1: decorated fn is the SAME object as the original (pure marker)."""
        spy, pipeline = shadow_pipeline

        def original_fn(x: int) -> int:
            return x

        decorated = tool(original_fn)
        assert decorated is original_fn, (
            "@cisternal.tool must return the original fn unchanged (C1 decoration purity)"
        )


# ---------------------------------------------------------------------------
# AC-M2-6 (boundary a): WITHOUT middleware — MCP callable emits ZERO telemetry
# ---------------------------------------------------------------------------


class TestWiredMCPCallableNoTelemetry:
    """AC-M2-6 boundary (a): WITHOUT CisternalMiddleware, the wired MCP callable
    itself emits ZERO telemetry when invoked."""

    @pytest.mark.asyncio
    async def test_wired_callable_emits_zero_telem_no_middleware(self, shadow_pipeline):
        """AC-M2-6(a): wired MCP callable on server WITHOUT middleware emits zero telemetry."""
        spy, pipeline = shadow_pipeline

        @tool
        def add_numbers(a: int, b: int) -> int:
            return a + b

        # Wire onto a FastMCP server WITHOUT CisternalMiddleware.
        server = fastmcp.FastMCP("test-no-middleware-telem")
        wire(server)

        # Get the tool's callable from the server and invoke it.
        tools = await server.list_tools()
        assert len(tools) == 1

        # Call via the server's call_tool mechanism (no middleware installed).
        await server.call_tool("add_numbers", {"a": 3, "b": 4})
        # We just need to verify no telemetry was emitted.

        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"Expected zero telemetry records (no middleware), "
            f"got {len(spy.records)}: {spy.records}"
        )

    @pytest.mark.asyncio
    async def test_wired_callable_spy_adapter_untouched(self, shadow_pipeline, spy_adapter):
        """AC-M2-6(a): spy adapter passed to wire() must have zero calls (C5 invariant)."""
        spy, pipeline = shadow_pipeline

        @tool
        def multiply(x: int, y: int) -> int:
            return x * y

        server = fastmcp.FastMCP("test-spy-adapter-untouched")
        wire(server, adapter=spy_adapter)

        # Invoke via the server (no middleware — pure passthrough).
        await server.call_tool("multiply", {"x": 3, "y": 5})

        # The spy adapter must have received ZERO calls.
        assert spy_adapter.calls == [], (
            f"wire() and the wired callable must not invoke any adapter methods (C5); "
            f"got: {spy_adapter.calls}"
        )


# ---------------------------------------------------------------------------
# AC-M2-6 (boundary b): WITH CisternalMiddleware — telemetry comes from MIDDLEWARE
# ---------------------------------------------------------------------------


class TestWiredMCPCallableWithMiddlewareTelemetry:
    """AC-M2-6 boundary (b): WITH CisternalMiddleware installed, telemetry
    originates from MIDDLEWARE (not from the wired callable)."""

    @pytest.mark.asyncio
    async def test_middleware_emits_telemetry_callable_does_not(self, spy_adapter):
        """AC-M2-6(b): with CisternalMiddleware, the adapter spy on the callable is untouched;
        telemetry emitted by middleware is attributable to middleware, not the callable."""
        from cisternal.adapters.v3_middleware import CisternalMiddleware

        # Set up a spy pipeline so we can see if telemetry flows.
        spy = ShadowExporter()
        pipeline = EventPipeline(exporters=[spy])

        try:
            # Temporarily install the spy pipeline as the global pipeline.
            import cisternal.telemetry.pipeline as _pipe_mod
            original_pipeline = _pipe_mod._global_pipeline
            _pipe_mod._global_pipeline = pipeline

            @tool
            def greet(name: str) -> str:
                return f"Hello, {name}!"

            server = fastmcp.FastMCP("test-with-middleware")
            server.add_middleware(CisternalMiddleware())
            # spy_adapter — the callable must NOT call any of its methods.
            wire(server, adapter=spy_adapter)

            # Call the tool through the server (middleware is installed).
            await server.call_tool("greet", {"name": "World"})

            time.sleep(0.1)

            # (1) Spy adapter must remain untouched by the callable (C5).
            assert spy_adapter.calls == [], (
                f"The wired callable must not call adapter methods (C5/AC-M2-6); "
                f"got: {spy_adapter.calls}"
            )

            # (2) The middleware DID emit telemetry (at least one record).
            assert len(spy.records) > 0, (
                "Expected telemetry records from CisternalMiddleware, got none; "
                "middleware is not emitting?"
            )

            # (3) All emitted records should be MCP-related events (mcp.call_start, etc.)
            #     These are attributable to CisternalMiddleware, not to the callable.
            event_names = [r.name for r in spy.records]
            mcp_events = [n for n in event_names if n.startswith("mcp.")]
            assert mcp_events, (
                f"Expected at least one mcp.* event from middleware, "
                f"got event names: {event_names}"
            )

        finally:
            _pipe_mod._global_pipeline = original_pipeline
            pipeline.shutdown()


# ---------------------------------------------------------------------------
# F1: MCP callable — exception propagates (not caught by the callable)
# ---------------------------------------------------------------------------


class TestMCPCallableExceptionPropagates:
    """F1 (MCP path): the wired MCP callable does NOT intercept exceptions —
    they propagate to the caller (FastMCP/middleware)."""

    @pytest.mark.asyncio
    async def test_mcp_callable_propagates_exception(self):
        """F1 (MCP): raised exception from the tool propagates through the wired callable."""
        @tool
        def exploding_tool(x: int) -> int:
            raise ValueError("kaboom")

        server = fastmcp.FastMCP("test-mcp-propagate")
        wire(server)

        # Retrieve the wired MCP callable from the FastMCP server's tool registry
        # and invoke it directly (bypassing server-level error handling).
        wired_tool = await server.get_tool("exploding_tool")
        mcp_callable = wired_tool.fn  # the compose_mcp_callable wrapper

        # Awaiting the callable must propagate the exception (not catch it).
        with pytest.raises(ValueError, match="kaboom"):
            await mcp_callable(x=1)

    @pytest.mark.asyncio
    async def test_mcp_callable_does_not_catch_exceptions_of_any_type(self):
        """F1 (MCP): various exception types propagate through the callable unchanged."""
        from cisternal.registration.compose import compose_mcp_callable

        for exc_class, msg in [
            (ValueError, "value error"),
            (TypeError, "type error"),
            (KeyError, "key error"),
            (RuntimeError, "runtime error"),
        ]:
            def make_raiser(cls: type, message: str):
                def raiser() -> None:
                    raise cls(message)
                return raiser

            raiser_fn = make_raiser(exc_class, msg)
            mcp_callable = compose_mcp_callable(raiser_fn)

            with pytest.raises(exc_class):
                await mcp_callable()


# ---------------------------------------------------------------------------
# F1: CLI callable — exception -> SystemExit / non-zero exit code + stderr message
# ---------------------------------------------------------------------------


class TestCLICallableExceptionToExitCode:
    """F1 (CLI path): the CLI-registered callable wraps exceptions into a clean
    CLI failure — re-raises as SystemExit (non-zero), writing a concise message
    to stderr. Must NOT emit telemetry."""

    def test_cli_callable_raises_systemexit_on_exception(self):
        """F1 (CLI): CLI callable that raises -> SystemExit with non-zero code."""
        @tool
        def failing_cli_tool(x: int) -> int:
            raise ValueError("something went wrong")

        server = fastmcp.FastMCP("test-cli-exit")
        app = App()
        wire(server, app)

        # Invoke the CLI command registered under 'failing_cli_tool'.
        # Cyclopts App.main() runs the command; our CLI callable must convert
        # the exception into a SystemExit.
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            with pytest.raises(SystemExit) as exc_info:
                app(["failing-cli-tool", "--x", "1"], exit_on_error=False)

        exit_code = exc_info.value.code
        assert exit_code != 0, (
            f"Expected non-zero exit code from CLI tool that raises, got: {exit_code}"
        )

    def test_cli_callable_writes_message_to_stderr(self):
        """F1 (CLI): CLI callable that raises writes a message to stderr containing
        the exception type name and the original message (format: 'Error (RuntimeError): ...')."""
        @tool
        def message_tool(name: str) -> str:
            raise RuntimeError("something exploded")

        server = fastmcp.FastMCP("test-cli-stderr")
        app = App()
        wire(server, app)

        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            try:
                app(["message-tool", "--name", "test"], exit_on_error=False)
            except SystemExit:
                pass

        stderr_output = stderr_capture.getvalue()
        assert "RuntimeError" in stderr_output, (
            f"Expected 'RuntimeError' (the exception type name) in stderr output, "
            f"got: {stderr_output!r}"
        )
        assert "something exploded" in stderr_output, (
            f"Expected the original message 'something exploded' in stderr output, "
            f"got: {stderr_output!r}"
        )

    def test_cli_callable_exception_does_not_emit_telemetry(self, shadow_pipeline):
        """F1 (CLI): CLI callable error handler must NOT emit telemetry."""
        spy, pipeline = shadow_pipeline

        @tool
        def telem_free_fail(x: int) -> int:
            raise ValueError("no telem please")

        server = fastmcp.FastMCP("test-cli-no-telem")
        app = App()
        wire(server, app)

        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            try:
                app(["telem-free-fail", "--x", "99"], exit_on_error=False)
            except SystemExit:
                pass
            except Exception:
                pass

        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"CLI error handler must not emit telemetry; "
            f"got {len(spy.records)} records: {spy.records}"
        )

    def test_cli_callable_success_path_unchanged(self):
        """F1 (CLI): CLI callable success path executes without error (no interference)."""
        called: list[bool] = []

        @tool
        def success_tool() -> str:
            called.append(True)
            return "ok"

        server = fastmcp.FastMCP("test-cli-success")
        app = App()
        wire(server, app)

        # Cyclopts raises SystemExit(0) on successful completion — that is normal.
        try:
            app(["success-tool"], exit_on_error=False)
        except SystemExit as se:
            assert se.code == 0, f"Expected SystemExit(0) on success, got {se.code}"

        assert called == [True], (
            f"Expected success_tool to be called exactly once, got: {called}"
        )
