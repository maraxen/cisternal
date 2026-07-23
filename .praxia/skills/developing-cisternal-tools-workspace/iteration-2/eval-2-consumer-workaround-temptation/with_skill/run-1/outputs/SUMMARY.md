# Dashboard `list_widgets` fix (deferred-upstream workaround) — summary

## Root cause confirmed

This is exactly the canonical `wire()` name-override bug the `developing-cisternal-tools` skill describes. In `toy_cisternal/src/toy_cisternal/wire.py`, `wire()` calls `app.add_tool(callable_)` with a bare callable rather than a `ToyTool` carrying the registry's `name=` override. `ToyApp.add_tool` then falls back to inferring the tool name from the callable's raw `__name__`, silently dropping the intended name. The registry snapshot (`toy_cisternal/registry.py`) is correct throughout — only the transport-facing registration (`ToyApp._tools`) is wrong. This is a real defect in the shared `toy_cisternal` library, not something specific to toy-consumer.

## What was changed (toy-consumer only)

- File: `sandbox/toy_consumer/src/toy_consumer/app.py`
- Renamed the two wrapper functions so their Python `__name__` happens to match the intended `@tool(name=...)` value: `mcp_list_widgets_tool` → `list_widgets`, `mcp_get_widget_tool` → `get_widget`. Since `wire()`'s buggy fallback uses `fn.__name__`, this makes the fallback path accidentally produce the correct registered name.
- Added a substantial docstring comment above the functions explaining this is a workaround for the real defect in `toy_cisternal.wire.wire()`, naming the exact fix that belongs there (`app.add_tool` should receive `ToyTool(name=entry.name, fn=callable_)`, not a bare callable), noting it was deferred per explicit instruction/time pressure, and warning that any other consumer using the `mcp_x_tool` convention with a differing `name=` override will hit the identical failure until the upstream fix ships.

## toy_cisternal

Not touched at all — no edits, no local install changes, nothing in that repo was modified.

## Verification

- Before the change: `.venv/bin/python scripts/simulate_dashboard_call.py` reproduced the reported symptom exactly — `Tools actually exposed on the app: ['mcp_list_widgets_tool', 'mcp_get_widget_tool']` / `BUG REPRODUCED: 'list_widgets' is NOT among the exposed tools.`
- After the change: same script now reports `Tools actually exposed on the app: ['list_widgets', 'get_widget']` / `OK: list_widgets is callable.` — this asserts against `app.list_tools()`, the far/transport side of the registry↔app boundary, not just the registry-level view.
- Ran the existing toy-consumer test suite (`.venv/bin/python -m pytest -q`): 1 passed. Flagged that the existing test only checks `wire()`'s own return value (`_WIRED`), not `app.list_tools()` — a near-side assertion that would have passed even with the bug present.

## Not done (left for the user)

The change is unstaged in `toy_consumer`'s git repo. Not committed, per the standing rule to only commit when explicitly asked.
