"""Tests for MCP adapter layer: AC-MCP-1..4 acceptance criteria (spec §8).

AC-MCP-1: CisternalMiddleware on v3 server emits mcp.call_start/end with correct fields.
AC-MCP-2: traced_tool(ContemplexAdapter) on sync tool emits start/end and shapes result.
AC-MCP-3: v3 tool raises RuntimeError → mcp.tool_error emitted, error envelope returned.
AC-MCP-3b: v2 sync tool raises ValueError → mcp.tool_error emitted, no exception escapes.
AC-MCP-4: Token reset in different Context raises ValueError, wrapper swallows it.

AC-MCP-5 (bugfix, cisternal/mcp-middleware-fix, 260728): CisternalMiddleware
against a REAL fastmcp.FastMCP server (not Mock()) -- the test that would
have caught the ToolResult-shape bug (BathosAdapter's isinstance(result, dict)
check silently discarded every real tool result; a plain-dict shape_error had
no .to_mcp_result(), crashing on every tool error).
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import fastmcp
import pytest

from cisternal import init
from cisternal.adapters.base import (
    AdapterBase,
    BathosAdapter,
    ContemplexAdapter,
    PassthroughAdapter,
    XpeririAdapter,
    MyxcelAdapter,
)
from cisternal.adapters.v2_decorator import traced_tool
from cisternal.adapters.v3_middleware import CisternalMiddleware
from cisternal.registration.decorator import tool as cisternal_tool
from cisternal.registration.registry import clear_registry
from cisternal.registration.wired import wire
from cisternal.telemetry.exporter import ShadowExporter


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for JSONL logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up pipeline between tests."""
    yield
    from cisternal.telemetry import pipeline as pipeline_module
    from cisternal.telemetry import self_obs as self_obs_module

    if pipeline_module._global_pipeline is not None:
        pipeline_module._global_pipeline.shutdown()
        pipeline_module._global_pipeline = None

    with self_obs_module._heartbeat_lock:
        self_obs_module._heartbeat_thread = None
        self_obs_module._last_stat = {
            "mtime": None,
            "size": None,
            "ts": None,
            "last_growth_ts": None,
        }
        self_obs_module._jsonl_path = None


class TestAcMcp1CisternalMiddleware:
    """AC-MCP-1: CisternalMiddleware emits mcp.call_start+mcp.call_end."""

    @pytest.mark.asyncio
    async def test_v3_middleware_emits_start_and_end(self, temp_log_dir):
        """Given CisternalMiddleware on a v3 server;
        When a tool is called with arguments;
        Then mcp.call_start + mcp.call_end appear with correct tool name and arg_keys."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        # Create a mock MiddlewareContext with a tool call
        context = Mock()
        context.message = Mock()
        context.message.name = "test_tool"
        context.message.arguments = {"a": 1, "b": 2}

        # Mock call_next to return a result immediately
        async def mock_call_next(ctx):
            return "ok"

        middleware = CisternalMiddleware()
        result = await middleware.on_call_tool(context, mock_call_next)

        # Allow time for events to be exported
        time.sleep(0.1)

        # Verify result is shaped
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("ok") is True

        # Verify telemetry was emitted
        start_records = [r for r in shadow.records if r.name == "mcp.call_start"]
        end_records = [r for r in shadow.records if r.name == "mcp.call_end"]

        assert len(start_records) == 1, (
            f"Expected 1 start record, got {len(start_records)}"
        )
        assert len(end_records) == 1, f"Expected 1 end record, got {len(end_records)}"

        # Verify start event fields
        start = start_records[0]
        assert start.fields["tool"] == "test_tool"
        assert start.fields["arg_keys"] == ["a", "b"]  # sorted
        assert "request_id" in start.fields

        # Verify end event fields
        end = end_records[0]
        assert end.fields["tool"] == "test_tool"
        assert "duration_ms" in end.fields
        assert end.fields["request_id"] == start.fields["request_id"]

    @pytest.mark.asyncio
    async def test_v3_middleware_shapes_result_bathos(self, temp_log_dir):
        """Verify BathosAdapter shapes result as dict envelope."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        context = Mock()
        context.message = Mock()
        context.message.name = "test_tool"
        context.message.arguments = {}

        # Return a dict result
        async def mock_call_next(ctx):
            return {"status": "success", "data": 42}

        middleware = CisternalMiddleware()
        result = await middleware.on_call_tool(context, mock_call_next)

        # BathosAdapter should merge the result with envelope fields
        assert result is not None
        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert result["data"] == 42
        assert result["ok"] is True
        assert result["error_code"] is None
        assert result["error"] is None


class TestAcMcp2TracedToolDecorator:
    """AC-MCP-2: traced_tool(ContemplexAdapter) emits start+end on sync tool."""

    def test_traced_tool_emits_start_and_end(self, temp_log_dir):
        """Given traced_tool(ContemplexAdapter()) wrapping a sync fn;
        When called with kwargs;
        Then mcp.call_start + mcp.call_end appear with arg_keys = kwargs keys."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @traced_tool(ContemplexAdapter())
        def my_tool(arg1: str, arg2: int) -> str:
            return f"result: {arg1}, {arg2}"

        result = my_tool(arg1="hello", arg2=42)

        # Allow time for events to be exported
        time.sleep(0.1)

        assert result == "result: hello, 42"

        # Verify telemetry
        start_records = [r for r in shadow.records if r.name == "mcp.call_start"]
        end_records = [r for r in shadow.records if r.name == "mcp.call_end"]

        assert len(start_records) == 1
        assert len(end_records) == 1

        start = start_records[0]
        assert start.fields["tool"] == "my_tool"
        assert start.fields["arg_keys"] == ["arg1", "arg2"]

        end = end_records[0]
        assert end.fields["tool"] == "my_tool"
        assert "duration_ms" in end.fields

    def test_traced_tool_shapes_result_contemplex(self, temp_log_dir):
        """Verify ContemplexAdapter returns result unchanged (passthrough)."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @traced_tool(ContemplexAdapter())
        def my_tool() -> dict:
            return {"status": "ok"}

        result = my_tool()

        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_traced_tool_async_emits_start_and_end(self, temp_log_dir):
        """Given traced_tool(MyxcelAdapter()) wrapping an async fn;
        When awaited with kwargs;
        Then mcp.call_start + mcp.call_end appear with arg_keys = kwargs keys."""

        import asyncio

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @traced_tool(MyxcelAdapter())
        async def mount_project(remote: str, project: str) -> dict:
            await asyncio.sleep(0)
            return {"remote": remote, "project": project, "mounted": True}

        result = await mount_project(remote="hpc", project="demo")

        time.sleep(0.1)

        assert result == {"remote": "hpc", "project": "demo", "mounted": True}

        start_records = [r for r in shadow.records if r.name == "mcp.call_start"]
        end_records = [r for r in shadow.records if r.name == "mcp.call_end"]

        assert len(start_records) == 1
        assert len(end_records) == 1

        start = start_records[0]
        assert start.fields["tool"] == "mount_project"
        assert start.fields["arg_keys"] == ["project", "remote"]

        end = end_records[0]
        assert end.fields["tool"] == "mount_project"
        assert "duration_ms" in end.fields

    @pytest.mark.asyncio
    async def test_traced_tool_async_preserves_coroutine_function(self):
        """Async wrapper remains a coroutine function for FastMCP await detection."""

        import asyncio

        @traced_tool(MyxcelAdapter())
        async def mount_status(remote: str | None = None) -> list[dict]:
            await asyncio.sleep(0)
            return [{"remote": remote or "all"}]

        assert asyncio.iscoroutinefunction(mount_status)


class TestAcMcp3ErrorHandling:
    """AC-MCP-3, AC-MCP-3b: Error handling in v3 and v2."""

    @pytest.mark.asyncio
    async def test_v3_middleware_catches_exception(self, temp_log_dir):
        """AC-MCP-3: Given a v3 tool raises RuntimeError;
        Then mcp.tool_error emitted AND shaped error envelope returned (ok=False),
        not re-raised."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        context = Mock()
        context.message = Mock()
        context.message.name = "failing_tool"
        context.message.arguments = {}

        async def mock_call_next_error(ctx):
            raise RuntimeError("boom")

        middleware = CisternalMiddleware()
        result = await middleware.on_call_tool(context, mock_call_next_error)

        # Allow time for events
        time.sleep(0.1)

        # Result should be error envelope, not exception
        assert result is not None
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert result["error_code"] == "INTERNAL"
        assert "boom" in result["error"]

        # Verify error event was emitted
        error_records = [r for r in shadow.records if r.name == "mcp.tool_error"]
        assert len(error_records) == 1

        error = error_records[0]
        assert error.fields["exc_type"] == "RuntimeError"
        assert "boom" in error.fields["exc_msg"]

    def test_v2_decorator_catches_exception(self, temp_log_dir):
        """AC-MCP-3b: Given traced_tool wrapping fn that raises ValueError;
        Then mcp.tool_error emitted AND error envelope returned; no exception propagates."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @traced_tool(ContemplexAdapter())
        def failing_tool():
            raise ValueError("something went wrong")

        # Call should not raise; should return shaped error
        result = failing_tool()

        time.sleep(0.1)

        # Result should be error envelope
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert "something went wrong" in result.get("error", "")

        # Verify error was emitted
        error_records = [r for r in shadow.records if r.name == "mcp.tool_error"]
        assert len(error_records) == 1

        error = error_records[0]
        assert error.fields["exc_type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_v2_decorator_async_catches_exception(self, temp_log_dir):
        """AC-MCP-3b async: traced_tool on async fn returns shaped error, no raise."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @traced_tool(MyxcelAdapter())
        async def failing_mount():
            raise ValueError("profile missing")

        result = await failing_mount()

        time.sleep(0.1)

        assert result == {"error": "ValueError", "message": "profile missing"}

        error_records = [r for r in shadow.records if r.name == "mcp.tool_error"]
        assert len(error_records) == 1
        assert error_records[0].fields["exc_type"] == "ValueError"


class TestAcMcp4TokenManagement:
    """AC-MCP-4: Token reset in different Context raises ValueError, wrapper swallows it.

    Note: AC-MCP-4 tests the error-handling path. The ValueError from reset()
    is caught in the finally block of both CisternalMiddleware.on_call_tool and
    traced_tool wrapper. This test verifies the wrapper doesn't crash when
    exceptions occur during token management.
    """

    @pytest.mark.asyncio
    async def test_v3_middleware_handles_token_safely(self, temp_log_dir):
        """Verify v3 middleware doesn't crash on token operations."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        context = Mock()
        context.message = Mock()
        context.message.name = "test_tool"
        context.message.arguments = {"arg": "value"}

        async def mock_call_next(ctx):
            return "ok"

        middleware = CisternalMiddleware()
        # Should not raise; token set/reset should complete safely
        result = await middleware.on_call_tool(context, mock_call_next)
        assert result is not None
        assert result.get("ok") is True

    def test_v2_decorator_handles_token_safely(self, temp_log_dir):
        """Verify v2 decorator doesn't crash on token operations."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @traced_tool(BathosAdapter())
        def test_tool(arg="value"):
            return "ok"

        # Should not raise; token set/reset should complete safely
        result = test_tool()
        assert result is not None
        assert result.get("ok") is True

    def test_token_reset_error_handling_code_path(self):
        """Verify that the ValueError handling in finally block is in place."""
        import inspect
        from cisternal.adapters import v3_middleware, v2_decorator

        v3_source = inspect.getsource(v3_middleware.CisternalMiddleware.on_call_tool)
        assert "finally:" in v3_source
        assert "mcp_request_id_var.reset" in v3_source
        assert "except ValueError:" in v3_source

        v2_source = inspect.getsource(v2_decorator.traced_tool)
        assert "finally:" in v2_source
        assert "_reset_request_token" in v2_source

        reset_source = inspect.getsource(v2_decorator._reset_request_token)
        assert "mcp_request_id_var.reset" in reset_source
        assert "except ValueError:" in reset_source

    def test_cross_context_reset_actually_raises_value_error(self):
        """Demonstrate that copy_context().run() triggers real ValueError from reset().

        This is the actual CH-10 scenario: a Token created in context A cannot be
        reset inside a different Context B (created via copy_context()). The
        middleware's `except ValueError: pass` guards against this pattern.
        """
        import contextvars
        from cisternal.telemetry.context import mcp_request_id_var

        # Set a token in the current (outer) context
        outer_tok = mcp_request_id_var.set("outer_request")

        # Copy the current context — inner_ctx now has "outer_request" but
        # outer_tok is bound to the outer context, NOT the copy
        inner_ctx = contextvars.copy_context()

        errors: list[ValueError] = []

        def attempt_reset_in_copy():
            # Trying to reset a token from the outer context inside a copy raises ValueError
            try:
                mcp_request_id_var.reset(outer_tok)
            except ValueError as e:
                errors.append(e)

        inner_ctx.run(attempt_reset_in_copy)

        # Clean up the outer token
        mcp_request_id_var.reset(outer_tok)

        # The ValueError was real — this is what the middleware's guard catches
        assert len(errors) == 1, "Expected ValueError from cross-context reset"
        assert isinstance(errors[0], ValueError)

    @pytest.mark.asyncio
    async def test_v3_middleware_swallows_cross_context_value_error(self, temp_log_dir):
        """AC-MCP-4: middleware's except ValueError: pass prevents propagation.

        Run on_call_tool normally to verify it doesn't crash even when the contextvar
        has a pre-existing value from the outer scope (a common real-world pattern).
        The cross-context ValueError is demonstrated separately above.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        from cisternal.telemetry.context import mcp_request_id_var

        # Pre-set the contextvar (simulating a caller that already set it)
        outer_tok = mcp_request_id_var.set("caller_request")

        context = Mock()
        context.message.name = "tool_with_outer_ctx"
        context.message.arguments = {}

        async def call_next(ctx):
            return {"data": "ok"}

        middleware = CisternalMiddleware()
        result = await middleware.on_call_tool(context, call_next)

        # Middleware completes without exception despite pre-existing contextvar
        assert result is not None
        assert result.get("ok") is True

        # Cleanup outer token
        mcp_request_id_var.reset(outer_tok)


class TestAdapterAllowedNames:
    """Verify ALLOWED_NAMES are correctly defined on adapters."""

    def test_bathos_adapter_allowed_names(self):
        """BathosAdapter should have the correct ALLOWED_NAMES."""
        adapter = BathosAdapter()
        expected = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
        assert adapter.ALLOWED_NAMES == expected

    def test_contemplex_adapter_allowed_names(self):
        """ContemplexAdapter should have the correct ALLOWED_NAMES."""
        adapter = ContemplexAdapter()
        expected = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
        assert adapter.ALLOWED_NAMES == expected

    def test_xperiri_adapter_allowed_names(self):
        """XpeririAdapter should have the correct ALLOWED_NAMES."""
        adapter = XpeririAdapter()
        expected = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
        assert adapter.ALLOWED_NAMES == expected

    def test_myxcel_adapter_allowed_names(self):
        """MyxcelAdapter should have the correct ALLOWED_NAMES."""
        adapter = MyxcelAdapter()
        expected = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
        assert adapter.ALLOWED_NAMES == expected


class TestRuntimeNameGuard:
    """AC-NAMEFREEZE-4: Runtime guard via _swallow_name_error."""

    def test_swallow_name_error_warns_and_returns_none(self, temp_log_dir, capsys):
        """_swallow_name_error prints to stderr and returns None (warn-and-continue)."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        adapter = BathosAdapter()
        result = adapter._swallow_name_error("illegal.name")
        assert result is None
        assert "ILLEGAL event name" in capsys.readouterr().err

    def test_runtime_guard_raises_when_monkeypatched(self, temp_log_dir):
        """When _swallow_name_error is monkeypatched to raise, assert fails."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        class BadAdapter(AdapterBase):
            ALLOWED_NAMES = frozenset()  # No allowed names

            def shape_ok(self, tool_name, result):
                return result

            def shape_error(self, tool_name, exc, **fields):
                return {"error": str(exc)}

        adapter = BadAdapter()

        # Monkeypatch _swallow_name_error to raise AssertionError
        def raising_swallow(name):
            raise AssertionError(f"Illegal name: {name}")

        adapter._swallow_name_error = raising_swallow  # type: ignore

        # emit_start checks ALLOWED_NAMES and calls _swallow_name_error if not found
        # The assert should fail because _swallow_name_error raises
        with pytest.raises(AssertionError, match="Illegal name"):
            adapter.emit_start("mcp.call_start", [], "req-1")


class TestAcMcp5RealFastMCPServer:
    """AC-MCP-5 (bugfix, cisternal/mcp-middleware-fix, 260728): CisternalMiddleware
    against a REAL fastmcp.FastMCP server, not Mock().

    This is the test that would have caught the confirmed bug: on a real
    server, ``call_next(context)`` returns a ``fastmcp.tools.tool.ToolResult``
    object, never a dict. The old hardcoded ``BathosAdapter()`` -- whose
    ``shape_ok`` does ``isinstance(result, dict)`` -- silently discarded
    every real tool result, and its ``shape_error`` returns a plain dict with
    no ``.to_mcp_result()``, which crashes once FastMCP tries to normalize
    the middleware's return value.

    All three assertions are made by comparing a server WITH
    CisternalMiddleware(adapter=PassthroughAdapter(), reraise=True) installed
    against a baseline server with NO middleware installed at all:
      (a) success: shaped result is unchanged from the no-middleware baseline.
      (b) error: the raise still propagates exactly as it would with no
          middleware installed.
      (c) telemetry: records were captured for both the success and error path.
    """

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        clear_registry(name="default")
        yield
        clear_registry(name="default")

    @pytest.mark.asyncio
    async def test_successful_call_unchanged_vs_no_middleware(self, temp_log_dir):
        """(a) Successful call's shaped ToolResult == the no-middleware baseline."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @cisternal_tool
        def add_two(a: int, b: int) -> int:
            return a + b

        baseline_server = fastmcp.FastMCP("mcp-fix-baseline-ok")
        wire(baseline_server)
        baseline_result = await baseline_server.call_tool("add_two", {"a": 3, "b": 4})

        mw_server = fastmcp.FastMCP("mcp-fix-with-middleware-ok")
        wire(mw_server)
        mw_server.add_middleware(
            CisternalMiddleware(adapter=PassthroughAdapter(), reraise=True)
        )
        mw_result = await mw_server.call_tool("add_two", {"a": 3, "b": 4})

        time.sleep(0.1)

        # The middleware must not reshape/discard the real ToolResult.
        assert mw_result == baseline_result, (
            f"Middleware-shaped result must equal the no-middleware baseline; "
            f"got {mw_result!r} vs baseline {baseline_result!r}"
        )
        assert mw_result.structured_content == {"result": 7}

        # (c) telemetry was captured for the success path.
        start_records = [r for r in shadow.records if r.name == "mcp.call_start"]
        end_records = [r for r in shadow.records if r.name == "mcp.call_end"]
        assert len(start_records) == 1
        assert len(end_records) == 1
        assert start_records[0].fields["tool"] == "add_two"

    @pytest.mark.asyncio
    async def test_raising_call_still_propagates_with_reraise(self, temp_log_dir):
        """(b) A raising tool call still raises/propagates exactly as it would
        with no middleware installed, when reraise=True."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @cisternal_tool
        def boom(x: int) -> int:
            raise ValueError(f"boom: {x}")

        baseline_server = fastmcp.FastMCP("mcp-fix-baseline-err")
        wire(baseline_server)
        baseline_exc: BaseException | None = None
        try:
            await baseline_server.call_tool("boom", {"x": 1})
        except Exception as exc:  # noqa: BLE001 - capturing for comparison
            baseline_exc = exc

        mw_server = fastmcp.FastMCP("mcp-fix-with-middleware-err")
        wire(mw_server)
        mw_server.add_middleware(
            CisternalMiddleware(adapter=PassthroughAdapter(), reraise=True)
        )
        mw_exc: BaseException | None = None
        try:
            await mw_server.call_tool("boom", {"x": 1})
        except Exception as exc:  # noqa: BLE001 - capturing for comparison
            mw_exc = exc

        time.sleep(0.1)

        assert baseline_exc is not None, "baseline (no middleware) call must raise"
        assert mw_exc is not None, "middleware in reraise=True mode must still raise"
        assert type(mw_exc) is type(baseline_exc)
        assert str(mw_exc) == str(baseline_exc)

        # (c) telemetry was captured for the error path (start + tool_error).
        start_records = [r for r in shadow.records if r.name == "mcp.call_start"]
        error_records = [r for r in shadow.records if r.name == "mcp.tool_error"]
        assert len(start_records) == 1
        assert len(error_records) == 1
        assert error_records[0].fields["tool"] == "boom"
        # Note: by the time the exception reaches our middleware's except
        # clause, FastMCP's own tool-execution core has already wrapped the
        # raw ValueError into a fastmcp.exceptions.ToolError (this happens
        # inside call_next, on both the baseline and middleware paths alike —
        # confirmed identical above via type(mw_exc) is type(baseline_exc)).
        assert error_records[0].fields["exc_type"] == type(baseline_exc).__name__
        assert "boom: 1" in error_records[0].fields["exc_msg"]

    @pytest.mark.asyncio
    async def test_default_adapter_still_bathos_shapes_dict_result(self, temp_log_dir):
        """Constructor default (no adapter passed) is still BathosAdapter -- the
        additive, backward-compatible part of the fix (spec item 1)."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        middleware = CisternalMiddleware()
        assert isinstance(middleware._adapter, BathosAdapter)

    @pytest.mark.asyncio
    async def test_reraise_default_false_preserves_ch5_behavior(self, temp_log_dir):
        """reraise defaults to False: errors are still caught and shaped, never
        propagated -- zero behavior change for existing (pre-fix) callers."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        context = Mock()
        context.message = Mock()
        context.message.name = "legacy_tool"
        context.message.arguments = {}

        async def call_next_error(ctx):
            raise RuntimeError("legacy boom")

        middleware = CisternalMiddleware()  # adapter=None, reraise=False (defaults)
        result = await middleware.on_call_tool(context, call_next_error)

        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "legacy boom" in result["error"]
