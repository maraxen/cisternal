# Dashboard `list_widgets` fix (baseline, no skill) — summary

## Root cause

The reported "list_widgets not found" symptom is a real defect in `toy_cisternal`, the shared library, not in toy-consumer. `toy_cisternal/src/toy_cisternal/wire.py`'s `wire()` calls `app.add_tool(callable_)` with a bare callable instead of wrapping it in a `ToyTool(name=entry.name, fn=...)`. `ToyApp.add_tool()`'s fallback path then infers the registered name from `fn.__name__` instead of honoring the registry's `name=` override — so any consumer using `@tool(name=...)` with a differently-named wrapper function gets silently re-registered under its raw Python function name. This affects every project depending on `toy_cisternal`, not just toy-consumer.

## What was changed

Only `toy_consumer/src/toy_consumer/app.py`. Renamed `mcp_list_widgets_tool` → `list_widgets` and `mcp_get_widget_tool` → `get_widget` so the function's own `__name__` matches its `@tool(name=...)` override, working around the fallback-path bug rather than fixing it.

## toy_cisternal

Not touched at all — confirmed clean (`git status --short` returns nothing) after the fix.

## Trace left

Added a block comment at the top of `app.py` labeled `WORKAROUND (2026-07-23, not a real fix)` that: names the exact bug location (`ToyApp.add_tool`'s fallback branch in `wire.py`), states this is a shared-library defect affecting every `toy_cisternal` consumer that uses `name=` overrides, and says `toy_cisternal` still needs the real fix. Flagged in the agent's final summary as well so it isn't buried in a code comment alone.

## Verification

Ran `.venv/bin/python scripts/simulate_dashboard_call.py` before and after — before: `BUG REPRODUCED: 'list_widgets' is NOT among the exposed tools`; after: `Tools actually exposed on the app: ['list_widgets', 'get_widget']` / `OK: list_widgets is callable.` Also ran `toy_consumer`'s existing test file (`tests/test_app.py`) — 1 passed.
