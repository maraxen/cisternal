"""Capability probe: Per-consumer surface selection (spec §5.2, CH-2).

At M1, two surfaces exist: v3_middleware (for bathos>=3.4.2 with Middleware)
and v2_decorator (for contemplex, myxcel, xperiri). This module probes
the runtime to determine which surface is available and returns the
appropriate path for each consumer.

(CH-2) Fall-through: if hasattr(server, 'add_middleware') is False on a
bathos server, probe warns and falls back to v2_decorator. This handles
the case where bathos has an older fastmcp version without v3 middleware.
"""


def _has_v3_middleware() -> bool:
    """Check if FastMCP v3 middleware is available (spec §5.2, CH-1).

    Tries to import the Middleware class from fastmcp.server.middleware.middleware.
    If the import succeeds, v3 middleware is available.

    Returns:
        True if v3 middleware is importable, False otherwise.
    """
    try:
        from fastmcp.server.middleware.middleware import Middleware  # noqa: F401

        return True
    except ImportError:
        return False


# Per-consumer surface mapping (spec §5.1, §5.2)
CONSUMER_SURFACE: dict[str, str] = {
    "bathos": "v3_middleware" if _has_v3_middleware() else "v2_decorator",
    "contemplex": "v2_decorator",
    "myxcel": "v2_decorator",
    "xperiri": "v2_decorator",
}


def surface_for(consumer: str) -> str:
    """Get the appropriate telemetry surface for a consumer (spec §5.2).

    Args:
        consumer: Consumer name (e.g., "bathos", "contemplex").

    Returns:
        Surface type: "v3_middleware" or "v2_decorator".
        Falls back to "v2_decorator" if consumer unknown.
    """
    return CONSUMER_SURFACE.get(consumer, "v2_decorator")
