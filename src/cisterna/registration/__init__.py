"""cisterna.registration — tool registration and wiring subsystem.

Public API:

    CisternaWireError   — exception raised by wire() on missing required tools
    WiredRegistry       — introspection object returned by wire()
    tool                — decorator: pure metadata marker, returns fn unchanged
    clear_registry      — test teardown helper; clears a named registry
    wire                — snapshot a registry and register tools on a FastMCP server

Import safety:
    This package is safe to import at module load time.
"""

from __future__ import annotations

from cisterna.registration.compose import compose_mcp_callable
from cisterna.registration.decorator import tool
from cisterna.registration.errors import CisternaWireError
from cisterna.registration.registry import clear_registry

__all__ = [
    "CisternaWireError",
    "WiredRegistry",
    "compose_mcp_callable",
    "tool",
    "clear_registry",
    "wire",
]


def __getattr__(name: str) -> object:
    """Lazy re-exports for wire and WiredRegistry (avoids importing fastmcp at package load time)."""
    if name == "wire":
        from cisterna.registration.wired import wire as _wire

        return _wire
    if name == "WiredRegistry":
        from cisterna.registration.wired import WiredRegistry as _WiredRegistry

        return _WiredRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
