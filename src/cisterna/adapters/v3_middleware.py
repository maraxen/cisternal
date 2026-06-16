"""CisternaMiddleware: FastMCP v3 integration via middleware hook (spec §3.7).

Middleware fires on_call_tool for each tool call, wrapping the tool execution
with telemetry: emit_start, measure duration, emit_end or emit_error, return
shaped envelope. Never re-raises exceptions to the transport (CH-5).

(CH-10, AC-MCP-4) Token management: set/reset with ValueError guard for
cross-context token resets (possible in asyncio context copy scenarios).
"""
import time
import uuid
from typing import Any

from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext
from cisterna.telemetry.context import mcp_request_id_var
from cisterna.adapters.base import BathosAdapter


class CisternaMiddleware(Middleware):
    """Middleware for FastMCP v3 servers.

    Wires via: server.add_middleware(CisternaMiddleware()).
    Fires on every tools/call request (spec §3.7).
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next: Any) -> Any:
        """Intercept tool call, emit telemetry, and return shaped response.

        Args:
            context: MiddlewareContext with .message = CallToolRequestParams.
                    .message.name = tool name (str)
                    .message.arguments = tool arguments (dict|None)
            call_next: Async callable to invoke the actual tool.

        Returns:
            Shaped response (dict envelope with ok/error) per BathosAdapter.
            Never raises; exceptions caught and returned as error envelopes.
        """
        tool_name = context.message.name
        arguments = context.message.arguments or {}
        arg_keys = sorted(arguments.keys())  # CH-6: client-supplied keys only
        request_id = uuid.uuid4().hex

        # Set mcp_request_id in context for this call
        token = mcp_request_id_var.set(request_id)
        adapter = BathosAdapter()
        adapter.emit_start(tool_name, arg_keys, request_id)
        t0 = time.monotonic_ns()

        try:
            result = await call_next(context)
            adapter.emit_end(tool_name, request_id, (time.monotonic_ns() - t0) / 1e6)
            return adapter.shape_ok(tool_name, result)
        except Exception as exc:
            adapter.emit_error(tool_name, request_id, exc)
            return adapter.shape_error(tool_name, exc)
        finally:
            try:
                mcp_request_id_var.reset(token)
            except ValueError:
                # AC-MCP-4: Token was created in a different Context (e.g., via
                # copy_context().run() in asyncio). Swallow and continue.
                pass
