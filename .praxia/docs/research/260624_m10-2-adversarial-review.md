# Adversarial review — M10.2 Telemetry doctor JSON + exit codes (#2661)

**date:** 2026-06-24  
**spec:** `.praxia/docs/specs/260624_m10-2-telemetry-doctor-json-exit-codes-e.md` (rev1)  
**design:** `.praxia/docs/designs/260624_m10-2-telemetry-doctor-json-exit-codes_design.md`  
**verdict:** **ACCEPT_WITH_NITS**

## Summary

M10.2 is a low-blast-radius extension of M10.1: refactor to structured checks, add JSON serializer and exit-code helper, wire CLI flags. Architecture reuses existing probe helpers and cyclopts `SystemExit` patterns from `validate`.

## Findings closed in rev1

| Severity | Count | Key fixes |
|----------|-------|-----------|
| MAJOR | 3 | `telemetry_gate` definition, `SystemExit` wiring, JSON `effective_status` |
| MINOR | 4 | JSON-only stdout, strict env OR flag, OTLP protocol-only nit, runbook consumer note |
| INFO | 2 | Writable probe accepted; parity test scope |

## Residual nits (non-blocking)

1. **No `--consumer` filter** — cutover scripts must set `CISTERNA_TELEMETRY` to the target consumer (or `all`) before running doctor; document in runbook.
2. **Invalid telemetry token** — `CISTERNA_TELEMETRY=bogus` warns under default, fails under strict; acceptable for MVP.
3. **Tiered exit deferred** — scripts needing warn-without-fail must parse JSON `summary.warn`, not exit code.

## Gate

**ACCEPT_WITH_NITS** — proceed to implementation (`go m10.2`).
