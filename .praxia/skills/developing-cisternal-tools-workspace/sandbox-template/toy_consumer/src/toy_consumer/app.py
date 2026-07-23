"""toy-consumer's tool server, mirroring bathos's src/bathos/mcp.py pattern:
wrapper functions named mcp_x_tool expose a shorter tool name x via
toy_cisternal.tool(name=...), then a single wire() call registers everything.
"""

from __future__ import annotations

from toy_cisternal import tool, wire
from toy_cisternal.wire import ToyApp


@tool(name="list_widgets")
def mcp_list_widgets_tool(limit: int = 10) -> list[str]:
    """List widgets (stand-in for real domain logic)."""
    return [f"widget-{i}" for i in range(limit)]


@tool(name="get_widget")
def mcp_get_widget_tool(widget_id: str) -> dict:
    """Get a single widget by id (stand-in for real domain logic)."""
    return {"id": widget_id}


app = ToyApp("toy-consumer")
_WIRED = wire(app, expected=["list_widgets", "get_widget"])
