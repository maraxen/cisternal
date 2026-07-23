# Dashboard `list_widgets` bug — root cause + fix (with skill)

## Root cause

Canonical "wire() name-override bug" (`maraxen/cisternal#6` shape), reproduced deliberately in `toy_cisternal` for rehearsal. In `toy_cisternal/src/toy_cisternal/wire.py`, `wire()` called `app.add_tool(callable_)` with a bare callable, not a `ToyTool` carrying the registry's `name=` override. `ToyApp.add_tool()`'s fallback path then inferred the tool name from the callable's own `__name__` (`mcp_list_widgets_tool`) instead of the registered name (`list_widgets`). The registry and `wire()`'s own return value both correctly recorded `"list_widgets"` the whole time — only the actual transport registration was wrong, which is exactly why `toy_consumer`'s existing test (asserting only against `_WIRED`) passed despite the live bug.

## Fix (upstream, root cause)

`toy_cisternal/src/toy_cisternal/wire.py` — changed `app.add_tool(callable_)` to `app.add_tool(ToyTool(name=entry.name, fn=callable_))` inside `wire()`.

## Regression tests

Added `test_wire_registers_tool_under_registry_name_on_the_app` to `toy_cisternal/tests/test_wire.py`, asserting against `app.list_tools()` (the far side), not `wire()`'s return value. Verified fail→pass: failed against pre-fix code (`AssertionError: assert 'list_widgets' in ['mcp_list_widgets_tool']`), passed against the fix. Also added a matching consumer-side test, `test_expected_tools_actually_exposed_on_the_app`, to `toy_consumer/tests/test_app.py`, since the existing consumer test had the identical near-side-only blind spot.

## Test suite

Ran toy_cisternal's full suite (5 tests) — all pass. Ran toy_consumer's full suite (2 tests) — all pass.

## Version bump / release

Two-commit pattern: fix landed as its own commit (`70f5ef1`) on branch `fix/wire-name-override-bug`, merged into `main` (`3f96592`), then a separate `chore(release): 0.1.1` commit (`38a9a5a`) bumped `pyproject.toml` and tagged `v0.1.1`. No GitHub remote in this sandbox, so "publish" was simulated by `uv build` + copying the wheel/sdist into the local package index.

## Consumer-side verification

Bumped `toy_consumer/pyproject.toml`'s floor to `toy-cisternal>=0.1.1`, deleted the stale lockfile, resolved the real published 0.1.1 wheel via `uv lock`/`uv sync --find-links <index>` (confirmed via `toy_cisternal-0.1.1.dist-info`, no editable/path override), reran the full consumer suite (2/2 passing), and re-ran the repro script — now prints `Tools actually exposed on the app: ['list_widgets', 'get_widget']` / `OK: list_widgets is callable.`

Both repos ended in a clean committed state (`.gitignore` added to each).
