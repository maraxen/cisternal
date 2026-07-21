"""Dispatch shim helpers for the cisternal registration subsystem.

The shim layer sits between the generated MCP callable (see
:mod:`cisternal.registration.compose`) and the original tool function.  Its
sole responsibility is to correctly invoke the original function and return its
result; it must never emit telemetry or mutate arguments.

Responsibilities:
    - Detect whether the original function is a coroutine function
      (``asyncio.iscoroutinefunction``).
    - For async originals: ``return await fn(*args, **kwargs)``
    - For sync originals: ``return fn(*args, **kwargs)``

C5 hard invariant:
    No telemetry calls here.  The shim is a pure passthrough.

TBD-M2-3 — async tool invoked via CLI inside a running event loop:
    When the original function is async, calling it requires ``await``.  If
    the caller is a CLI path that uses ``asyncio.run()``, ``asyncio.run`` will
    raise ``RuntimeError`` if there is ALREADY a running event loop (e.g. the
    user embedded the tool in a Jupyter notebook or an async framework like
    FastAPI).

    Resolution strategy (chosen for M2):
        The ``cli_dispatch`` helper detects a running loop via
        ``asyncio.get_running_loop()``.  If a loop is found and the original
        is async, a :class:`cisternal.registration.errors.CisternalWireError` is
        raised immediately with a clear explanation pointing the caller to
        ``app.run_async()``.  The ``dispatch`` coroutine itself is always safe
        to ``await`` from within an existing loop.

    Full CLI wiring (``asyncio.run`` orchestration from the CLI entry point)
    lands in the M2-WIRE track.  This module provides only the detection and
    error path.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from cisternal.registration.errors import CisternalWireError


async def dispatch(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Dispatch a call to *fn*, awaiting if it is a coroutine function.

    This is the E1 inner shim used inside the ``async def`` generated callable
    produced by :func:`cisternal.registration.compose.compose_mcp_callable`.
    It is always ``await``-ed by the outer generated callable, so it is itself
    a coroutine.

    Args:
        fn: The original tool function (sync or async).
        *args: Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn*.
    """
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return fn(*args, **kwargs)


def is_async(fn: Callable[..., Any]) -> bool:
    """Return True if *fn* is a coroutine function.

    A thin wrapper around ``asyncio.iscoroutinefunction`` provided here so
    compose.py and tests can import it from a single location.

    Args:
        fn: Any callable.

    Returns:
        Whether *fn* is an async def function.
    """
    return asyncio.iscoroutinefunction(fn)


def cli_dispatch(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """CLI-path helper: run *fn* from a synchronous context.

    For sync originals: calls ``fn(*args, **kwargs)`` directly and returns
    the result.

    For async originals: uses ``asyncio.run()`` to drive the coroutine, BUT
    first checks for a running event loop (TBD-M2-3).  If a loop is already
    running, ``asyncio.run()`` would raise ``RuntimeError``.  Instead, this
    function raises :class:`~cisternal.registration.errors.CisternalWireError`
    with a clear explanation.

    Args:
        fn: The original tool function (sync or async).
        *args: Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn* (for sync originals).

    Raises:
        CisternalWireError: If *fn* is async and a running event loop is
            detected.  The caller should use ``await fn(*args, **kwargs)``
            or ``app.run_async()`` instead.
    """
    if not asyncio.iscoroutinefunction(fn):
        return fn(*args, **kwargs)

    # Async original: detect running loop before calling asyncio.run().
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to call asyncio.run().
        return asyncio.run(fn(*args, **kwargs))

    # If we reach here, get_running_loop() succeeded: a loop is active.
    # asyncio.run() would raise RuntimeError; raise a clear error instead.
    raise CisternalWireError(
        message=(
            f"Cannot call async tool {fn.__name__!r} via the synchronous CLI "
            "dispatch path while an event loop is already running.  "
            "Use 'await fn(...)' inside an async context, or use "
            "'app.run_async()' for the CLI entry point.  "
            "(TBD-M2-3: full async CLI wiring lands in M2-WIRE.)"
        )
    )
