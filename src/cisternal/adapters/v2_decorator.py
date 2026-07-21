"""traced_tool: FastMCP v2 integration via decorator (spec §3.8).

Double-decorator pattern: outer decorator takes an adapter, inner decorator
wraps the tool function. On each call, emits telemetry, measures duration,
and returns a shaped response. Never re-raises exceptions (CH-5).

Sync and async originals are supported: async tools get an ``async def`` wrapper
that awaits the original (mirrors :func:`cisternal.registration.shim.dispatch`).

(CH-10, AC-MCP-4) Token management: set/reset with ValueError guard.
"""

import asyncio
import functools
import time
import uuid
from typing import Any, Callable, TypeVar

from cisternal.telemetry.context import mcp_request_id_var
from cisternal.adapters.base import AdapterBase

T = TypeVar("T")


def _reset_request_token(token: Any) -> None:
    try:
        mcp_request_id_var.reset(token)
    except ValueError:
        # AC-MCP-4: Token from different context; swallow.
        pass


def traced_tool(
    adapter: AdapterBase,
) -> Callable[[Callable[..., T]], Callable[..., Any]]:
    """Decorator to wrap a FastMCP v2 tool with telemetry.

    Usage:
        @traced_tool(ContemplexAdapter())
        def my_tool(arg: str) -> str:
            return f"result: {arg}"

        @traced_tool(MyxcelAdapter())
        async def mount_project(remote: str, project: str) -> dict:
            ...

    Args:
        adapter: AdapterBase instance (e.g., BathosAdapter(), ContemplexAdapter()).

    Returns:
        Decorator function that wraps the tool (sync or async).
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                request_id = uuid.uuid4().hex
                token = mcp_request_id_var.set(request_id)
                arg_keys = sorted(kwargs.keys())  # CH-6: kwargs only (parity caveat)
                adapter.emit_start(fn.__name__, arg_keys, request_id)
                t0 = time.monotonic_ns()

                try:
                    result = await fn(*args, **kwargs)
                    adapter.emit_end(
                        fn.__name__, request_id, (time.monotonic_ns() - t0) / 1e6
                    )
                    return adapter.shape_ok(fn.__name__, result)
                except Exception as exc:
                    adapter.emit_error(fn.__name__, request_id, exc)
                    return adapter.shape_error(fn.__name__, exc)
                finally:
                    _reset_request_token(token)

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            request_id = uuid.uuid4().hex
            token = mcp_request_id_var.set(request_id)
            arg_keys = sorted(kwargs.keys())  # CH-6: kwargs only (parity caveat)
            adapter.emit_start(fn.__name__, arg_keys, request_id)
            t0 = time.monotonic_ns()

            try:
                result = fn(*args, **kwargs)
                adapter.emit_end(
                    fn.__name__, request_id, (time.monotonic_ns() - t0) / 1e6
                )
                return adapter.shape_ok(fn.__name__, result)
            except Exception as exc:
                adapter.emit_error(fn.__name__, request_id, exc)
                return adapter.shape_error(fn.__name__, exc)
            finally:
                _reset_request_token(token)

        return sync_wrapper

    return decorator
