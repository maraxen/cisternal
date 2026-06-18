"""cisterna.registration — tool registration and wiring subsystem.

Public API:

    CisternaWireError   — exception raised by wire() on missing required tools
    tool                — decorator: pure metadata marker, returns fn unchanged
    clear_registry      — test teardown helper; clears a named registry
    wire                — snapshot a registry and produce a FastMCP server

Import safety:
    This package is safe to import at module load time.
"""

from __future__ import annotations

from cisterna.registration.decorator import tool
from cisterna.registration.errors import CisternaWireError
from cisterna.registration.registry import clear_registry

__all__ = [
    "CisternaWireError",
    "tool",
    "clear_registry",
    "wire",
]


def __getattr__(name: str) -> object:
    """Lazy re-export for wire (avoids importing fastmcp at package load time)."""
    if name == "wire":
        from cisterna.registration.wired import wire as _wire

        return _wire
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
