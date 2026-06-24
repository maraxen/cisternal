# Epic closeout audit — M10.1 Telemetry doctor CLI (#2650)

**task_id:** `260624_epic-audit_m101`  
**closed_epic:** M10.1 telemetry doctor CLI  
**depends_on:** M10 operator runbook (#2647)  
**next_milestone:** M3.1 (#2326) PI-gated, or debt #238 flaky test  
**date:** 2026-06-24  
**verdict:** **APPROVE**

## Shipped vs claimed

> **Note:** M10.1 deliverables verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M10.1-0 | PASS | `telemetry_app` + `telemetry_doctor` in `cli.py`; logic in `probe/telemetry_doctor.py` |
| AC-M10.1-1 | PASS | Report: raw gate + 4 consumers via `consumer_telemetry_enabled()` |
| AC-M10.1-2 | PASS | `resolve_log_dir_from_env()` in `pipeline.py`; doctor prints `resolved` + `writable` |
| AC-M10.1-2b | PASS | `_job_context_line()` MYX > BTH precedence |
| AC-M10.1-3 | PASS | `otlp_sdk_available()`, `resolve_otlp_protocol()`, endpoint env |
| AC-M10.1-4 | PASS | `get_pipeline()` inactive label; no `init()` |
| AC-M10.1-5 | PASS | No top-level fastmcp in `cli.py`; `test_cli_assets` + doctor fastmcp test |
| AC-M10.1-6 | PASS | `--help` references `cisterna-telemetry.md` |
| AC-M10.1-7 | PASS | `tests/test_cli_telemetry_doctor.py` — 10 tests |
| AC-M10.1-8 | PASS | Runbook §Operator diagnostic |
| AC-M10.1-9 | PASS | `uv run pytest -q` → **386 passed**, 2 skipped (≥376) |

**Total:** 11/11 ACs satisfied on working tree.

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `src/cisterna/probe/telemetry_doctor.py` | M10.1 deliverable |
| `src/cisterna/cli.py` | `telemetry doctor` subcommand |
| `src/cisterna/telemetry/pipeline.py` | `resolve_log_dir_from_env()` extract |
| `tests/test_cli_telemetry_doctor.py` | Test suite |
| `.praxia/docs/runbooks/cisterna-telemetry.md` | Verification one-liner |
| `.praxia/docs/specs/260624_m10-1-telemetry-doctor-cli-for-cisterna.md` | Spec rev1 |
| `.praxia/docs/designs/260624_m10-1-telemetry-doctor-cli_design.md` | Adversarial design |

## Regression status

```
uv run pytest tests/test_cli_telemetry_doctor.py -q → 10 passed
uv run pytest -q && uv run ruff check . → 386 passed, 2 skipped; All checks passed!
```

No breaking API changes. Adversarial nits (CH-001..007) all landed.

## Pillar balance

| Pillar | Status post-M10.1 |
|--------|-------------------|
| Operator docs (M10) | Runbook + live `telemetry doctor` command |
| Export trust (M11–M11.1) | Unchanged |
| Telemetry adoption (M5–M9.2) | Doctor closes operator debug gap |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M10.1 artifacts uncommitted | P1 | Commit before treating epic shipped |
| `--json` / exit codes | P3 | M10.2 deferred |
| #238 flaky test | P3 | Not bundled |
| Runbook/doctor drift | P3 | Tests call shared helpers |

## Next epic candidates

| Candidate | Rationale |
|-----------|-----------|
| **#238** flaky test fix | Quick CI stability win |
| **#2326** M3.1 | PI-gated larger epic |
| **M10.2** | `--json` + misconfig exit codes |

## Verdict rationale

**APPROVE** — Read-only doctor mirrors M10 runbook effective config; adversarial architecture (probe module, shared log_dir helper, OTLP reuse) implemented; +10 tests; fastmcp-free CLI preserved.
