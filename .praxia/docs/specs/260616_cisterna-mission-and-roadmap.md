---
title: Cisterna — Mission, Recon Findings & Telemetry-First Roadmap
date: 2026-06-16
status: active
---

# Cisterna

Shared Python library providing two pillars to the (Python) ecosystem —
xperiri, bathos, maraxiom, aminx, contemplex, jaxlint, myxcel, xtrax:

1. **Telemetry** for FastMCP servers and Cyclopts CLIs (OpenTelemetry-based).
2. **Agent-asset export** — one canonical asset → many surfaces.

praxia is the only Rust project; its existing Rust export engine informs (but
does not constrain) cisterna's Python design.

## Decisions (2026-06-16)

- **Asset export:** native Python implementation to start; a praxia (Rust)
  backend may be added later behind a `Writer`/backend abstraction.
- **First milestone:** telemetry first (FastMCP + Cyclopts).

## Ecosystem facts (recon 2026-06-16)

| Dimension | Count | Detail |
|---|---|---|
| MCP servers | 5 (58 tools) | bathos 22, myxcel 19, contemplex 9, jaxlint 4, xperiri 4 — mixed FastMCP v2/v3 |
| CLIs | 8 (156+ cmds) | 100% Typer; bth 41, mrx 39, myxcel 34, aminx 20, ctxp 10, jaxlint 9, xpr 3; zero Cyclopts |
| Skills | 71 | praxia 55, jaxlint 11, others 5 |
| Agents/roles | 60+ | praxia roles 40, maraxiom 4, plain agents 7 |
| OTel adoption | 0 | all bespoke JSONL / Postgres / Parquet today |

## Telemetry reference surface (bathos canonical)

- `init_telemetry(level, log_dir, max_bytes=10485760, backup_count=5)` — idempotent, must-not-raise.
- `event(event_name, **fields)` — lazy-init, never raises.
- `span(name, **fields)` ctx manager — emits `<name>.start` / `<name>.end` with span_id, duration_ms (float), ok, exc_type/exc_msg/traceback.
- Contextvars: bathos `run_uuid`/`mcp_request_id`/`task_id`; contemplex `request_id`/`session_id`/`phase`.
- JSONL record base fields: ts, level, pid, tid, host, surface, event, msg + conditional contextvars + custom fields.
- File scheme: `<log_dir>/events.<hostname>.<pid>.jsonl`, RotatingFileHandler(max_bytes, backup_count).

## FastMCP version matrix

| Project | fastmcp pin | middleware? |
|---|---|---|
| bathos | >=3.3.1 | yes (v3 `add_middleware`) |
| xperiri | >=3.0,<4 | yes |
| contemplex | >=2.0,<3.0 | no (decorator only) |
| myxcel | >=0.4 | unclear |

## Roadmap

- **M1 — Telemetry core:** span/event model + contextvars + JSONL exporter (default). Adopt bathos-compatible schema.
- **M2 — FastMCP integration:** `TelemetryMiddleware` (v3) + `traced_tool` decorator (v2). Prove in one v3 server + contemplex.
- **M3 — Cyclopts/CLI integration:** `@app.meta.default` launcher wrapper + Typer-compat shim. OTLP + Postgres exporters optional.
- **M4 — Assets IR + adapters (native Python):** bundle + claude adapter + validate.
- **M5 — Remaining adapters + registry; evaluate praxia-Rust backend bridge.**
