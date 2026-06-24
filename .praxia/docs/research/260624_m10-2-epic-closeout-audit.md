# Epic closeout audit — M10.2 Telemetry doctor JSON + exit codes (#2661)

**task_id:** `260624_epic-audit_m102`  
**closed_epic:** M10.2 telemetry doctor JSON + exit codes  
**depends_on:** M10.1 telemetry doctor CLI (#2650)  
**date:** 2026-06-24  
**verdict:** **APPROVE**

## Shipped vs claimed

> **Note:** M10.2 deliverables verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M10.2-0 | PASS | `DoctorCheck`, `DoctorReport`, `build_doctor_report()`; `format_doctor_report()` renders from struct |
| AC-M10.2-1 | PASS | `--json` → `format_doctor_json()` with `schema_version: 1`, `checks[]`, `effective_status`, `summary.strict`; JSON-only stdout (`test_doctor_cli_json_only_stdout`) |
| AC-M10.2-2 | PASS | `compute_doctor_exit_code(strict=False)` — warn-only → 0 (`test_compute_exit_code_warn_only_default_lenient`) |
| AC-M10.2-2b | PASS | `cli.py` `raise SystemExit(compute_doctor_exit_code(...))` |
| AC-M10.2-3 | PASS | `--strict` + `CISTERNA_DOCTOR_STRICT`; promotion in `effective_check_status`; JSON `effective_status` unchanged `status` |
| AC-M10.2-4 | PASS | Severity table: `telemetry_gate`, `log_dir_writable`, `otlp_sdk`, `otlp_config`, `consumers.*`, `pipeline`, `job_context` |
| AC-M10.2-5 | PASS | `telemetry_doctor(json_output=..., strict=...)`; lazy import; human default |
| AC-M10.2-6 | PASS | `test_cli_still_fastmcp_free` |
| AC-M10.2-7 | PASS | `tests/test_cli_telemetry_doctor.py` — **22 tests** (+12 M10.2) |
| AC-M10.2-8 | PASS | Runbook §CI/cutover preflight + consumer env note |
| AC-M10.2-9 | PASS | `uv run pytest -q` → **398 passed**, 2 skipped (≥386) |

**Total:** 11/11 ACs satisfied on working tree.

### M10.1 regression (parity)

All 10 original M10.1 doctor tests still pass via shared `build_doctor_report()` / `format_doctor_report()` path.

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `src/cisterna/probe/telemetry_doctor.py` | M10.2 structured report + serializers |
| `src/cisterna/cli.py` | `--json`, `--strict`, exit wiring |
| `tests/test_cli_telemetry_doctor.py` | Extended suite |
| `.praxia/docs/runbooks/cisterna-telemetry.md` | CI/cutover examples |
| `.praxia/docs/specs/260624_m10-2-telemetry-doctor-json-exit-codes-e.md` | Spec rev1 |
| `.praxia/docs/designs/260624_m10-2-telemetry-doctor-json-exit-codes_design.md` | Adversarial design |
| `.praxia/docs/research/260624_m10-2-adversarial-review.md` | Adversarial memo |
| `src/cisterna/export/claude.py` | Unrelated #2662 comment (prior iteration) |
| `.praxia/loop_state.toml` | Loop bookkeeping |

## Regression status

```
uv run pytest tests/test_cli_telemetry_doctor.py -q → 22 passed
uv run pytest -q → 398 passed, 2 skipped
uv run ruff check src/cisterna/probe/telemetry_doctor.py src/cisterna/cli.py → clean
```

No breaking API changes. Adversarial nits CH-001..007 landed.

## Pillar balance

| Pillar | Status post-M10.2 |
|--------|-------------------|
| Operator UX (M10–M10.2) | Human doctor + scriptable JSON/exit gate |
| Export trust (M11–M11.1) | Unchanged |
| Telemetry adoption (M5–M9.2) | Cutover scripts can preflight via `--json --strict` |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M10.2 uncommitted | P1 | Commit before treating epic shipped |
| CI job not wired | P3 | Doctor is CLI-only; no workflow job yet — sibling repos opt-in |
| `log_dir_writable` / `otlp_sdk` fail exit | P3 | No dedicated CLI exit-1 test with monkeypatched fail paths (logic covered at unit level for gate) |
| `--consumer` filter | P3 | Deferred post-M10.2 |
| Tiered exit 0/1/2 | P3 | Deferred |
| #238 flaky test | P3 | Not bundled |

## Next epic candidates

| Candidate | Rationale |
|-----------|-----------|
| **Commit + triage** | Close M10.2 loop; pick next pillar or debt |
| **CI doctor job** | Optional advisory `export-dogfood.yml` preflight |
| **#238** flaky test | Quick CI stability |
| **M3.1 backlog cleanup** | Close stale #2660 duplicate |

## Verdict rationale

**APPROVE** — Single `build_doctor_report()` source feeds human + JSON serializers; exit codes derived from `effective_status` with `--strict` / env promotion; M10.1 parity preserved; +12 tests; runbook documents CI/cutover contract. Residual nits are documentation/CI wiring, not spec blockers.
