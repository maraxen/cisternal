# Epic closeout audit — M7 OTLP Egress (#2627)

**task_id:** `260624_epic-audit_m7`  
**closed_epic:** M7 OTLP Egress — optional trace export  
**depends_on:** M6 (#2624) Bathos Telemetry Cutover  
**next_milestone:** #2145 XpeririAdapter · #2146 MyxcelAdapter · M7.1 HTTP OTLP / collector CI  
**date:** 2026-06-24

## Shipped vs claimed

> **Note:** M7 implementation verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M7-0 | PASS | `uv run pytest -q` → **320 passed** (baseline 314 post-M6) |
| AC-M7-0b | PASS (nuanced) | `tests/test_otlp_exporter.py::test_sdk_lazy_until_otlp_init` — SDK lazy until `init()` with endpoint; see nit below |

### M7.0 — import guard

| AC | Status | Evidence |
|----|--------|----------|
| Lazy SDK load | PASS | `src/cisterna/telemetry/otlp_exporter.py` — SDK imports inside `OtlpExporter.__init__` only |
| API-only top-level | PASS | `opentelemetry.trace` (API dep) at module level; not `opentelemetry.sdk` |

### M7.1 — OtlpExporter + env gate

| AC | Status | Evidence |
|----|--------|----------|
| AC-M7-1a | PASS | `test_jsonl_only_when_otlp_endpoint_unset` |
| AC-M7-1b | PASS | `test_dual_export_when_otlp_endpoint_set` |
| AC-M7-1c | PASS | `test_raising_otlp_exporter_does_not_break_jsonl` |
| AC-M7-1d | PASS | `test_call_pair_exports_span_with_tool_attribute` — span name + `tool` attribute |
| Pipeline hook | PASS | `src/cisterna/telemetry/pipeline.py` — `maybe_create_otlp_exporter()` after JsonlExporter |

### M7.2 — tests

| AC | Status | Evidence |
|----|--------|----------|
| AC-M7-2a | PASS | In-memory `InMemorySpanExporter` in `test_call_pair_exports_span_with_tool_attribute` |
| AC-M7-2b | PASS | `test_heartbeat_dropped_from_otlp` — heartbeats dropped from OTLP |

**Total:** 9/9 parent ACs satisfied on working tree.

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `src/cisterna/telemetry/otlp_exporter.py` | OtlpExporter + `maybe_create_otlp_exporter()` |
| `src/cisterna/telemetry/pipeline.py` | Env-gated OTLP append |
| `tests/test_otlp_exporter.py` | 6 AC tests |
| `pyproject.toml` / `uv.lock` | OTEL SDK in dev group |
| `.praxia/docs/specs/260624_m7-otlp-egress-buildable-spec-rev1.md` | Buildable spec |

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 320 passed; All checks passed!

uv run pytest tests/shadow/ -q → 4 passed
```

Net **+6** tests vs M6 closeout (314 → 320).

## Pillar balance

| Pillar | Status post-M7 |
|--------|----------------|
| Export trust (M4) | Unchanged |
| Telemetry adoption (M5–M6) | contemplex + bathos cutover; JSONL default |
| Observability egress (M7) | Optional OTLP gRPC when `CISTERNA_OTLP_ENDPOINT` set |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M7 not committed to `main` | P1 | Commit before treating epic as shipped |
| AC-M7-0b wording vs dev deps | P3 | Spec says `import opentelemetry.sdk` fails without `[otlp]`; dev group installs SDK for tests — lazy-load is the real contract |
| M7.1 HTTP OTLP + collector CI | deferred | Brainstorm runner-up M7-H steelman |
| #2145 / #2146 external adapters | open | Next TRIAGE candidates |
| `consumer_telemetry_enabled` unrelated to OTLP | info | Separate env (`CISTERNA_TELEMETRY` vs `CISTERNA_OTLP_ENDPOINT`) |

## Adversarial verdict (condensed)

**ACCEPT** — scope matches buildable spec; no API freeze violations; never-raise preserved via pipeline isolation + OtlpExporter try/except.

**Nits:**
1. Commit M7 delta to `main`.
2. Clarify AC-M7-0b in spec as lazy-load, not package absence (dev CI has SDK).

## Verdict

**VERIFY: APPROVE** — M7 parent DoD satisfied (9/9 ACs) on working tree. Route to **TRIAGE** for #2145/#2146 or M7.1 after commit.
