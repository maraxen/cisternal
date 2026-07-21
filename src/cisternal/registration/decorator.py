"""Public decorator for the cisternal registration subsystem.

The ``@tool`` decorator is a PURE METADATA MARKER (AC-M2-1, C1):
  - It registers the function into the named registry partition.
  - It returns the ORIGINAL function unchanged: ``decorated_fn is fn`` is True.
  - It does NOT wrap, monkey-patch, or alter the function in any way that
    changes identity or behavior.
  - ``asyncio.iscoroutinefunction(decorated_fn)`` is unchanged for both sync
    and async callables.

Usage::

    @tool
    def my_sync_tool(x: int) -> int:
        return x * 2

    @tool(registry="bathos")
    async def my_async_tool(x: int) -> int:
        return x * 2

    # Both of these are True:
    assert my_sync_tool is my_sync_tool   # trivially
    assert asyncio.iscoroutinefunction(my_async_tool)

A benign marker attribute ``__cisternal_tool__ = True`` is set on *fn* before
returning it.  This does not change the callable's identity (``is`` still
holds) and does not affect ``asyncio.iscoroutinefunction``.
"""

from __future__ import annotations

from typing import Any, Callable, overload

from cisternal.registration.registry import register


# ---------------------------------------------------------------------------
# Overloaded signatures so type checkers understand both call forms.
# ---------------------------------------------------------------------------

@overload
def tool(fn: Callable[..., Any]) -> Callable[..., Any]: ...  # @tool (bare)


@overload
def tool(
    fn: None = None,
    *,
    registry: str = "default",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...  # @tool(...)


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    registry: str = "default",
) -> Callable[..., Any]:
    """Pure metadata marker: register *fn* in the named registry.

    Supports both ``@tool`` (bare) and ``@tool(registry="name")``.

    The decorated function is returned UNCHANGED.  ``decorated_fn is fn``
    is always True.

    Args:
        fn:       The function to register.  Supplied positionally when the
                  decorator is used bare (``@tool``).
        registry: Which named registry partition to store the tool in.

    Returns:
        The original *fn* (not a wrapper).
    """
    def _register_and_return(f: Callable[..., Any]) -> Callable[..., Any]:
        register(f, registry=registry)
        # Benign marker attr — does NOT change callable identity.
        f.__cisternal_tool__ = True  # type: ignore[attr-defined]
        return f

    if fn is not None:
        # Bare usage: @tool
        return _register_and_return(fn)

    # Parameterised usage: @tool(registry="name")
    return _register_and_return


__all__ = ["tool"]
