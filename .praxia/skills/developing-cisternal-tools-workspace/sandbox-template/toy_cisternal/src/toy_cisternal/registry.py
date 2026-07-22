"""Named-registry storage + the @tool decorator.

Mirrors the real cisternal.registration.{decorator,registry} split: @tool is a
pure-metadata marker (returns fn unchanged), and register() supports an
explicit name= override that defaults to fn.__name__.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

_REGISTRY: dict[str, "ToolEntry"] = {}


@dataclass
class ToolEntry:
    name: str
    fn: Callable[..., Any]


def register(fn: Callable[..., Any], *, name: str | None = None) -> None:
    tool_name = name if name is not None else fn.__name__
    _REGISTRY[tool_name] = ToolEntry(name=tool_name, fn=fn)


def snapshot() -> dict[str, ToolEntry]:
    return dict(_REGISTRY)


def clear_registry() -> None:
    _REGISTRY.clear()


def tool(fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Callable[..., Any]:
    def _register_and_return(f: Callable[..., Any]) -> Callable[..., Any]:
        register(f, name=name)
        return f

    if fn is not None:
        return _register_and_return(fn)
    return _register_and_return
