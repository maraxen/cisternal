# Epic closeout audit — M10 Operator Runbook (#2647)

**task_id:** `260624_epic-audit_m10`  
**closed_epic:** M10 Operator runbook — `CISTERNA_TELEMETRY` + OTLP env contract  
**depends_on:** M5–M9.2 telemetry adoption (all four consumer cutovers shipped)  
**next_milestone:** M10.1 `cisterna telemetry doctor` CLI (runner-up) or export hardening II  
**date:** 2026-06-24  
**verdict:** **APPROVE**

## Shipped vs claimed

> **Note:** M10 deliverables verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M10-0 | PASS | `.praxia/docs/runbooks/cisterna-telemetry.md` exists |
| AC-M10-0b | PASS | `uv run pytest -q` → **359 passed**, 2 skipped |

### Env contract (AC-M10-1 … AC-M10-4)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M10-1 | PASS | Runbook §`CISTERNA_TELEMETRY` — unset, `all`/`1`/`true`/`yes`, per-consumer names; cites `telemetry_env.py` |
| AC-M10-2 | PASS | Runbook §OTLP — `CISTERNA_OTLP_ENDPOINT`, `CISTERNA_OTLP_PROTOCOL`, `[otlp]` extra, ports 4317/4318 |
| AC-M10-3 | PASS | Runbook §JSONL log directory — `CISTERNA_LOG_DIR` > `BTH_LOG_DIR` > `CTXP_LOG_DIR` > `~/.cisterna/logs` |
| AC-M10-4 | PASS | Runbook §`job_span` — `MYX_JOB_ID` > `BTH_TASK_ID`, `MYX_RUN_UUID` / `BTH_RUN_UUID` |

### Per-consumer (AC-M10-5 … AC-M10-6)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M10-5 | PASS | Four subsections with flag + `telemetry_bridge.py` paths (bathos, contemplex, xperiri, myxcel) |
| AC-M10-6 | PASS | myxcel row marked **async** `traced_tool`; others sync |

### Verification & troubleshooting (AC-M10-7 … AC-M10-9)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M10-7 | PASS | Copy-paste `tests/shadow/` + four `test_*_telemetry_cutover.py` commands |
| AC-M10-8 | PASS | OTLP smoke: `test_otlp_http.py -m integration`, collector fixture, advisory CI job noted |
| AC-M10-9 | PASS | ≥3 troubleshooting entries (unset telemetry, SDK missing, protocol/port, shadow failures) |

**Total:** 10/10 ACs satisfied on working tree.

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `.praxia/docs/runbooks/cisterna-telemetry.md` | M10 deliverable |
| `.praxia/docs/specs/260624_m10-operator-runbook-for-cisterna-docume.md` | Brainstorm spec + AC matrix |
| `.praxia/loop_state.toml` | Loop CLOSE / M10 complete flags |

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 359 passed, 2 skipped; All checks passed!

uv run pytest tests/shadow/ -q → 12 passed
```

No product code changed — test count unchanged vs M9.2 baseline.

## Pillar balance

| Pillar | Status post-M10 |
|--------|-------------------|
| Telemetry adoption (M5–M9.2) | Four adapters + four repo cutovers |
| Observability egress (M7–M7.1) | OTLP gRPC/HTTP documented in runbook |
| Operator docs (M10) | Single authoritative runbook closes #2647 |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M10 artifacts uncommitted | P1 | Commit runbook + spec + loop_state before treating epic shipped |
| Runbook drift vs code | P3 | No CI doc-check; pre-mortem mitigated by source-of-truth table + pytest commands |
| M10.1 doctor CLI | P3 | Deferred runner-up; would reduce operator grep-of-source |
| Orphan spec `260623_cisterna-m3-1-2326-file-manifest-assetso.md` | P4 | Untracked; unrelated to M10 |

## VERIFY checklist

| Check | Result |
|-------|--------|
| `ci_green` | PASS |
| `research_memo` | PASS (this file) |
| `loop_priorities` | PENDING — update `[epics]` with `m10_operator_runbook_complete` on commit |

## Followups for TRIAGE

1. **Commit** M10 docs + loop_state (user-gated).
2. **Backlog #2647** — mark `completed` after commit.
3. **Next epic candidates:** M10.1 doctor CLI · export hardening II · multi-emitter goldens.
4. **Disarm** 30m loop heartbeat if manual control preferred.
