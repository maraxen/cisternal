# Epic closeout audit — M3.3 (#2581)

**task_id:** `260624_epic-audit_m33`  
**closed_epic:** #2581 M3.3 — deferred rev2 export infrastructure  
**children:** M3.3a snapshot API, M3.3b WriterSink (#2587), M3.3c vendor commands (#2588), M3.3d L14 validate (#2589)  
**depends_on:** #2563 M3.2  
**next_milestone:** UNVERIFIED — no cisterna feature epic in backlog (M2.5 #2145/#2146 are external repos)  
**date:** 2026-06-24

## Shipped vs claimed

### M3.3a — snapshot API (5 ACs)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M33a-1 | PASS | `tests/test_registration_snapshot_public.py::test_snapshot_is_shallow_copy` |
| AC-M33a-2 | PASS | `tests/test_registration_snapshot_public.py::test_list_registries_excludes_unknown` |
| AC-M33a-3 | PASS | `tests/test_registration_snapshot_public.py::test_registry_assets_unknown_does_not_create_partition` |
| AC-M33a-4 | PASS | `tests/test_assets_spec.py::test_asset_spec_snapshot_coupling` |
| AC-M33a-5 | PASS | full pytest (296 green) |

### M3.3b — WriterSink (#2587, 3 ACs)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M33b-1 | PASS | `tests/test_export_write.py` (11 tests; `write_bundle` delegates to `FileWriterSink`) |
| AC-M33b-2 | PASS | `tests/test_export_sink.py` (3 MemoryWriterSink tests) |
| AC-M33b-3 | PASS | ruff clean; 296 pytest |

### M3.3c — vendor export_command (#2588, 3 ACs)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M33c-1 | PASS | `tests/test_assets_manifest_vendor_commands.py::test_vendor_export_commands_claude_and_cursor` |
| AC-M33c-2 | PASS | `tests/test_export_regression_m32.py` + `tests/test_cli_assets_validate.py` goldens |
| AC-M33c-3 | PASS | full pytest |

### M3.3d — L14 validate-only (#2589, 4 ACs)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M33d-1 | PASS | `tests/test_assets_manifest_extensions.py::test_manifest_minimal_unchanged_no_extension_warnings` |
| AC-M33d-2 | PASS | `tests/test_assets_manifest_extensions.py::test_workflow_missing_path_warns` |
| AC-M33d-3 | PASS | `tests/test_assets_manifest_extensions.py::test_snippet_invalid_scope_warns` |
| AC-M33d-4 | PASS | `tests/test_assets_manifest_extensions.py::test_validate_workflow_warning_exits_one` |

**Total:** 15/15 acceptance criteria cited across four children.

## Parallel wave verification

| Track | Module ownership | Merge conflict |
|-------|------------------|----------------|
| M3.3b | `export/sink.py`, `write.py` | None |
| M3.3c | `manifest_commands.py`, `manifest.py` import | None |
| M3.3d (sequential) | `manifest_extensions.py` | None |

Orchestration: concurrent subagents with **file ownership boundaries**; integrate on `main` before M3.3d.

## Git delta (M3.3 epic)

Commits `b51886f` → `2ca1792` (10 commits on M3.3b–d wave + M3.3a earlier):

- New: `registration.snapshot` API, `export/sink.py`, `manifest_commands.py`, `manifest_extensions.py`
- `write_bundle` → `FileWriterSink` delegation; `WriteResult` in `sink.py`, re-exported from `write.py`

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 296 passed; All checks passed!
```

Baseline at M3.2 closeout: 283 tests. Net +13 for M3.3 epic (incl. M3.3a +3, b +3, c +3, d +4).

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| Debt #238 flaky `test_raising_exporter_swallowed` | P3 | Pre-existing timing; defer |
| `WriteResult` moved to `sink.py` | doc | Public import path `cisterna.export.write.WriteResult` unchanged |
| No next cisterna epic registered | triage | Roadmap M4+ needs PI brainstorm |

## Rev2 deferred checklist

| Item | Status |
|------|--------|
| entry_point plugins | Shipped M3.2 #2563 |
| Antigravity | Shipped M3.1c #2559 |
| WriterSink | Shipped M3.3b #2587 |
| `registration.snapshot()` public API | Shipped M3.3a |
| vendor path-array export_command | Shipped M3.3c #2588 |
| L14 workflow/pipeline/snippet validate-only | Shipped M3.3d #2589 |

**M3.1 rev2 deferred scope: complete.**

## Verdict

**VERIFY: APPROVE** — M3.3 parent DoD satisfied (15/15 ACs). Route to **TRIAGE** for next milestone selection.
