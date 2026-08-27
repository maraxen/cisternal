"""Structural types for callables the registration/adapter layers introspect.

Plain ``Callable[..., T]`` erases attribute access, but the decorators in
``cisternal.adapters`` and ``cisternal.registration`` are only ever applied to
real ``def``/``async def`` functions in practice (never lambdas or arbitrary
callable objects) -- those genuinely carry ``__name__`` at runtime, and
support having ``__signature__``/``__cisternal_tool__`` attached for later
introspection. These protocols document that real shape so call sites can be
typed precisely instead of reaching for ``Callable``/``object``.
"""

from __future__ import annotations

from typing import Any, Protocol


class NamedCallable(Protocol):
    """A callable exposing ``__name__`` (any real function/coroutine function)."""

    __name__: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class TaggedCallable(Protocol):
    """A callable carrying the extra attributes cisternal's registration layer
    attaches for CLI/MCP introspection (``__signature__``, ``__cisternal_tool__``).
    """

    __name__: str
    __signature__: Any
    __cisternal_tool__: bool

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
