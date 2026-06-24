---
session_id: d188d205
topic: M10 operator runbook for cisterna — document CISTERNA_TELEMETRY cutover per consumer (bathos, contemplex, xperiri, myxcel), CISTERNA_OTLP_ENDPOINT/PROTOCOL, JSONL log paths, shadow parity gate, and troubleshooting. All adapters and repo cutovers now shipped (#2647).
task_type: constrained-technical
winner: M10-A Single operator runbook in .praxia/docs/runbooks/cisterna-telemetry.md with env matrix, per-consumer cutover checklist, shadow/gate verification, OTLP smoke, JSONL query appendix, troubleshooting
created_at: 2026-06-24T00:08:12.554342+00:00
---

# Brainstorm: M10 operator runbook for cisterna — document CISTERNA_TELEMETRY cutover per consumer (bathos, contemplex, xperiri, myxcel), CISTERNA_OTLP_ENDPOINT/PROTOCOL, JSONL log paths, shadow parity gate, and troubleshooting. All adapters and repo cutovers now shipped (#2647).

## Problem Frame
Confirm. Fixed: docs-only in cisterna repo; never-raise telemetry invariant; CISTERNA_TELEMETRY opt-in per consumer; shadow tests are verification gate; JSONL remains default sink; OTLP optional via extras. Negotiable: single file vs split docs; optional doctor CLI; depth of JSONL query examples; whether to include docker-compose collector snippet.

## Idea Pool
- [user] M10-A Single operator runbook in .praxia/docs/runbooks/cisterna-telemetry.md: env matrix, cutover checklist per consumer, shadow gate command, OTLP smoke, troubleshooting
- [user] source
- [user] ai
- [user] M10-B Split runbooks: cisterna core + per-consumer one-pagers in sibling repos — more maintenance, out of M10 fixed scope
- [user] M10-C JSONL query cookbook only (duckdb/jq) without cutover env — incomplete
- [user] M10-D Runbook + cisterna CLI `telemetry doctor` printing effective config — code scope creep for docs epic
- [user] M10-E Link-only from loop_priorities.toml — too thin
- [user] M10-F Decision tree: JSONL-only vs OTLP vs dual; CISTERNA_TELEMETRY=all vs per-consumer; job_span env MYX_JOB_ID > BTH_TASK_ID
- [user] PEGS: Processes — operator enables CISTERNA_TELEMETRY → consumer init_server_telemetry → traced_tool/job_span → JSONL fan-out + optional OTLP. Events — mcp.call_*, job.start/end, export records. Goals — verify shadow parity before prod; query logs; wire Grafana/Tempo. States — telemetry off (default), JSONL-only, JSONL+OTLP. Constraints — never-raise; grpc:4317 vs http:4318; log_dir precedence CISTERNA_LOG_DIR > BTH_LOG_DIR > CTXP_LOG_DIR > ~/.cisterna/logs. Assumptions — sibling repos already have telemetry_bridge.py. Ready to converge: M10-A single runbook with M10-F decision tree sections; defer M10-D doctor CLI to M10.1.

## Decision Log
- [ACCEPT] M10-A Single operator runbook: Docs-only matches fixed constraint; centralizes env contract post M5-M9.2; includes verification commands from existing test suite; decision tree from M10-F folded in. Doctor CLI deferred to M10.1.
- [DEFER] M10-D doctor CLI: Useful but violates docs-only fixed constraint for M10; backlog as M10.1 follow-up.

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem: 6 months later operators still grep source because runbook listed wrong default ports after M7.1 HTTP addition; sibling cutover steps diverged (myxcel async traced_tool not documented); no one runs shadow tests before deploy. Mitigations baked into spec: env table generated from code comments cross-check; per-consumer section links to actual telemetry_bridge.py paths; mandatory verification block with exact uv run pytest commands; OTLP grpc/http port callout box.
**AI:** _not recorded_

## Acceptance Criteria

**Deliverable:** `.praxia/docs/runbooks/cisterna-telemetry.md` (docs-only; closes backlog #2647)

### Epic DoD

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M10-0** | Runbook merged | `test -f .praxia/docs/runbooks/cisterna-telemetry.md` | File exists |
| **AC-M10-0b** | Full suite | `uv run pytest -q` | ≥359 tests green (no regressions) |

### Env contract section

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M10-1** | Runbook env table | Cross-check `src/cisterna/probe/telemetry_env.py` | Documents `CISTERNA_TELEMETRY` values: unset, `all`/`1`/`true`/`yes`, per-consumer names |
| **AC-M10-2** | OTLP section | Cross-check `src/cisterna/telemetry/otlp_exporter.py` | Documents `CISTERNA_OTLP_ENDPOINT`, `CISTERNA_OTLP_PROTOCOL` (`grpc` default port 4317, `http` port 4318), `[otlp]` extra |
| **AC-M10-3** | Log dir section | Cross-check `src/cisterna/telemetry/pipeline.py` | Documents precedence: `CISTERNA_LOG_DIR` > `BTH_LOG_DIR` > `CTXP_LOG_DIR` > `~/.cisterna/logs` |
| **AC-M10-4** | Job spans section | Cross-check `src/cisterna/telemetry/span.py` | Documents `job_span` env: `MYX_JOB_ID` > `BTH_TASK_ID`, `MYX_RUN_UUID` |

### Per-consumer cutover section

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M10-5** | Consumer table | Operator reads runbook | One subsection each for bathos, contemplex, xperiri, myxcel with `CISTERNA_TELEMETRY=<name>` example and sibling `telemetry_bridge.py` path |
| **AC-M10-6** | Myxcel note | Async MCP tools | Runbook states myxcel uses async `traced_tool`; xperiri/bathos/contemplex sync |

### Verification & troubleshooting

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M10-7** | Verification block | Operator copies commands | Documents `uv run pytest tests/shadow/ -q` and per-consumer gate tests (`test_*_telemetry_cutover.py`) |
| **AC-M10-8** | OTLP smoke | CI reference | Documents `tests/test_otlp_http.py -m integration` + `tests/fixtures/otel-collector-config.yaml`; references blocking `otlp-collector` job (promoted M7.2; see [CI promotion status](260623_ci-promotion-status.md)) |
| **AC-M10-9** | Troubleshooting | Common failures | ≥3 entries: OTLP SDK missing, wrong protocol/port, telemetry disabled (unset `CISTERNA_TELEMETRY`) |

### Deferred (M10.1)

- `cisterna telemetry doctor` CLI (runner-up M10-D)
