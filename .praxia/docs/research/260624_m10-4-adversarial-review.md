# Adversarial review — M10.4 Doctor --consumer filter (#2664)

**date:** 2026-06-24  
**spec:** `.praxia/docs/specs/260624_m10-4-doctor-consumer-filter-add-optiona.md` (rev1)  
**design:** `.praxia/docs/designs/260624_m10-4-doctor-consumer-filter_design.md`  
**depends_on:** M10.2 (#2661)  
**verdict:** **ACCEPT_WITH_NITS**

## Summary

M10.4 is a narrow extension: optional `--consumer` / `CISTERNA_DOCTOR_CONSUMER` scopes `telemetry_gate` only. Default path and CI dogfood step unchanged. Blast radius: `telemetry_doctor.py`, `cli.py`, tests, runbook.

## Findings → reconciliation

| ID | Sev | Challenger | Synthesis |
|----|-----|------------|-----------|
| **CH-001** | MAJOR | Gate message must disambiguate `CISTERNA_TELEMETRY=contemplex` + `--consumer bathos` | **Fixed** — AC-M10.4-1b: message includes raw env + `target <name>: enabled\|disabled` |
| **CH-002** | MAJOR | `DoctorReport` lacks `consumer_filter` — JSON/human drift risk | **Fixed** — AC-M10.4-0b: `consumer_filter: str \| None` on report dataclass |
| **CH-003** | MINOR | Case sensitivity `--consumer Bathos` | **Fixed** — normalize to lowercase; match `_KNOWN_CONSUMERS` |
| **CH-004** | MINOR | Empty `--consumer ""` or empty env | **Fixed** — treat as no filter (same as omitted) |
| **CH-005** | MINOR | Invalid consumer with `--json` — JSON or stderr? | **Fixed** — exit 2 **before** report; stderr only (matches `validate` unknown surface) |
| **CH-006** | INFO | `_KNOWN_CONSUMERS` only in doctor module | **Nit** — keep tuple in doctor; validate against it in `resolve_doctor_consumer()` |
| **CH-007** | INFO | `CISTERNA_TELEMETRY=all` + `--consumer bathos` | **Pass** — `consumer_telemetry_enabled` returns true; gate passes |

## Scope check

| In | Out |
|----|-----|
| `resolve_doctor_consumer()` | CI workflow change |
| `build_doctor_report(consumer=)` gate branch | Filter `consumers.*` rows from output |
| CLI `--consumer` + env | `--consumer all` alias |
| exit 2 invalid name | schema_version bump |

## Edge-case matrix (implementation)

| CISTERNA_TELEMETRY | --consumer | telemetry_gate (default) | strict |
|--------------------|------------|--------------------------|--------|
| unset | bathos | warn | fail |
| bathos | bathos | pass | pass |
| contemplex | bathos | warn | fail |
| all | bathos | pass | pass |
| bogus | (none) | warn (M10.2) | fail |
| bathos | (none) | pass (any on) | pass |

## Residual risks (accepted)

1. Operators must pass matching `--consumer` for their repo — runbook example mitigates.
2. Informational `consumers.*` rows may look contradictory when filter targets disabled consumer — message on gate line clarifies.

## Gate

**ACCEPT_WITH_NITS** — proceed to **`go m10.4`**.
