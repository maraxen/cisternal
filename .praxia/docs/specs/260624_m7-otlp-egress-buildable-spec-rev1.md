---
title: M7 OTLP Egress — buildable spec rev1
brainstorm: .praxia/docs/specs/260623_m7-milestone-for-cisterna-after-m6-batho.md
task_id: 260624_m7-otlp-egress
depends_on_epic: 2624
---

# M7 OTLP Egress — buildable spec (rev1)

**Goal:** Optional OTLP gRPC trace export when `CISTERNA_OTLP_ENDPOINT` is set; JSONL remains default and always fan-outs when pipeline initializes.

## Out of scope

- HTTP OTLP (M7.1 candidate)
- OTLP logs/metrics
- Consumer repo cutover (bathos/contemplex unchanged)
- #2145 / #2146 external adapters (M8+)
- Docker otel-collector CI job (M7.1 advisory)
- Export hardening / Rust bridge

## Child packages

| ID | Deliverable | depends_on |
|----|-------------|------------|
| **M7.0** | Import guard — `import cisterna` without `[otlp]` does not load sdk | — |
| **M7.1** | `OtlpExporter` + `init_pipeline` env gate | M7.0 |
| **M7.2** | In-memory SpanExporter tests | M7.1 |

## AC matrix

### Epic DoD

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M7-0** | M7 merged | `uv run pytest -q` (default env, no otlp extra) | ≥314 tests green |
| **AC-M7-0b** | Default install | `import cisterna` without `[otlp]` | `import opentelemetry.sdk` fails |

### M7.1 — OtlpExporter

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M7-1a** | `CISTERNA_OTLP_ENDPOINT` unset | `cisterna.init()` | Pipeline has JsonlExporter only |
| **AC-M7-1b** | Endpoint set + `uv sync --extra otlp` | `cisterna.init()` | Pipeline fans out to JsonlExporter **and** OtlpExporter |
| **AC-M7-1c** | OtlpExporter raises on export | `emit_event("mcp.call_start", ...)` | Caller never raises; JSONL exporter still receives record |
| **AC-M7-1d** | `mcp.call_start` + `mcp.call_end` pair | OTLP export | Span with `tool` attribute and duration |

### M7.2 — Tests

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M7-2a** | In-memory `SpanExporter` in test | Tool traced via `traced_tool` | ≥1 exported span name matches tool |
| **AC-M7-2b** | Heartbeat events | OTLP path | Dropped or exported as span event (document choice) |

## Span mapping (decision)

- `mcp.call_start` + `mcp.call_end` → single span (linked by `request_id` in Record.fields)
- `mcp.tool_error` → span with error status
- `*.start` / `*.end` span pairs → OTLP spans
- `telemetry.heartbeat` → **drop** from OTLP (JSONL only)

## Env contract

| Variable | Required | Default |
|----------|----------|---------|
| `CISTERNA_OTLP_ENDPOINT` | no | unset → OTLP disabled |
| `OTEL_SERVICE_NAME` | no | `cisterna` |

Install: `uv sync --extra otlp` (sdk + grpc exporter already in pyproject).

## Pre-mortem mitigations

| Risk | Mitigation |
|------|------------|
| Record≠Span conflation | Pair start/end; drop heartbeats |
| SDK on default install | Lazy import inside OtlpExporter only |
| Blocking export | BatchSpanProcessor on background thread (same isolation as JSONL listener) |
