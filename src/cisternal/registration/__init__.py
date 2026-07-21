"""cisternal.registration — tool registration and wiring subsystem.

Public API:

    CisternalWireError   — exception raised by wire() on missing required tools
    WiredRegistry       — introspection object returned by wire()
    tool                — decorator: pure metadata marker, returns fn unchanged
    clear_registry      — test teardown helper; clears a named registry
    list_registries   — partition names that currently exist
    snapshot            — shallow copy of a registry partition (C6)
    wire                — snapshot a registry and register tools on a FastMCP server

Import safety:
    This package is safe to import at module load time.
"""

from __future__ import annotations

from cisternal.registration.compose import compose_mcp_callable
from cisternal.registration.decorator import tool
from cisternal.registration.errors import CisternalWireError
from cisternal.registration.registry import clear_registry, list_registries, snapshot

__all__ = [
    "CisternalWireError",
    "WiredRegistry",
    "compose_mcp_callable",
    "list_registries",
    "snapshot",
    "tool",
    "clear_registry",
    "wire",
]


def __getattr__(name: str) -> object:
    """Lazy re-exports for wire and WiredRegistry (avoids importing fastmcp at package load time)."""
    if name == "wire":
        from cisternal.registration.wired import wire as _wire

        return _wire
    if name == "WiredRegistry":
        from cisternal.registration.wired import WiredRegistry as _WiredRegistry

        return _WiredRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
