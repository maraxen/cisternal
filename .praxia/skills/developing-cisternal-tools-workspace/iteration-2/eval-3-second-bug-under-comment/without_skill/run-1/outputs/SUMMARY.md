# Two-bug dashboard report — root cause + fix (baseline, no skill)

## Two independent root causes, not one

1. **`list_widgets` "tool not found"** — a library bug in `toy_cisternal/src/toy_cisternal/wire.py`. `wire()` called `app.add_tool(callable_)` with a bare function instead of a `ToyTool(name=entry.name, fn=callable_)`. `ToyApp.add_tool()`'s fallback path then inferred the exposed name from the callable's own `__name__` rather than the registry's `name=` override. The `maraxen/cisternal#6` bug shape.

2. **`get_widget` returning `{'deleted': True}`** — a copy-paste bug local to `toy_consumer/src/toy_consumer/app.py`: `mcp_delete_widget_tool` was decorated `@tool(name="get_widget")`, the same registered name as the real `get_widget` handler. `registry.register()` has no alias/merge semantics — a plain dict write, so the second registration silently clobbered the first. A comment above it claimed this was an intentional "soft-delete alias" feature.

## Verifying (not trusting) the "soft-delete alias" comment

Checked `toy_cisternal/src/toy_cisternal/registry.py` (no alias/duplicate-name handling exists), grepped both toy repos and the real `cisterna` repo for any spec, design doc, or code path implementing such a feature, and found none. The comment was unsubstantiated self-justification for a bug, not a real feature.

## Fixes

- `toy_cisternal/src/toy_cisternal/wire.py`: `add_tool(ToyTool(name=entry.name, fn=callable_))` instead of a bare callable. Bumped `toy_cisternal` to 0.1.1, committed, tagged `v0.1.1`, rebuilt the wheel, copied into the local index.
- `toy_consumer/src/toy_consumer/app.py`: gave `delete_widget` its own registered name (`@tool(name="delete_widget")`), removed the false comment, added it to `wire()`'s `expected=[...]` list. Bumped the `toy-cisternal` dependency floor to `>=0.1.1` and reinstalled from the local index.

## Regression tests added

- `toy_cisternal/tests/test_wire.py`: two new tests asserting `app.list_tools()` exposes the registered name, not `fn.__name__`.
- `toy_consumer/tests/test_app.py`: `test_expected_tools_actually_exposed_on_transport` (checks all three tool names) and `test_get_widget_and_delete_widget_are_distinct_tools` (asserts fetch vs. delete semantics).

## Test runs

All 6 toy_cisternal tests and all 3 toy_consumer tests pass, run per-file per the local test-suite guard.

## End-to-end verification

Re-ran both reproduction scripts after the fix: `simulate_dashboard_call.py` → all three tools exposed, list_widgets callable. `simulate_get_widget_confusion.py` → get_widget returns fetch semantics, no `deleted` key. Both bugs fixed and confirmed independently.
