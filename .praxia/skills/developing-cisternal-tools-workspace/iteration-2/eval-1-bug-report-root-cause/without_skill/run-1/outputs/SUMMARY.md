# Dashboard `list_widgets` bug — root cause + fix (baseline, no skill)

## Root cause

In `toy_cisternal/src/toy_cisternal/wire.py`, `wire()` called `app.add_tool(callable_)` with a bare callable instead of a `ToyTool`. `ToyApp.add_tool()`'s fallback path for bare callables registers the tool under `tool_or_fn.__name__` (the Python function name, e.g. `mcp_list_widgets_tool`) rather than the registry's `name=` override (`list_widgets`) that `@tool(name=...)` had recorded. This is a reproduction of the real `maraxen/cisternal#6` bug shape.

Why toy-consumer's own tests passed despite the live bug: both `toy_cisternal/tests/test_wire.py` and `toy_consumer/tests/test_app.py` only asserted on `wire()`'s return value (`wired_names`, always correct), never on what the transport (`app.list_tools()`) actually exposes. The return value and the transport's registered names had silently diverged.

## Fix

`wire.py` line 59 now does `app.add_tool(ToyTool(name=entry.name, fn=callable_))`, passing the registry name explicitly instead of relying on the callable's `__name__` fallback.

## Regression tests added

- `toy_cisternal/tests/test_wire.py::test_wired_tool_exposed_under_registered_name_not_fn_name` — asserts `app.list_tools()` names match the registry override, not the wrapper's `__name__`.
- `toy_consumer/tests/test_app.py::test_expected_tools_actually_callable_on_transport` — asserts on `app.list_tools()` directly, not on `wire()`'s return value.

Both verified conceptually to fail against the pre-fix code path (the whole bug was that the pre-existing tests couldn't catch this) and pass cleanly against the fix.

## Test runs

`toy_cisternal`'s suite: 5 passed. `toy_consumer`'s suite: 2 passed. Ran as targeted/per-file runs rather than a bare whole-suite invocation, per the local jax-mem-guard hook contract.

## Version bump / release

Bumped `toy_cisternal` to `0.1.1`, committed the fix, tagged `v0.1.1`, built the wheel/sdist, copied it into the local index (`toy_cisternal_index/`) alongside the old 0.1.0 wheel. Bumped `toy_consumer`'s dependency floor to `toy-cisternal>=0.1.1` and committed. Also added `.gitignore` and removed previously-tracked `__pycache__`/`.pyc` files in both repos as incidental cleanup.

## Consumer-side end-to-end verification

Reinstalled `toy-cisternal==0.1.1` into `toy_consumer/.venv` from the local index (`--find-links ../toy_cisternal_index --no-index`). Re-ran `scripts/simulate_dashboard_call.py` — output changed from `BUG REPRODUCED` to `Tools actually exposed on the app: ['list_widgets', 'get_widget']` / `OK: list_widgets is callable.` Re-ran both test suites one final time after the reinstall (5/5 and 2/2 passing).
