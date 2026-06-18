"""Dispatch shim helpers for the cisterna registration subsystem.

The shim layer sits between the generated MCP callable (see
:mod:`cisterna.registration.compose`) and the original tool function.  Its
sole responsibility is to correctly invoke the original function and return its
result; it must never emit telemetry or mutate arguments.

Responsibilities:
    - Detect whether the original function is a coroutine function
      (``asyncio.iscoroutinefunction``).
    - For async originals: ``return await fn(*args, **kwargs)``
    - For sync originals: ``return fn(*args, **kwargs)``

C5 hard invariant:
    No telemetry calls here.  The shim is a pure passthrough.

Implementation note:
    The authoritative implementation lives in the M2-COMPOSE track (item 2141).
    This stub exists so the package skeleton imports cleanly.
"""

from __future__ import annotations

from typing import Any, Callable


async def dispatch(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Dispatch a call to *fn*, awaiting if it is a coroutine function.

    Args:
        fn: The original tool function (sync or async).
        *args: Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn*.

    Raises:
        NotImplementedError: Until M2-COMPOSE (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")


def is_async(fn: Callable[..., Any]) -> bool:
    """Return True if *fn* is a coroutine function.

    A thin wrapper around ``asyncio.iscoroutinefunction`` provided here so
    compose.py and tests can import it from a single location.

    Args:
        fn: Any callable.

    Returns:
        Whether *fn* is an async def function.

    Raises:
        NotImplementedError: Until M2-COMPOSE (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")
