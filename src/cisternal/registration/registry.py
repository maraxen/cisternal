"""Named-registry storage for the cisternal registration subsystem.

Design (B1 — named registries):
    Tools are stored in named partitions. The default partition is "default".
    Each call to @cisternal.tool(registry="name") appends the decorated function
    to the named registry.  Registries are module-level singletons keyed by
    name; all mutations are synchronous and not thread-safe (single-threaded
    tool-decoration phase assumed).

Snapshot semantics (C6):
    cisternal.wire() takes a point-in-time snapshot of a registry.  Any tool
    decorated *after* wire() is called is NOT visible to the wired server.
    This is by design: once a server is wired its tool set is frozen.  Callers
    that need to add tools must call wire() again to obtain a new server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# ToolEntry
# ---------------------------------------------------------------------------


@dataclass
class ToolEntry:
    """Metadata record for a registered tool.

    Attributes:
        name:     The tool name as stored in the registry (defaults to fn.__name__).
        fn:       The original callable (unchanged by the decorator).
        registry: The partition name the tool was registered in.
    """

    name: str
    fn: Callable[..., Any]
    registry: str


# ---------------------------------------------------------------------------
# Module-level storage
# ---------------------------------------------------------------------------

# _REGISTRIES[partition_name][tool_name] = ToolEntry
_REGISTRIES: dict[str, dict[str, ToolEntry]] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _registry(name: str = "default") -> dict[str, ToolEntry]:
    """Return the live partition dict, creating it if absent.

    This returns a LIVE view (not a copy).  Mutations to the returned dict
    are reflected in _REGISTRIES.

    Args:
        name: Registry partition name.  Defaults to ``"default"``.

    Returns:
        The dict mapping tool name -> ToolEntry for the named partition.
    """
    if name not in _REGISTRIES:
        _REGISTRIES[name] = {}
    return _REGISTRIES[name]


def list_registries() -> tuple[str, ...]:
    """Return sorted names of registry partitions that currently exist.

    Does not create new partitions.  Partitions appear after the first tool
    is registered to that name (or after ``snapshot()`` creates one).
    """
    return tuple(sorted(_REGISTRIES))


def snapshot(name: str = "default") -> dict[str, ToolEntry]:
    """Return a shallow copy of the named partition at call time.

    Snapshot semantics (C6): entries added after this call are NOT reflected
    in the returned dict.  ``cisternal.wire()`` uses this so the wired tool
    set is frozen at wire time.

    Note: calling ``snapshot`` on a previously unseen *name* creates an
    empty partition.  Prefer :func:`list_registries` before snapshot when
    probing for existence (see ``registry_assets``).
    """
    return dict(_registry(name))


def _snapshot(name: str = "default") -> dict[str, ToolEntry]:
    """Alias for :func:`snapshot` (wire/tests compatibility)."""
    return snapshot(name)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def register(
    fn: Callable[..., Any],
    *,
    registry: str = "default",
    name: str | None = None,
) -> None:
    """Insert *fn* into the named registry partition.

    This is an internal helper called by the ``@tool`` decorator.  Direct
    callers should use the decorator instead.

    Args:
        fn:       The callable to register.
        registry: Partition name.  Defaults to ``"default"``.
        name:     Override for the stored tool name.  Defaults to ``fn.__name__``.
    """
    tool_name = name if name is not None else fn.__name__
    entry = ToolEntry(name=tool_name, fn=fn, registry=registry)
    _registry(registry)[tool_name] = entry


def clear_registry(name: str | None = None) -> None:
    """Remove all entries from a single registry partition.

    - ``name=None``  clears ONLY the ``"default"`` partition.
    - ``name="foo"`` clears ONLY the ``"foo"`` partition.
    - All other partitions are left untouched in both cases.

    Calling this on a partition that does not yet exist is a no-op.

    Args:
        name: The partition to clear.  ``None`` means ``"default"``.
    """
    target = name if name is not None else "default"
    if target in _REGISTRIES:
        _REGISTRIES[target].clear()
