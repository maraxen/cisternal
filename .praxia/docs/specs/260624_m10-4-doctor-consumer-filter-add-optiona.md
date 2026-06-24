---
session_id: 16c2754b
topic: M10.4 doctor --consumer filter
task_type: constrained-technical
winner: M10.4-A+B+C+D+E+F — --consumer scopes telemetry_gate; exit 2 on invalid; JSON consumer_filter; human target line; CISTERNA_DOCTOR_CONSUMER env fallback
runner_up: M10.4-H --consumer all explicit alias
backlog_id: 2664
depends_on: M10.2 (#2661)
created_at: 2026-06-24T05:00:00+00:00
design: .praxia/docs/designs/260624_m10-4-doctor-consumer-filter_design.md
---

# Brainstorm: M10.4 doctor --consumer filter

## Problem Frame

Sibling-repo cutover scripts need `cisterna telemetry doctor --json --strict` to fail when **their** consumer is disabled, even if another consumer is enabled. M10.2 `telemetry_gate` passes when any consumer is on.

**Fixed:** Optional flag; default behavior unchanged; CI (`CISTERNA_TELEMETRY=all`, no `--consumer`) unchanged; reuse `consumer_telemetry_enabled()`.

## Winner

**M10.4-A+B+C+D+E+F:**
- `--consumer NAME` scopes `telemetry_gate` to `consumer_telemetry_enabled(NAME)`
- Unknown consumer → **exit 2** with enumerated known list
- `CISTERNA_DOCTOR_CONSUMER` env fallback when CLI flag omitted (flag wins if both)
- JSON `summary.consumer_filter: string | null`
- Human report: `target consumer: NAME` when filter active
- All `consumers.*` rows remain (informational)

## Gate semantics (with --consumer)

| Condition | Default status | `--strict` |
|-----------|----------------|------------|
| Target consumer enabled | `pass` | `pass` |
| Target consumer disabled | `warn` | `fail` |
| `CISTERNA_TELEMETRY` unset | `warn` (target disabled) | `fail` |

## Pre-mortem

- Script uses wrong `--consumer` for repo → gate message must show raw env + target enabled state
- Typo `myxcel` → exit 2 lists known consumers

## Acceptance Criteria (rev1)

**AC-M10.4-0 (scope):** Extend `build_doctor_report(consumer: str | None = None)`; add `consumer_filter: str | None` to `DoctorReport`; no CI workflow change.

**AC-M10.4-0b (resolve):** `resolve_doctor_consumer(*, cli_consumer: str | None) -> str | None` — CLI flag overrides `CISTERNA_DOCTOR_CONSUMER` env; empty string → no filter; unknown name → `ValueError` with known list (CLI maps to exit 2).

**AC-M10.4-1 (--consumer):** `cisterna telemetry doctor --consumer bathos` scopes `telemetry_gate` to `consumer_telemetry_enabled("bathos")`.

**AC-M10.4-1b (gate message):** Filtered gate message includes raw `CISTERNA_TELEMETRY` and `target <name>: enabled|disabled` (e.g. `raw=contemplex; target bathos: disabled`).

**AC-M10.4-1c (case):** Consumer names matched case-insensitively; stored canonical lowercase in `consumer_filter`.

**AC-M10.4-2 (default):** Without `--consumer` / env, M10.2 any-consumer `telemetry_gate` unchanged.

**AC-M10.4-3 (invalid):** Unknown consumer → exit **2** before report emission; stderr lists `bathos|contemplex|xperiri|myxcel` (no JSON body).

**AC-M10.4-4 (env):** `CISTERNA_DOCTOR_CONSUMER` applies when `--consumer` omitted; CLI flag overrides env.

**AC-M10.4-5 (JSON):** `summary.consumer_filter` set when filter active; gate `detail` includes `target_consumer`.

**AC-M10.4-6 (human):** Filter active → report includes `target consumer: <name>` under gate section.

**AC-M10.4-7 (tests):** Extend `test_cli_telemetry_doctor.py` — scoped gate pass/fail, invalid exit 2, env fallback, JSON field.

**AC-M10.4-8 (runbook):** Cutover example: `uv run cisterna telemetry doctor --consumer contemplex --json --strict`.

**AC-M10.4-9 (baseline):** `uv run pytest -q` ≥ 401 passed.

## Reconciliation log (adversarial → rev1)

| Finding | Resolution |
|---------|------------|
| CH-001 gate message ambiguity | AC-M10.4-1b raw + target line |
| CH-002 DoctorReport field | AC-M10.4-0b consumer_filter |
| CH-003 case sensitivity | AC-M10.4-1c lowercase canonical |
| CH-004 empty string | resolve treats as no filter |
| CH-005 invalid + --json | exit 2 pre-report, stderr only |

## Deferred

- `--consumer all` explicit alias
- Filter `consumers.*` rows from output (only gate scoped for MVP)

## INVEST

I: pass · N: pass · V: pass · E: pass · S: pass · T: pass
