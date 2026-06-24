---
session_id: 6df3bcc7
topic: M10.2 telemetry doctor JSON + exit codes
task_type: constrained-technical
winner: M10.2-K+A+F+C+E — build_doctor_report() structured checks[]; --json with schema_version; exit 0/1 from worst severity; --strict promotes warn→fail for CI/cutover
runner_up: M10.2-D tiered exit (0/1/2) without --strict
backlog_id: 2661
created_at: 2026-06-24T04:17:27+00:00
design: .praxia/docs/designs/260624_m10-2-telemetry-doctor-json-exit-codes_design.md
---

# Brainstorm: M10.2 telemetry doctor JSON + exit codes

## Problem Frame

Extend M10.1 `cisterna telemetry doctor` for **machine-readable output** and **actionable exit codes**. Primary consumers: **sibling-repo cutover scripts** (bathos/contemplex/xperiri/myxcel) and **cisterna CI preflight**.

**Fixed:** read-only inspect; no `init()` side effects; fastmcp-free CLI; reuse M10.1 probe helpers.

**MVP scope:** `--json` + exit codes + `--strict` only. Defer `--consumer` filter and #238 flaky-test bundle.

## Winner

**M10.2-K+A+F+C+E:** Refactor to `build_doctor_report()` returning structured `checks[]`; human and JSON serializers share one source. `--json` emits nested JSON with `schema_version: 1`. Exit code derived from worst check severity: `fail` → 1, else 0. Default lenient (warnings pass). `--strict` (or `CISTERNA_DOCTOR_STRICT=1`) promotes `warn` → `fail` for exit.

## Decision Log

- **[ACCEPT]** Structured checks[] + binary exit + `--strict` for CI
- **[REJECT]** Tiered exit 0/1/2 — unnecessary for MVP; scripts need pass/fail gate only
- **[REJECT]** Flat JSON — checks[] maps cleanly to severity aggregation

## Check severity table (MVP)

| Check id | Condition | Default status | Under `--strict` |
|----------|-----------|----------------|------------------|
| `telemetry_gate` | raw unset/empty OR zero known consumers enabled (invalid token counts as none) | `warn` | `fail` |
| `log_dir_writable` | resolved log dir fails write probe | `fail` | `fail` |
| `otlp_sdk` | `CISTERNA_OTLP_ENDPOINT` set but SDK missing | `fail` | `fail` |
| `pipeline` | `get_pipeline()` is None | `pass` (informational) | `pass` |
| `consumers.*` | per-consumer enabled/disabled | `pass` (informational) | `pass` |
| `job_context` | MYX_JOB_ID / BTH_TASK_ID present | `pass` (informational) | `pass` |

Exit code = `1` if any check has effective severity `fail` after `--strict` promotion; else `0`.

## Pre-mortem

**Failure:** CI ran doctor without `--strict`; telemetry off but exit 0; cutover shipped blind.  
**Mitigation:** runbook + help document CI must pass `--strict`; example in M10 runbook verification section.

**Failure:** JSON and human output drift after refactor.  
**Mitigation:** single `build_doctor_report()`; tests assert both serializers from same struct.

## Acceptance Criteria (rev1 — adversarially reconciled)

**AC-M10.2-0 (refactor):** Add `DoctorCheck` + `DoctorReport` dataclasses and `build_doctor_report() -> DoctorReport` in `probe/telemetry_doctor.py`. `format_doctor_report()` renders human text from it (M10.1 behavior parity).

**AC-M10.2-1 (--json):** `cisterna telemetry doctor --json` prints **JSON only** to stdout (no human lines) with:
- `schema_version: 1`
- `checks: [{id, status, effective_status, message, detail?}, ...]`
- `summary: {pass, warn, fail, strict: bool}`

**AC-M10.2-2 (exit default):** Without strict mode, exit `1` only when any check has `effective_status: fail`. Warnings do not affect exit.

**AC-M10.2-2b (exit wiring):** CLI calls `compute_doctor_exit_code(report, strict=...)` and raises `SystemExit(code)` (same pattern as `validate`).

**AC-M10.2-3 (--strict):** Strict mode when `--strict` **or** `CISTERNA_DOCTOR_STRICT` in `1`/`true`/`yes` (case-insensitive). Promotes `warn` → `fail` for `effective_status` / exit only; `status` field unchanged. `summary.strict` reflects active promotion.

**AC-M10.2-4 (severity rules):** Implement check table (rev1 `telemetry_gate` definition) using existing helpers.

**AC-M10.2-5 (CLI):** `telemetry_doctor(*, json: bool = False, strict: bool = False)`; lazy import preserved; default human output when `--json` absent.

**AC-M10.2-6 (fastmcp-free):** `import cisterna.cli` still does not import fastmcp at module level.

**AC-M10.2-7 (tests):** Extend `tests/test_cli_telemetry_doctor.py` — `build_doctor_report()` unit cases, JSON shape, exit 0/1 matrix, strict promotion, one CLI smoke per mode.

**AC-M10.2-8 (runbook):** M10 runbook adds CI/cutover examples (`--json --strict` and env-only strict).

**AC-M10.2-9 (baseline):** `uv run pytest -q` ≥ 386 passed.

## Reconciliation log (adversarial → rev1)

| Finding | Resolution |
|---------|------------|
| CH-001 telemetry_gate ambiguity | Warn only when raw empty or zero consumers enabled; `all` → pass |
| CH-002 exit wiring | `SystemExit(compute_doctor_exit_code(...))` |
| CH-003 JSON strict semantics | `effective_status` + `summary.strict` |
| CH-004 JSON stdout purity | `--json` emits JSON only |
| CH-005 strict precedence | Flag OR env |
| CH-006 OTLP protocol-only | Informational pass |
| CH-007 no --consumer | Runbook note |

## Acceptance Criteria (brainstorm draft — superseded by rev1 above)

## Deferred (post-M10.2)

- `--consumer` filter
- Tiered exit 0/1/2
- Auto-strict when `CI=true`
- #238 flaky test bundle

## INVEST

I: pass · N: pass · V: pass · E: pass · S: pass · T: pass
