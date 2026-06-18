"""cisterna.registration — tool registration and wiring subsystem.

Public API (implemented in M2-REGISTRY / M2-WIRE, item 2141):

    CisternaWireError   — exception raised by wire() on missing required tools
    tool                — decorator: pure metadata marker, returns fn unchanged
    clear_registry      — test teardown helper; clears a named registry
    wire                — snapshot a registry and produce a FastMCP server

Only :class:`CisternaWireError` is fully implemented in this wave (M2-PKG,
item 2140).  The remaining symbols are documented stubs that raise
``NotImplementedError`` until M2-REGISTRY ships.

Import safety:
    This package is safe to import at module load time.  The stub functions
    raise only when *called*, never on import.
"""

from __future__ import annotations

from cisterna.registration.errors import CisternaWireError

__all__ = [
    "CisternaWireError",
    "tool",
    "clear_registry",
    "wire",
]


def __getattr__(name: str) -> object:
    """Lazy re-export for stub symbols to keep the package import-safe.

    Importing ``cisterna.registration.tool`` (or ``clear_registry`` / ``wire``)
    succeeds at import time; the ``NotImplementedError`` is raised only when
    the returned callable is *called*.
    """
    if name == "tool":
        from cisterna.registration.registry import tool as _tool

        return _tool
    if name == "clear_registry":
        from cisterna.registration.registry import clear_registry as _cr

        return _cr
    if name == "wire":
        from cisterna.registration.wired import wire as _wire

        return _wire
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
