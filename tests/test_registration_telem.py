"""Tests for cisterna registration telemetry boundary and F1 dual error contract.

Acceptance criteria covered:

  AC-M2-14 (direct call): a @cisterna.tool-decorated fn called DIRECTLY (no wire)
            returns the original value and emits ZERO telemetry. Verified via
            ShadowExporter spy pipeline.

  AC-M2-6 (boundary):
    (a) WITHOUT CisternaMiddleware installed, invoking the wired MCP callable emits
        ZERO telemetry (the callable itself emits nothing).
    (b) WITH CisternaMiddleware installed (per M1), telemetry originates from
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
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import fastmcp
import pytest
from cyclopts import App

from cisterna.registration.decorator import tool
from cisterna.registration.registry import clear_registry
from cisterna.registration.wired import wire
from cisterna.telemetry import EventPipeline, ShadowExporter


# ---------------------------------------------------------------------------
# Minimal concrete AdapterBase subclass (defined here — do NOT import Bathos/Contemplex)
# ---------------------------------------------------------------------------


@dataclass
class _SpyAdapter:
    """Minimal spy adapter for asserting no adapter methods are called by the callable.

    Tracks all calls to emit_start, emit_end, emit_error, shape_ok, shape_error.
    We do NOT subclass AdapterBase to avoid importing real adapters from other repos.
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
# AC-M2-14: direct call — @cisterna.tool decorated fn called directly emits zero telemetry
# ---------------------------------------------------------------------------


class TestDirectCallZeroTelemetry:
    """AC-M2-14: calling a @cisterna.tool-decorated fn directly returns the
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

        import time
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

        import time
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
            "@cisterna.tool must return the original fn unchanged (C1 decoration purity)"
        )


# ---------------------------------------------------------------------------
# AC-M2-6 (boundary a): WITHOUT middleware — MCP callable emits ZERO telemetry
# ---------------------------------------------------------------------------


class TestWiredMCPCallableNoTelemetry:
    """AC-M2-6 boundary (a): WITHOUT CisternaMiddleware, the wired MCP callable
    itself emits ZERO telemetry when invoked."""

    @pytest.mark.asyncio
    async def test_wired_callable_emits_zero_telem_no_middleware(self, shadow_pipeline):
        """AC-M2-6(a): wired MCP callable on server WITHOUT middleware emits zero telemetry."""
        spy, pipeline = shadow_pipeline

        @tool
        def add_numbers(a: int, b: int) -> int:
            return a + b

        # Wire onto a FastMCP server WITHOUT CisternaMiddleware.
        server = fastmcp.FastMCP("test-no-middleware-telem")
        wire(server)

        # Get the tool's callable from the server and invoke it.
        tools = await server.list_tools()
        assert len(tools) == 1

        # Call via the server's call_tool mechanism (no middleware installed).
        await server.call_tool("add_numbers", {"a": 3, "b": 4})
        # We just need to verify no telemetry was emitted.

        import time
        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"Expected zero telemetry records (no middleware), "
            f"got {len(spy.records)}: {spy.records}"
        )

    @pytest.mark.asyncio
    async def test_wired_callable_spy_adapter_untouched(self, shadow_pipeline):
        """AC-M2-6(a): spy adapter passed to wire() must have zero calls (C5 invariant)."""
        spy, pipeline = shadow_pipeline

        @tool
        def multiply(x: int, y: int) -> int:
            return x * y

        server = fastmcp.FastMCP("test-spy-adapter-untouched")
        adapter = _SpyAdapter()
        wire(server, adapter=adapter)

        # Invoke via the server (no middleware — pure passthrough).
        await server.call_tool("multiply", {"x": 3, "y": 5})

        # The spy adapter must have received ZERO calls.
        assert adapter.calls == [], (
            f"wire() and the wired callable must not invoke any adapter methods (C5); "
            f"got: {adapter.calls}"
        )


# ---------------------------------------------------------------------------
# AC-M2-6 (boundary b): WITH CisternaMiddleware — telemetry comes from MIDDLEWARE
# ---------------------------------------------------------------------------


class TestWiredMCPCallableWithMiddlewareTelemetry:
    """AC-M2-6 boundary (b): WITH CisternaMiddleware installed, telemetry
    originates from MIDDLEWARE (not from the wired callable)."""

    @pytest.mark.asyncio
    async def test_middleware_emits_telemetry_callable_does_not(self):
        """AC-M2-6(b): with CisternaMiddleware, the adapter spy on the callable is untouched;
        telemetry emitted by middleware is attributable to middleware, not the callable."""
        from cisterna.adapters.v3_middleware import CisternaMiddleware

        # Set up a spy pipeline so we can see if telemetry flows.
        spy = ShadowExporter()
        pipeline = EventPipeline(exporters=[spy])

        try:
            # Temporarily install the spy pipeline as the global pipeline.
            import cisterna.telemetry.pipeline as _pipe_mod
            original_pipeline = _pipe_mod._global_pipeline
            _pipe_mod._global_pipeline = pipeline

            @tool
            def greet(name: str) -> str:
                return f"Hello, {name}!"

            server = fastmcp.FastMCP("test-with-middleware")
            server.add_middleware(CisternaMiddleware())
            # adapter=_SpyAdapter() — the callable must NOT call it.
            adapter = _SpyAdapter()
            wire(server, adapter=adapter)

            # Call the tool through the server (middleware is installed).
            await server.call_tool("greet", {"name": "World"})

            import time
            time.sleep(0.1)

            # (1) Spy adapter must remain untouched by the callable (C5).
            assert adapter.calls == [], (
                f"The wired callable must not call adapter methods (C5/AC-M2-6); "
                f"got: {adapter.calls}"
            )

            # (2) The middleware DID emit telemetry (at least one record).
            assert len(spy.records) > 0, (
                "Expected telemetry records from CisternaMiddleware, got none; "
                "middleware is not emitting?"
            )

            # (3) All emitted records should be MCP-related events (mcp.call_start, etc.)
            #     These are attributable to CisternaMiddleware, not to the callable.
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

        # Get the generated MCP callable directly from the internal tool map
        # so we can call it without server-level error handling.
        from cisterna.registration.compose import compose_mcp_callable

        def also_explodes(x: int) -> int:
            raise RuntimeError("boom!")

        mcp_callable = compose_mcp_callable(also_explodes)

        # Awaiting the callable must propagate the exception (not catch it).
        with pytest.raises(RuntimeError, match="boom!"):
            await mcp_callable(x=1)

    @pytest.mark.asyncio
    async def test_mcp_callable_does_not_catch_exceptions_of_any_type(self):
        """F1 (MCP): various exception types propagate through the callable unchanged."""
        from cisterna.registration.compose import compose_mcp_callable

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
        """F1 (CLI): CLI callable that raises writes a concise message to stderr."""
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
            except Exception:
                pass  # Some exception handling — we check stderr output below

        stderr_output = stderr_capture.getvalue()
        assert stderr_output.strip(), (
            "Expected a non-empty message on stderr when CLI callable raises"
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

        import time
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
