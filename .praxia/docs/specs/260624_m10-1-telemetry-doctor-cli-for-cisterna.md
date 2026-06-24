---
session_id: 522dad86
topic: M10.1 telemetry doctor CLI for cisterna — cisterna telemetry doctor subcommand printing effective CISTERNA_TELEMETRY, log dir, OTLP config, pipeline status. What should M10.1 optimize for: output format, consumer-specific checks, JSON mode, or bundling flaky test #238?
task_type: constrained-technical
winner: M10.1-A+B+C+D+E+I: `cisterna telemetry doctor` — human-readable report of CISTERNA_TELEMETRY consumer matrix, resolved log_dir, OTLP endpoint/protocol + otlp extra availability, pipeline active/idle status; help links runbook; lazy imports preserve fastmcp-free cli
created_at: 2026-06-24T03:29:47.894937+00:00
adversarial_verdict: ACCEPT_WITH_NITS
design: .praxia/docs/designs/260624_m10-1-telemetry-doctor-cli_design.md
---

# Brainstorm: M10.1 telemetry doctor CLI for cisterna — cisterna telemetry doctor subcommand printing effective CISTERNA_TELEMETRY, log dir, OTLP config, pipeline status. What should M10.1 optimize for: output format, consumer-specific checks, JSON mode, or bundling flaky test #238?

## Problem Frame
confirmed

## Idea Pool
- [ai] M10.1-A `cisterna telemetry doctor` top-level subcommand (telemetry_app under cyclopts App).
- [ai] M10.1-B Print effective CISTERNA_TELEMETRY + per-consumer enabled matrix (bathos/contemplex/xperiri/myxcel).
- [ai] M10.1-C Print resolved log_dir using same logic as init_pipeline (extract helper if needed).
- [ai] M10.1-D Print OTLP endpoint/protocol + whether otlp extra importable.
- [ai] M10.1-E Pipeline status: get_pipeline() None vs active, last export hint.
- [ai] M10.1-F `--json` structured output for scripts.
- [ai] M10.1-G `--consumer NAME` filters view to one consumer.
- [ai] M10.1-H Exit code 1 on warnings (missing otlp extra when endpoint set, unreadable log dir).
- [ai] M10.1-I Link runbook section in help text.
- [ai] M10.1-J Bundle #238 flaky test fix.
- [user] PEGS: Process = operator runs doctor before/after cutover. Events = mis-set env, OTLP without extra, wrong log dir. Goals = one command mirrors runbook effective config. States = pipeline may be uninitialized in CLI-only invocation. Components = cli.py new telemetry_app, telemetry_env, pipeline log resolution, otlp_exporter env reads. Constraints = fastmcp-free cli import path. Assumption = read-only inspect without calling init() side effects unless --probe flag.
- [user] converge. Winner candidate: M10.1-A+B+C+D+E — doctor subcommand with human table output covering telemetry gate matrix, resolved log dir, OTLP config, pipeline status. Defer --json and exit-code warnings to M10.2 unless trivial. Risk: duplicating env resolution — extract shared resolve_log_dir() from pipeline if needed.

## Decision Log
- [DEFER] M10.1-F --json mode: Defer M10.2 unless trivial
- [DEFER] M10.1-H exit code warnings: Defer M10.2
- [ACCEPT] M10.1-A+B+C+D+E+I doctor with table output: Core operator value; mirrors runbook

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem: doctor output drifted from runbook after env var rename; operators trusted stale table. Mitigation: AC cites source modules; doctor tests assert key strings match telemetry_env/pipeline behavior.

I: pass N: pass V: pass E: pass S: pass T: pass
**AI:** _not recorded_

## Acceptance Criteria (rev1 — adversarially reconciled)

**AC-M10.1-0 (command):** `cisterna telemetry doctor` under `telemetry` cyclopts sub-app; exit 0 on success. Report logic lives in `src/cisterna/probe/telemetry_doctor.py` (lazy-imported from `cli.py`).

**AC-M10.1-1 (consumer matrix):** Output lists raw `CISTERNA_TELEMETRY` (or `(unset)`) and `enabled`/`disabled` per consumer via `consumer_telemetry_enabled()` for `bathos`, `contemplex`, `xperiri`, `myxcel`.

**AC-M10.1-2 (log dir):** Extract `resolve_log_dir_from_env() -> Path` in `pipeline.py`; `init_pipeline` and doctor both use it. Doctor prints resolved path and `writable: yes|no` (mkdir+touch probe; **no** tempdir fallback in doctor).

**AC-M10.1-2b (job context, nit):** If `MYX_JOB_ID` or `BTH_TASK_ID` set, print effective task id source (per M10 runbook).

**AC-M10.1-3 (OTLP):** Use `otlp_sdk_available()`, `resolve_otlp_protocol()`, and raw `CISTERNA_OTLP_ENDPOINT`; print endpoint (or `(unset)`), protocol, `otlp_sdk: installed|missing`.

**AC-M10.1-4 (pipeline):** `get_pipeline()` via `cisterna.telemetry.pipeline` — print `active` or `inactive (expected unless cisterna.init() ran)`; no `init()` call.

**AC-M10.1-5 (fastmcp-free):** `import cisterna.cli` does not import fastmcp at module level; existing fastmcp-free tests pass.

**AC-M10.1-6 (help):** `--help` includes documentation reference to runbook path `.praxia/docs/runbooks/cisterna-telemetry.md` (no runtime file existence check).

**AC-M10.1-7 (tests):** `tests/test_cli_telemetry_doctor.py` — monkeypatch env; assert matrix, log dir, OTLP lines; calls same helpers as production code.

**AC-M10.1-8 (runbook link):** M10 runbook verification section adds `cisterna telemetry doctor` one-liner.

**AC-M10.1-9 (baseline):** `uv run pytest -q` ≥ 376 passed.

## Reconciliation log (adversarial → rev1)

| Finding | Resolution |
|---------|------------|
| CH-001 log_dir DRY | `resolve_log_dir_from_env()` |
| CH-002 cli bloat | `probe/telemetry_doctor.py` |
| CH-003 inactive pipeline | Explicit label in output |
| CH-004 OTLP DRY | Reuse otlp_exporter helpers |
| CH-005 help path | Doc reference only |
| CH-007 writable probe | AC-M10.1-2 writable line |

## Deferred (M10.2)
- `--json` output
- Non-zero exit on warnings
- `--consumer` filter
- #238 flaky test bundle
