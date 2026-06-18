"""Wire entry point for the cisterna registration subsystem.

``cisterna.wire()`` is the main user-facing API for producing a transport
server from a registry snapshot.

Behaviour (C6 — snapshot semantics):
    ``wire()`` takes a point-in-time snapshot of the named registry via
    :func:`cisterna.registration.registry._snapshot`.  Tools decorated with
    ``@cisterna.tool`` *after* ``wire()`` is called are NOT included in the
    returned server; they are invisible to it.

Error contract:
    If caller passes ``require=["tool_a", "tool_b"]`` and any of those names
    are not present in the registry snapshot, ``wire()`` raises
    :class:`cisterna.registration.errors.CisternaWireError` with
    ``missing=[<absent names>]``.

Transport:
    The returned object is a ``fastmcp.FastMCP`` instance pre-populated with
    the generated MCP callables for each registered tool.

Implementation note:
    The authoritative implementation lives in the M2-WIRE track (item 2141).
    This stub exists so the package skeleton imports cleanly.
"""

from __future__ import annotations

from typing import Any


def wire(
    registry: str = "default",
    *,
    require: list[str] | None = None,
    name: str = "cisterna",
    **fastmcp_kwargs: Any,
) -> Any:
    """Snapshot the named registry and build a FastMCP server from it.

    Args:
        registry: Which named registry to snapshot.  Defaults to
            ``"default"``.
        require: Optional list of tool names that must be present in the
            snapshot.  If any are absent,
            :class:`~cisterna.registration.errors.CisternaWireError` is
            raised.
        name: Name passed to ``fastmcp.FastMCP(name=...)``.
        **fastmcp_kwargs: Additional keyword arguments forwarded to
            ``fastmcp.FastMCP``.

    Returns:
        A configured ``fastmcp.FastMCP`` server instance.

    Raises:
        CisternaWireError: If any name in *require* is absent from the
            registry snapshot.
        NotImplementedError: Until M2-WIRE (2141) ships.
    """
    raise NotImplementedError("implemented in M2-REGISTRY (2141)")
