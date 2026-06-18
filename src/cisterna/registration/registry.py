"""Named-registry storage for the cisterna registration subsystem.

Design (B1 — named registries):
    Tools are stored in named partitions. The default partition is "default".
    Each call to @cisterna.tool(registry="name") appends the decorated function
    to the named registry.  Registries are module-level singletons keyed by
    name; all mutations are synchronous and not thread-safe (single-threaded
    tool-decoration phase assumed).

Snapshot semantics (C6):
    cisterna.wire() takes a point-in-time snapshot of a registry.  Any tool
    decorated *after* wire() is called is NOT visible to the wired server.
    This is by design: once a server is wired its tool set is frozen.  Callers
    that need to add tools must call wire() again to obtain a new server.

Implementation note:
    The authoritative implementation lives in the M2-REGISTRY track (item 2141).
    This module provides a documented stub so that the package skeleton imports
    cleanly and downstream code can reference the intended API surface without
    pulling in unfinished implementation.
"""

from __future__ import annotations

from typing import Any, Callable

# Module-level registry store.  Keys are registry names; values are dicts
# mapping tool name -> callable.  Populated by @cisterna.tool at decoration
# time and snapshotted by cisterna.wire() at wire time.
_REGISTRIES: dict[str, dict[str, object]] = {}


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    registry: str = "default",
    name: str | None = None,
) -> Callable[..., Any]:
    """Pure metadata marker: register *fn* in the named registry.

    Calling this decorator must NOT alter *fn* in any way.  The returned
    object must satisfy ``decorated_fn is fn``.

    Args:
        fn: The function to register.  When the decorator is used without
            arguments (``@cisterna.tool``) this is supplied positionally.
        registry: Which named registry to store the tool in.  Defaults to
            ``"default"``.
        name: Override for the tool name stored in the registry.  If None,
            ``fn.__name__`` is used.

    Returns:
        *fn* unchanged.

    Raises:
        NotImplementedError: Until M2-REGISTRY (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")


def clear_registry(registry: str = "default") -> None:
    """Remove all entries from the named registry.

    Primarily for test teardown.  Calling this on a registry that does not
    exist is a no-op.

    Args:
        registry: The registry name to clear.  Defaults to ``"default"``.

    Raises:
        NotImplementedError: Until M2-REGISTRY (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")


def _registry(name: str = "default") -> dict[str, object]:
    """Return a live view of the named registry (not a copy).

    Internal API used by cisterna.wire() and tests.

    Args:
        name: Registry name.  Defaults to ``"default"``.

    Returns:
        The dict mapping tool name -> callable for the named registry.

    Raises:
        NotImplementedError: Until M2-REGISTRY (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")


def _snapshot(name: str = "default") -> dict[str, object]:
    """Return a shallow copy (snapshot) of the named registry at call time.

    Used by cisterna.wire() to implement C6 snapshot semantics: tools added
    after the snapshot is taken are not reflected in the returned dict.

    Args:
        name: Registry name.  Defaults to ``"default"``.

    Returns:
        A new dict that is a copy of the registry at this moment.

    Raises:
        NotImplementedError: Until M2-REGISTRY (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")
