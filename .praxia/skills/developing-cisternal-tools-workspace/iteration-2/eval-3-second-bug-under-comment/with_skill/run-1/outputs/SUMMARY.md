# Two-bug dashboard report — root cause + fix (with skill)

## Two distinct root causes, both real, compounding into what looked like one confusing story

**Root cause 1 (cisternal-side, causes report A):** `toy_cisternal/wire.py`'s `wire()` passed a bare callable to `ToyApp.add_tool()` instead of a `ToyTool` carrying the registry's `name=` override. `ToyApp.add_tool()` fell back to inferring the name from the callable's own `__name__` instead of the registered name. The canonical `maraxen/cisternal#6` shape.

**Root cause 2 (consumer-side, causes report B):** `toy_cisternal/registry.py`'s `register()` used a plain dict assignment with no collision check. toy-consumer's `app.py` had `mcp_get_widget_tool` and `mcp_delete_widget_tool` both decorated `@tool(name="get_widget")`; the second decoration silently overwrote the first. A code comment claimed this was a deliberate "soft-delete alias" feature. Debunked by grepping both repos for "alias"/"soft-delete"/"overwrite"/"collision" and reading every existing test — zero hits, nothing implements or documents such semantics. Unguarded dict overwrite dressed up with a plausible comment.

One or two issues: two distinct defects. Once bug 1 alone is fixed, bug 2's symptom (get_widget running delete's handler) still surfaces, so both needed fixing.

## What was changed

- `toy_cisternal/src/toy_cisternal/wire.py`: `wire()` now calls `app.add_tool(ToyTool(name=entry.name, fn=callable_))`.
- `toy_cisternal/src/toy_cisternal/registry.py`: `register()` now raises `ValueError` on a genuine name collision between two distinct functions instead of silently overwriting (additive hardening, not a substitute for the consumer-side fix).
- `toy_cisternal/tests/{test_wire.py,test_registry.py}`: added tests asserting against `app.list_tools()` (far side of the boundary) and a duplicate-registration-raises test.
- `toy_consumer/src/toy_consumer/app.py`: removed the false "soft-delete alias" comment, gave `delete_widget` its own registered name, added it to `wire(expected=[...])`.
- `toy_consumer/pyproject.toml`: dependency floor bumped to `>=0.1.1`.
- `toy_consumer/tests/test_app.py`: added tests asserting against `app.list_tools()`, that `get_widget` returns fetch semantics, and that `delete_widget` is its own distinct tool.

## Fail-then-pass verification

`git stash`'d the fixes, ran the new cisternal tests — both failed with the exact expected symptoms. `git stash pop`'d, re-ran — all 6 cisternal tests passed. On the consumer side, ran the new tests against the still-installed 0.1.0 cisternal — 3 of 4 failed with the exact reported symptoms. After upgrading to 0.1.1, all 4 passed.

## Full suites

Both repos' entire test suites (6 tests in toy-cisternal, 4 in toy-consumer) run per-file per the local WSL2 suite guard. All green post-fix.

## Release handling

Two-commit pattern: fix commit `2e4a77e` merged to `main` (`de92a41`), then a separate `chore(release): bump toy-cisternal to 0.1.1` commit (`1674410`). Tagged `v0.1.1`, `uv build`, wheel copied into the local index. No GitHub remote in this sandbox, so no `--admin` bypass needed.

## Closing the loop in toy-consumer

Bumped the dependency floor, `uv pip install --find-links <index> --no-index toy-cisternal==0.1.1` to upgrade the venv from the real published wheel — confirmed no `[tool.uv.sources]` override was added, `importlib.metadata.version("toy-cisternal")` reports `0.1.1` post-upgrade. Fixed the consumer's collision bug, reran its full suite, merged to `main`.

## End-to-end confirmation

On `main` in both repos (clean working trees), with the venv resolving the real published `toy-cisternal==0.1.1`: both `simulate_dashboard_call.py` and `simulate_get_widget_confusion.py` report OK — both bug reports resolved.
