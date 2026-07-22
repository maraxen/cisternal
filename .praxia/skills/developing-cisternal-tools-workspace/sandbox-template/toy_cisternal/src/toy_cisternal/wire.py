"""wire(): register every @tool()-decorated function onto a transport ("app").

Mirrors cisternal.registration.wired.wire() and its ToyApp-equivalent of
FastMCP's add_tool(). NOTE: this file intentionally reproduces the real
maraxen/cisternal#6 bug shape for rehearsal purposes -- add_tool() is called
with a bare callable, so ToyApp falls back to inferring the name from the
callable's own __name__ instead of the registry's name= override.
"""

from __future__ import annotations

from typing import Any, Callable

from toy_cisternal.registry import snapshot


class ToyTool:
    def __init__(self, name: str, fn: Callable[..., Any]) -> None:
        self.name = name
        self.fn = fn


class ToyApp:
    """Stand-in for a FastMCP-like server."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._tools: dict[str, ToyTool] = {}

    def add_tool(self, tool_or_fn: "ToyTool | Callable[..., Any]") -> None:
        if isinstance(tool_or_fn, ToyTool):
            self._tools[tool_or_fn.name] = tool_or_fn
        else:
            # Fallback path: infer the name from the callable itself.
            self._tools[tool_or_fn.__name__] = ToyTool(name=tool_or_fn.__name__, fn=tool_or_fn)

    def list_tools(self) -> list[ToyTool]:
        return list(self._tools.values())


def _compose_callable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Stand-in for compose_mcp_callable(): produces the transport-facing
    callable from the registered function. In the real library this also
    handles the sync/async dispatch shim and __signature__ preservation."""
    return fn


def wire(app: ToyApp, expected: list[str] | None = None) -> list[str]:
    snap = snapshot()

    if expected is not None:
        missing = [n for n in expected if n not in snap]
        if missing:
            raise ValueError(f"wire(): expected tools not found in registry: {missing}")

    wired_names: list[str] = []
    for entry in snap.values():
        callable_ = _compose_callable(entry.fn)
        app.add_tool(callable_)
        wired_names.append(entry.name)

    return wired_names
