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

    The generated callable contains no references to adapters, middleware,
    telemetry, or any import that could trigger telemetry.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from cisterna.registration.shim import dispatch


def compose_mcp_callable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap *fn* in an MCP-compatible async callable.

    Applies E2 outer form (always async), E1 dispatch shim (await iff async),
    H1 signature copy (explicit ``__signature__``), and respects C5 (zero
    telemetry emitted by the generated callable).

    The generated callable is a pure passthrough: it calls through to the
    original via :func:`cisterna.registration.shim.dispatch` and does nothing
    else.  It does not reference any adapter, does not import or call
    CisternaMiddleware, and emits no telemetry.

    Args:
        fn: The original tool function (sync or async).

    Returns:
        A new ``async def`` callable whose ``__signature__`` matches *fn*.
        The generated callable has:

        - ``asyncio.iscoroutinefunction(generated) == True``  (E2)
        - ``generated.__signature__ == inspect.signature(fn)``  (H1)
        - ``generated.__wrapped__ == fn``  (traceability)
        - ``generated.__name__ == fn.__name__``  (via update_wrapper)
        - ``generated.__doc__ == fn.__doc__``  (via update_wrapper)
    """
    # Capture the original signature BEFORE wrapping so Annotated[] metadata
    # is preserved.  inspect.signature() follows __wrapped__ chains, so we
    # must capture it now.
    original_sig = inspect.signature(fn)

    # Define the generated MCP callable.  It is ALWAYS async (E2 outer form).
    # Inside, the E1 shim (dispatch) handles sync vs async originals.
    #
    # NOTE: We capture `fn` by closure.  There is no reference to any adapter,
    # middleware, or telemetry here.  C5 is satisfied.
    async def _mcp_callable(*args: Any, **kwargs: Any) -> Any:
        return await dispatch(fn, *args, **kwargs)

    # Step 1: apply functools.update_wrapper to copy __name__, __doc__,
    # __annotations__, __module__, __qualname__, and set __wrapped__.
    # update_wrapper does NOT set __signature__ — that comes in step 2.
    functools.update_wrapper(_mcp_callable, fn)

    # Step 2: explicitly set __signature__ to the original's signature (H1).
    # This is the ONLY way to preserve Annotated[] parameters and return
    # annotations for introspection by FastMCP and other tools.
    _mcp_callable.__signature__ = original_sig  # type: ignore[attr-defined]

    return _mcp_callable
