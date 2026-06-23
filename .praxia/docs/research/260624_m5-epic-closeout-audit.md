# Epic closeout audit — M5 Telemetry Adoption (#2609)

**task_id:** `260623_epic-audit_m5`  
**closed_epic:** #2609 M5 Telemetry Adoption — shadow CI, cutover gate, contemplex smoke  
**children:** M5.0 (#2610), M5.1a (#2611), M5.1b (#2612); follow-up M5.2 (#2613 open)  
**depends_on:** #2597 M4 Export Trust  
**next_milestone:** #2613 contemplex repo cutover (external) · UNVERIFIED M6 topic  
**date:** 2026-06-24

## Shipped vs claimed

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M5-0 | PASS | `uv run pytest -q` → 311 passed; M4 validate loops exit 0 |
| AC-M5-0b | PASS | `tests/test_telemetry_import_guard.py::test_import_cisterna_does_not_start_pipeline` |

### M5.0 — import guard (#2610)

| AC | Status | Evidence |
|----|--------|----------|
| (implicit) | PASS | `src/cisterna/telemetry/pipeline.py` — `get_pipeline()` None until `cisterna.init()` |

### M5.1a — shadow in CI (#2611)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M5-1a | PASS | `tests/shadow/test_bathos_shadow.py` (4 tests in shadow suite) |
| AC-M5-1b | PASS | `tests/shadow/test_contemplex_shadow.py` |
| AC-M5-1c | PASS | `.github/workflows/export-dogfood.yml` L19–20 before example install |

**Note:** Shadow harness shipped M1; M5 wired CI only (design discovery).

### M5.1b — cutover gate (#2612)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M5-2a | PASS | `tests/test_contemplex_telemetry_cutover.py::test_consumer_telemetry_enabled_contemplex_flag` |
| AC-M5-2b | PASS | `tests/test_contemplex_telemetry_cutover.py::test_consumer_telemetry_disabled_when_unset` |
| AC-M5-2c | PASS | `tests/test_contemplex_telemetry_cutover.py::test_traced_tool_emits_when_cutover_enabled` |
| API | PASS | `src/cisterna/probe/telemetry_env.py::consumer_telemetry_enabled` |

### M5.2 — external follow-up (#2613)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M5-3 | PASS (registered) | Backlog #2613 open — contemplex repo cutover PR; intentionally deferred |

**Total:** 10/10 parent ACs satisfied (#2613 registered, not required complete for epic close).

## Git delta (M5 epic)

Commit `c9e3561` on `main`:

- New: `src/cisterna/probe/telemetry_env.py`
- New: `tests/test_telemetry_import_guard.py`, `tests/test_contemplex_telemetry_cutover.py`
- Changed: `.github/workflows/export-dogfood.yml` (+shadow step)

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 311 passed; All checks passed!

uv run pytest tests/shadow/ -q → 4 passed
M4 validate (4 surfaces, self-manifest) → exit 0
```

Baseline at M4 closeout: 307 tests. Net **+4** for M5 epic.

**Flaky:** `tests/test_core.py::TestNeverRaise::test_raising_exporter_swallowed` failed once, passed on immediate retry (debt #238).

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| #2613 contemplex repo cutover | P2 | Gate exists in cisterna; production cutover needs sibling repo |
| Debt #238 flaky never-raise test | P3 | Pre-existing; unrelated to M5 |
| `consumer_telemetry_enabled` not yet called from contemplex | P2 | By design until #2613 |
| Bathos production cutover | deferred | Shadow parity only per brainstorm |

## Pillar balance

| Pillar | Status post-M5 |
|--------|----------------|
| Export trust (M4) | CI green; unchanged goldens |
| Telemetry adoption | Gate + shadow CI + smoke; contemplex cutover pending #2613 |

## Verdict

**VERIFY: APPROVE** — M5 parent DoD satisfied (10/10 ACs). Route to **TRIAGE** for #2613 or M6 selection.
