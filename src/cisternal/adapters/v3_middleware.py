"""CisternalMiddleware: FastMCP v3 integration via middleware hook (spec §3.7).

Middleware fires on_call_tool for each tool call, wrapping the tool execution
with telemetry: emit_start, measure duration, emit_end or emit_error, return
shaped envelope. By default (``reraise=False``, back-compat), never re-raises
exceptions to the transport (CH-5) -- the adapter's shape_error is used to
build a returned error envelope instead.

Bugfix (cisternal/mcp-middleware-fix, 260728): against a *real* FastMCP
server, ``call_next(context)`` returns a ``fastmcp.tools.tool.ToolResult``,
never a ``dict`` -- FastMCP's own mixins later call ``.to_mcp_result()`` on
whatever this middleware returns. The previous hardcoded
``BathosAdapter()`` -- whose ``shape_ok`` checks ``isinstance(result, dict)``
-- silently discarded every real tool result, and its ``shape_error`` returns
a plain dict that has no ``.to_mcp_result()``, crashing with AttributeError
on every tool error. Fixed by:
  (1) an injectable ``adapter`` constructor param (defaults to
      ``BathosAdapter()`` for back-compat with existing v2/contemplex-style
      consumers who want a shaped dict envelope);
  (2) a ``reraise`` constructor flag: when True, telemetry (span timing,
      exception type/message) is still recorded on error, but the original
      exception is then re-raised untouched rather than shaped, letting
      FastMCP's own error mapping run exactly as if no middleware were
      installed. Pair this with ``adapters.base.PassthroughAdapter`` (whose
      ``shape_ok`` returns the ``ToolResult`` completely unmodified) for a
      real FastMCP server -- see that class's docstring.

(CH-10, AC-MCP-4) Token management: set/reset with ValueError guard for
cross-context token resets (possible in asyncio context copy scenarios).
"""

import time
import uuid
from typing import Any

from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext
from cisternal.telemetry.context import mcp_request_id_var
from cisternal.adapters.base import AdapterBase, BathosAdapter


class CisternalMiddleware(Middleware):
    """Middleware for FastMCP v3 servers.

    Wires via: server.add_middleware(CisternalMiddleware()).
    Fires on every tools/call request (spec §3.7).

    Args:
        adapter: Consumer-specific AdapterBase implementation that owns
            telemetry event-name validation and response shaping. Defaults
            to ``BathosAdapter()`` for back-compat. Pass
            ``adapters.base.PassthroughAdapter()`` when installing against a
            real FastMCP server, so successful ``ToolResult`` values are
            returned unmodified instead of being reshaped into a dict
            envelope.
        reraise: If True, a tool-call exception is still fully recorded via
            ``adapter.emit_error`` but is then re-raised as-is (bare
            ``raise``) instead of being passed to ``adapter.shape_error``.
            This lets FastMCP's own NotFoundError/ValidationError/ToolError
            handling run unmodified, as if this middleware weren't
            installed. Defaults to False (original CH-5 behavior: never
            re-raise, always return a shaped error envelope).
    """

    def __init__(self, adapter: AdapterBase | None = None, reraise: bool = False) -> None:
        self._adapter = adapter or BathosAdapter()
        self._reraise = reraise

    async def on_call_tool(self, context: MiddlewareContext, call_next: Any) -> Any:
        """Intercept tool call, emit telemetry, and return shaped response.

        Args:
            context: MiddlewareContext with .message = CallToolRequestParams.
                    .message.name = tool name (str)
                    .message.arguments = tool arguments (dict|None)
            call_next: Async callable to invoke the actual tool.

        Returns:
            ``self._adapter.shape_ok(tool_name, result)`` on success -- for
            ``PassthroughAdapter`` this is the ``ToolResult`` unmodified.
            On error: if ``reraise`` is False (default), the shaped error
            envelope from ``self._adapter.shape_error`` (never raises -- CH-5).
            If ``reraise`` is True, the original exception is re-raised after
            telemetry is recorded.
        """
        tool_name = context.message.name
        arguments = context.message.arguments or {}
        arg_keys = sorted(arguments.keys())  # CH-6: client-supplied keys only
        request_id = uuid.uuid4().hex

        # Set mcp_request_id in context for this call
        token = mcp_request_id_var.set(request_id)
        adapter = self._adapter
        adapter.emit_start(tool_name, arg_keys, request_id)
        t0 = time.monotonic_ns()

        try:
            result = await call_next(context)
            adapter.emit_end(tool_name, request_id, (time.monotonic_ns() - t0) / 1e6)
            return adapter.shape_ok(tool_name, result)
        except Exception as exc:
            adapter.emit_error(tool_name, request_id, exc)
            if self._reraise:
                raise
            return adapter.shape_error(tool_name, exc)
        finally:
            try:
                mcp_request_id_var.reset(token)
            except ValueError:
                # AC-MCP-4: Token was created in a different Context (e.g., via
                # copy_context().run() in asyncio). Swallow and continue.
                pass
