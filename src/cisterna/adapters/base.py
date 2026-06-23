"""AdapterBase: Consumer-agnostic adapter protocol (spec §3.6, §5.4).

Each adapter owns the event-name set (ALLOWED_NAMES) and the response shape
for its consumer (shape_ok/shape_error). The MCP wrappers (CisternaMiddleware,
traced_tool) instantiate an adapter, delegate telemetry emission + shaping to it,
and never re-raise exceptions (CH-5).

(CH-9) Runtime name guard: emit_start/end/error check that the emitted name is
in self.ALLOWED_NAMES; on mismatch, calls _swallow_name_error (stderr warn + continue).
Tests monkeypatch _swallow_name_error to raise AssertionError instead.
"""

from abc import ABC, abstractmethod
import json
import sys
from typing import Any

from cisterna import emit_event


class AdapterBase(ABC):
    """Abstract base for MCP tool adapters (v3 middleware, v2 decorator, etc.).

    Each subclass defines:
    - ALLOWED_NAMES: frozenset[str] of event names this adapter may emit.
    - shape_ok(tool_name, result): Transform success response.
    - shape_error(tool_name, exc): Transform error response.
    """

    ALLOWED_NAMES: frozenset[str]

    def emit_start(self, tool_name: str, arg_keys: list[str], request_id: str) -> None:
        """Emit mcp.call_start event.

        Args:
            tool_name: Name of the tool being called.
            arg_keys: Sorted list of argument keys (spec §3.7, §3.8).
            request_id: Unique request ID for this invocation.
        """
        name = "mcp.call_start"
        if name not in self.ALLOWED_NAMES:
            self._swallow_name_error(name)
        emit_event(name, tool=tool_name, arg_keys=arg_keys, request_id=request_id)

    def emit_end(self, tool_name: str, request_id: str, duration_ms: float) -> None:
        """Emit mcp.call_end event.

        Args:
            tool_name: Name of the tool that executed.
            request_id: The request ID from emit_start.
            duration_ms: Duration of execution in milliseconds.
        """
        name = "mcp.call_end"
        if name not in self.ALLOWED_NAMES:
            self._swallow_name_error(name)
        emit_event(name, tool=tool_name, request_id=request_id, duration_ms=duration_ms)

    def emit_error(self, tool_name: str, request_id: str, exc: BaseException) -> None:
        """Emit mcp.tool_error event.

        Args:
            tool_name: Name of the tool that raised.
            request_id: The request ID from emit_start.
            exc: The exception that was raised.
        """
        name = "mcp.tool_error"
        if name not in self.ALLOWED_NAMES:
            self._swallow_name_error(name)
        emit_event(
            name,
            tool=tool_name,
            request_id=request_id,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )

    @abstractmethod
    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape a successful tool result for the consumer.

        Args:
            tool_name: Name of the tool (for context).
            result: The result returned by the tool.

        Returns:
            Consumer-specific shaped response (dict, str, or other).
        """
        pass

    @abstractmethod
    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape an error response for the consumer (never re-raises).

        Args:
            tool_name: Name of the tool (for context).
            exc: The exception that was caught.
            **fields: Optional extra fields for the error envelope.

        Returns:
            Consumer-specific error shape (dict, str, or other).
        """
        pass

    def _swallow_name_error(self, name: str) -> None:
        """Handle illegal event name: log to stderr and return (warn-and-continue).

        Tests may monkeypatch this to raise AssertionError (AC-NAMEFREEZE-4).

        Args:
            name: The illegal event name.
        """
        print(f"[cisterna] ILLEGAL event name: {name!r}", file=sys.stderr)


class BathosAdapter(AdapterBase):
    """Adapter for bathos v3 middleware.

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: dict envelope with ok/error_code/error/resolution_hint.
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: merge dict results, add envelope fields.

        If result is a dict, spread it and add envelope.
        Otherwise, return minimal envelope.
        """
        if isinstance(result, dict):
            return {
                **result,
                "ok": True,
                "error_code": None,
                "error": None,
                "resolution_hint": None,
            }
        return {
            "ok": True,
            "error_code": None,
            "error": None,
            "resolution_hint": None,
        }

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: error envelope with error_code and message."""
        return {
            "ok": False,
            "error_code": "INTERNAL",
            "error": str(exc),
            "resolution_hint": "",
        }


class ContemplexAdapter(AdapterBase):
    """Adapter for contemplex v2 decorator (sync).

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: passthrough for success; err_envelope for error.
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough result unchanged."""
        return result

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: use contemplex err_envelope if available, else fallback.

        Tries to import contemplex.errors; if unavailable, returns basic dict.
        """
        try:
            from contemplex.errors import ErrorCode, err_envelope

            return err_envelope(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}")
        except ImportError:
            # Fallback if contemplex is not available
            return {"ok": False, "error_code": "INTERNAL", "error": str(exc)}


class XpeririAdapter(AdapterBase):
    """Adapter for xperiri v2 decorator (sync, JSON-string MCP returns).

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: JSON string for success and error (xperiri MCP tools return str).
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough str; serialize dict/other to JSON."""
        if isinstance(result, str):
            return result
        return json.dumps(result, sort_keys=True)

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: JSON string envelope matching xperiri error returns."""
        payload: dict[str, Any] = {"ok": False, "error": str(exc)}
        payload.update(fields)
        return json.dumps(payload, sort_keys=True)
