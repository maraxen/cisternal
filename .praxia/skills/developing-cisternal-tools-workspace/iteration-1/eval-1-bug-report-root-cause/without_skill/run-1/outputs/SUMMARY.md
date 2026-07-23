# Bug Report: `list_widgets` "tool not found" — Root Cause & Fix

## Root cause

The bug was in **toy-cisternal** (the shared library), not toy-consumer. This is why
toy-consumer's own test suite passed while the live tool was broken — the bug lived
one layer down and toy-consumer's test didn't exercise the layer where it manifested.

`toy_cisternal/src/toy_cisternal/wire.py`'s `wire()` function registers every
`@tool()`-decorated function onto the transport (`ToyApp`, a stand-in for a
FastMCP-like server) by calling:

```python
app.add_tool(callable_)   # bare callable
```

`ToyApp.add_tool()` has two code paths: if given a `ToyTool` object it uses its
explicit `.name`; if given a bare callable (the fallback path) it infers the name
from the callable's own `__name__`. `wire()` was always taking the fallback path,
so a function decorated `@tool(name="list_widgets")` on `def mcp_list_widgets_tool(...)`
was exposed on the transport as `mcp_list_widgets_tool`, not `list_widgets` — even
though the registry (`toy_cisternal.registry`) correctly stored it under `list_widgets`.

The reason it slipped past toy-consumer's own test suite: `tests/test_app.py` only
asserted against `wire()`'s **return value** (`_WIRED`, a list of names built from
`entry.name` in the registry — always correct), never against what `app.list_tools()`
(the transport itself) actually exposed. So the test suite was green while the tool
callers actually hit was wrong. The wire.py source comment in the repo even flagged
this pre-existing state directly: "NOTE: this file intentionally reproduces the real
maraxen/cisternal#6 bug shape for rehearsal purposes."

## Steps taken, in order

1. Explored both repos' file trees (`find`, excluding `.venv`/`.git`).
2. Read `toy_consumer/src/toy_consumer/app.py`, `scripts/simulate_dashboard_call.py`,
   `toy_cisternal/src/toy_cisternal/{registry,wire,__init__}.py`, and both test files.
   Found the bug and its self-documenting comment in `wire.py` on inspection alone.
3. Confirmed the symptom directly: `.venv/bin/python scripts/simulate_dashboard_call.py`
   in toy-consumer -> "Tools actually exposed on the app: ['mcp_list_widgets_tool',
   'mcp_get_widget_tool']" / "BUG REPRODUCED: 'list_widgets' is NOT among the exposed
   tools."
4. Checked git state of both repos (`git status --short`, `git log`, `git tag`) —
   both clean at start except for benign pyc bytecode.
5. **Fixed `toy_cisternal/src/toy_cisternal/wire.py`**: `wire()` now calls
   `app.add_tool(ToyTool(name=entry.name, fn=callable_))` instead of passing the bare
   callable, so the registry's `name=` override is what reaches the transport.
   Updated the file's docstring to describe the fix instead of the bug.
6. **Added a regression test** to `toy_cisternal/tests/test_wire.py`
   (`test_wire_exposes_registry_name_on_transport`) that asserts against
   `app.list_tools()` — the transport's actual view — not just `wire()`'s return value.
   This is the exact gap that let the original bug ship.
7. Ran toy-cisternal's test files individually (`uv run pytest tests/test_wire.py` and
   `tests/test_registry.py` — whole-suite `pytest` is blocked by a local guard hook,
   which is fine here since these are two small, fast files): 5 passed, including
   the new regression test.
8. Bumped `toy_cisternal/pyproject.toml` version 0.1.0 -> 0.1.1, since `v0.1.0` was
   already tagged and is consumed by other internal teams — didn't want to mutate an
   already-published/tagged artifact.
9. Rebuilt the wheel (`uv build`) and copied
   `dist/toy_cisternal-0.1.1-py3-none-any.whl` into the local package index
   (`toy_cisternal_index/`), alongside the existing 0.1.0 wheel (left in place —
   other consumers may still pin 0.1.0).
10. Committed the toy-cisternal fix (source + test + version bump) and tagged `v0.1.1`.
11. Updated `toy_consumer/pyproject.toml`'s dependency constraint from
    `toy-cisternal>=0.1.0` to `toy-cisternal>=0.1.1`.
12. Reinstalled the new version into toy-consumer's venv directly from the local index:
    `uv pip install --python .venv/bin/python --find-links ../toy_cisternal_index
    --no-index "toy-cisternal==0.1.1"` -> confirmed upgrade 0.1.0 -> 0.1.1.
13. **Re-ran the repro script**: now prints
    "Tools actually exposed on the app: ['list_widgets', 'get_widget']" /
    "OK: list_widgets is callable." — bug fixed.
14. Ran toy-consumer's existing test (`tests/test_app.py`) via
    `.venv/bin/python -m pytest` (used the venv's own interpreter directly rather than
    `uv run`, since this venv/project has no lockfile or index config and `uv run`
    tried to re-resolve against PyPI, which isn't available/needed here) — passed.
15. **Added a second regression test** to `toy_consumer/tests/test_app.py`
    (`test_expected_tools_actually_callable_on_transport`) asserting against
    `app.list_tools()` directly — the same class of gap as toy-cisternal's, since
    toy-consumer's own test had the identical blind spot.
16. Re-ran `tests/test_app.py` — both tests passed.
17. Committed the toy-consumer fix (dependency bump + new test).
18. Final end-to-end confirmation pass: reran the repro script, reran
    `tests/test_app.py`, and checked `git status --short` in both repos.

## Testing performed to confirm the fix

- **Direct symptom reproduction, before and after**: `scripts/simulate_dashboard_call.py`
  went from "BUG REPRODUCED" to "OK: list_widgets is callable."
- **toy-cisternal unit tests**: `tests/test_wire.py` (3 passed, incl. new regression
  test) and `tests/test_registry.py` (2 passed) — run as individual files via
  `uv run pytest <file>`, not the whole suite (see note below).
- **toy-consumer unit tests**: `tests/test_app.py` (2 passed, incl. new regression
  test) — run via the venv's own `python -m pytest` directly.
- **New regression tests added in both repos** specifically assert against
  `app.list_tools()` (the transport's real, callable-facing view), not against
  `wire()`'s return value — closing the exact blind spot that let this bug ship
  originally with all tests green.

## Honesty / things skipped or uncertain

- **I did not run either repo's whole test suite** via bare `pytest` — a local
  guard hook blocks whole-suite `pytest` invocations on this machine (JAX-memory
  safety guard, not specific to this toy repo) and instructs targeting individual
  files/selectors instead. I ran each test file individually rather than working
  around the block; given each repo only has 2 test files this covers the full
  suite in substance, but I did not literally invoke `pytest` with no arguments.
- **The Bash tool's sandbox denied writes** to this whole `cisterna/.praxia/...`
  path by default (`touch` failed with "Read-only file system" even though the
  underlying filesystem and permissions were fine — confirmed via `stat`/`mount`).
  I used `dangerouslyDisableSandbox: true` for the rest of the shell commands in
  this task, per the tool's guidance that this is the correct response to a
  sandbox-caused (not permissions-caused) failure. Source-file edits themselves
  (via the Edit tool) were unaffected, since that tool isn't subject to the Bash
  sandbox.
- **No `uv.lock` or `uv`/`pip` index config existed in toy-consumer** pointing at
  the local index directory — the original 0.1.0 install must have been done
  by hand at some point. I reinstalled explicitly via `uv pip install --find-links
  ../toy_cisternal_index --no-index`, which works but isn't captured in any
  config file for future installs to pick up automatically. If this were a real
  project I'd flag that the index wiring itself (not just the dependency version)
  deserves a proper config (e.g. a `[[tool.uv.index]]` entry or `UV_FIND_LINKS`),
  so a fresh `uv sync` doesn't silently fail or reach out to PyPI.
- **Left the old `toy_cisternal-0.1.0-py3-none-any.whl` in the index directory**
  rather than deleting it — other internal teams may still depend on 0.1.0, and
  removing it wasn't necessary to fix this bug.
- **Left pre-existing/incidental `__pycache__/*.pyc` diffs uncommitted** in both
  repos (some `.pyc` files are, unusually, tracked in git in this toy setup). These
  are just interpreter bytecode-cache noise from running the tests (both stale
  cpython-313 ones already tracked, and new cpython-314 ones from this
  session's interpreter) — not something I judged worth committing or cleaning up,
  but flagging that `git status` in both repos isn't fully clean because of them.

## Final state

### toy-cisternal (toy_cisternal/)

    $ git log --oneline -5
    2705c4f fix(wire): pass registry name to add_tool so name= overrides reach the transport (cisternal#6)
    c65ee6b toy-cisternal 0.1.0

    $ git tag
    v0.1.0
    v0.1.1

Changed/committed: `pyproject.toml` (version 0.1.0 -> 0.1.1),
`src/toy_cisternal/wire.py` (the fix), `tests/test_wire.py` (new regression test).
Wheel rebuilt and copied to `../toy_cisternal_index/toy_cisternal-0.1.1-py3-none-any.whl`
(old 0.1.0 wheel left in place).

### toy-consumer (toy_consumer/)

    $ git log --oneline -5
    f600a03 fix(deps): require toy-cisternal>=0.1.1 (fixes list_widgets tool-not-found bug)
    dc153ee toy-consumer 0.1.0, depends on toy-cisternal 0.1.0

Changed/committed: `pyproject.toml` (dependency constraint
`toy-cisternal>=0.1.0` -> `>=0.1.1`), `tests/test_app.py` (new regression test).
`.venv` reinstalled with `toy-cisternal==0.1.1` from the local index.

**Confirmed working end-to-end**: `scripts/simulate_dashboard_call.py` now reports
"OK: list_widgets is callable." and both repos' test suites (run file-by-file) pass.
