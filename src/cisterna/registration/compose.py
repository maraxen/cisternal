"""MCP callable composition for the cisterna registration subsystem.

This module is responsible for taking a plain Python function (sync or async)
and producing the generated MCP-compatible callable that wraps it according to
the E2/E1 dispatch rules:

E2 (outer form):
    The generated callable is ALWAYS ``async def``.
    ``asyncio.iscoroutinefunction(generated) == True`` for both sync and async
    originals.

E1 (inner dispatch shim):
    - If the original is async: ``await fn(...)``
    - If the original is sync: ``fn(...)`` (direct call, no thread executor)

H1 (signature preservation):
    ``generated.__signature__`` is set EXPLICITLY to
    ``inspect.signature(original)`` because ``functools.update_wrapper`` does
    NOT copy ``__signature__``.  ``Annotated[]`` parameter metadata is
    preserved.  The return annotation is left untouched.

C5 (telemetry hard invariant):
    The generated callable MUST NOT call any telemetry methods
    (``adapter.emit_start``, ``emit_end``, ``emit_error``, ``shape_ok``,
    ``shape_error``, etc.).  All telemetry is owned by
    :class:`cisterna.adapters.v3_middleware.CisternaMiddleware`.

Implementation note:
    The authoritative implementation lives in the M2-COMPOSE track (item 2141).
    This stub exists so the package skeleton imports cleanly.
"""

from __future__ import annotations

from typing import Any, Callable


def compose_mcp_callable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap *fn* in an MCP-compatible async callable.

    Applies E2 outer form (always async), E1 dispatch shim (await iff async),
    H1 signature copy, and respects C5 (zero telemetry emitted here).

    Args:
        fn: The original tool function (sync or async).

    Returns:
        A new ``async def`` callable whose ``__signature__`` matches *fn*.

    Raises:
        NotImplementedError: Until M2-COMPOSE (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")
