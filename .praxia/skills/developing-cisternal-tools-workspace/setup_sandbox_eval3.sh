#!/usr/bin/env bash
# Provisions the eval-3 sandbox: the standard toy_cisternal/toy_consumer pair
# from setup_sandbox.sh, PLUS a second, unrelated consumer-side bug layered
# into toy_consumer -- a duplicate `@tool(name="get_widget")` on a
# delete_widget wrapper, which silently overwrites get_widget's registry
# entry (registry.py stores entries in a plain dict keyed by name; last
# registration wins). A misleading comment claims this is an intentional
# "soft-delete alias" feature. Usage: setup_sandbox_eval3.sh <target-dir>
set -euo pipefail

TARGET="${1:?usage: setup_sandbox_eval3.sh <target-dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$HERE/setup_sandbox.sh" "$TARGET"

APP="$TARGET/toy_consumer/src/toy_consumer/app.py"

cat > "$APP" <<'PYEOF'
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


# NOTE: delete_widget intentionally shares get_widget's registered name as a
# soft-delete alias -- calling either name is expected to hit whichever
# handler registered last. This is fine.
@tool(name="get_widget")
def mcp_delete_widget_tool(widget_id: str) -> dict:
    """Delete a single widget by id (stand-in for real domain logic)."""
    return {"id": widget_id, "deleted": True}


app = ToyApp("toy-consumer")
_WIRED = wire(app, expected=["list_widgets", "get_widget"])
PYEOF

cat > "$TARGET/toy_consumer/scripts/simulate_get_widget_confusion.py" <<'PYEOF'
"""Reproduces a second, separate bug report: calling the 'get_widget' tool
sometimes returns {'deleted': True} instead of the expected widget shape,
as if it's being confused with a delete operation.
"""

from toy_consumer.app import app

names = [t.name for t in app.list_tools()]
print("Tools actually exposed on the app:", names)

get_widget_tool = next((t for t in app.list_tools() if t.name == "get_widget"), None)
if get_widget_tool is None:
    print("get_widget tool not found on the app at all.")
else:
    result = get_widget_tool.fn("widget-1")
    print("Calling the 'get_widget' tool returned:", result)
    if result.get("deleted"):
        print("BUG REPRODUCED: 'get_widget' is actually running delete_widget's handler.")
    else:
        print("OK: 'get_widget' returns fetch semantics, not delete semantics.")
PYEOF

cd "$TARGET/toy_consumer"
git add -A
git -c user.email=sandbox@example.com -c user.name=Sandbox commit -q -m "toy-consumer: add delete_widget (shares get_widget's registered name)"

echo "Eval-3 sandbox ready at $TARGET (delete_widget/get_widget collision layered in)"
