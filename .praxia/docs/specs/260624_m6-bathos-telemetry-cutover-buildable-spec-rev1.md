---
title: M6 Bathos Telemetry Cutover — buildable spec rev1
brainstorm: .praxia/docs/specs/260623_m6-milestone-for-cisterna-after-m5-telem.md
task_id: 260624_m6-bathos-telemetry-cutover
depends_on_epic: 2609
---

# M6 Bathos Telemetry Cutover — buildable spec (rev1)

**Goal:** Second consumer cutover — bathos repo routes telemetry through cisterna when `CISTERNA_TELEMETRY=bathos`; cisterna gate tests + existing shadow parity remain green.

## Out of scope

- OTLP exporter (M7 candidate)
- Export hardening / Rust bridge
- Myxcel / Xperiri adapters (#2145, #2146)
- Replacing bathos `traced_tool` error-shaping (keep MCP envelope logic)

## Child packages

| ID | Deliverable | Repo |
|----|-------------|------|
| **M6.1a** | `consumer_telemetry_enabled("bathos")` smoke tests | cisterna |
| **M6.1b** | `telemetry_bridge` + `event`/`init`/`span` routing | bathos |
| **M6.2** | Bridge tests + MCP `init_server_telemetry` | bathos |

## AC matrix

### Epic DoD

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M6-0** | M6 merged | `uv run pytest -q` (cisterna) | ≥314 tests green |
| **AC-M6-0b** | Shadow gate | `uv run pytest tests/shadow/ -q` | Pass (unchanged) |

### M6.1a — Cisterna gate

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M6-2a** | `CISTERNA_TELEMETRY=bathos` | `consumer_telemetry_enabled("bathos")` | `True` |
| **AC-M6-2b** | env unset | `consumer_telemetry_enabled("bathos")` | `False` |
| **AC-M6-2c** | Flag set + `init()` + `traced_tool(BathosAdapter())` | Tool call | `ShadowExporter` captures ≥1 `mcp.call_start` |

### M6.1b — Bathos bridge

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M6-3a** | Flag unset | `init_telemetry(log_dir=tmp)` + `event()` | Legacy JSONL file created |
| **AC-M6-3b** | `CISTERNA_TELEMETRY=bathos` | `init_server_telemetry` + `emit_via_cisterna` | `cisterna.get_pipeline()` non-None; JSONL written |
| **AC-M6-3c** | `bth-mcp` entry | `mcp_server()` | Calls `init_server_telemetry()` |

## Cutover mechanism

- `bathos.telemetry_bridge` mirrors contemplex M5.2 pattern
- `init_telemetry` / `event` / `span` delegate to cisterna when flag set
- Contextvars synced best-effort before `emit_event`
- Job spans use `cisterna.span()` when cutover enabled (no separate job-span spike required for MCP path)
