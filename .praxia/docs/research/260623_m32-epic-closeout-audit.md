# Epic closeout audit — M3.2 (#2563)

**task_id:** `260623_epic-audit_m32`  
**closed_epic:** #2563 M3.2 — entry_point emitter plugins + dispatch registry  
**depends_on:** #2326 M3.1 (completed)  
**next_milestone:** M3.3 deferred rev2 infrastructure (parent backlog TBD at triage)  
**date:** 2026-06-23

## Shipped vs claimed

| AC | Status | Evidence |
|----|--------|----------|
| AC-M32-1 | PASS | `tests/test_export_registry.py::test_entry_points_register_four_builtins` |
| AC-M32-2 | PASS | `tests/test_export_registry.py::test_list_emitter_surfaces_sorted` |
| AC-M32-3 | PASS | `tests/test_export_registry.py::test_get_emitter_claude_matches_direct_ctor` |
| AC-M32-4 | PASS | `tests/test_export_registry.py::test_get_emitter_unknown_returns_none` |
| AC-M32-5 | PASS | `tests/test_export_registry.py::test_get_emitter_broken_factory_returns_none` |
| AC-M32-6 | PASS | `tests/test_cli_assets_validate.py::{test_validate_names_only_golden,test_validate_cursor_golden,test_validate_copilot_golden,test_validate_antigravity_golden}` |
| AC-M32-7 | PASS | `tests/test_export_regression_m32.py::test_all_golden_digests_unchanged_after_m32` |

**Total:** 7/7 acceptance criteria cited.

## Locked decisions verification

| ID | Claim | Evidence |
|----|-------|----------|
| L29 | entry-points in pyproject | `pyproject.toml:36-40` |
| L30 | factory callables | `registry.py:20-33` (`claude_factory`, etc.) |
| L31 | unified dispatch | `validate_golden.py:emit_surface_files` → `get_emitter`; `cli.py:207-227` |
| L32 | kwargs filter claude-only | `registry.py:85-87` |
| L33 | fail-closed lookup | `registry.py:82-94`; CLI exit 2 at `cli.py:210-212, 222-224` |
| L34 | list_emitter_surfaces | `registry.py:73-75`; exported `export/__init__.py` |
| L35 | no public register_emitter | `export/__init__.py` — only `get_emitter`, `list_emitter_surfaces` |

## Git delta (M3.2 execution)

Commits `df5849d` → `d976855` (6 commits):

- +~217 lines product + tests
- New: `src/cisterna/export/registry.py`
- Refactored: `validate_golden.py`, `cli.py`, `export/__init__.py`
- Entry points: `pyproject.toml` `[project.entry-points."cisterna.emitters"]`

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 283 passed; All checks passed!
```

Baseline at M3.1 closeout: 275 tests. Net +8 tests for M3.2 (+2 audit hygiene).

## Audit hygiene gaps (OPTION-B)

| Item | Severity | Resolution |
|------|----------|------------|
| No CLI test for unknown surface exit 2 | **resolved** | `test_export_unknown_surface_exits_two`, `test_validate_unknown_surface_exits_two` |
| Spec table `_claude_factory` vs `claude_factory` | doc drift | Fix spec rev1 table |

## Open risks for next milestone (M3.3 deferred)

1. **Scope balloon** — rev2 deferred bundles WriterSink, `registration.snapshot()` public API, vendor path-array commands, L14 validate-only parsing. Register parent only; split children at triage.
2. **Third-party emitters** — entry_points can override built-ins (`registry.py:69`); document conflict policy before community plugins.
3. **M2.5 adapters** — #2145/#2146 remain open in external repos (not blocking cisterna).

## Debt / lessons

- No open debt items.
- Entry_point registry pattern validated; golden gate effective for dispatch refactors.

## Verdict

**VERIFY: APPROVE** — M3.2 DoD satisfied. Route to **TRIAGE** for M3.3 deferred infrastructure.
