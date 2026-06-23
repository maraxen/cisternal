---
title: M5 Telemetry Adoption — buildable spec rev1
brainstorm: .praxia/docs/specs/260623_hmw-select-cisterna-m5-milestone-after-m.md
design: .praxia/docs/designs/260623_m5-telemetry-adoption_design.md
depends_on_epic: 2597
task_id: 260623_m5-telemetry-adoption
adversarial_verdict: ACCEPT_WITH_NITS
---

# M5 Telemetry Adoption — buildable spec (rev1)

**Goal:** Measurable telemetry adoption path — shadow parity in CI, import safety for export dogfood, contemplex cutover gate in cisterna. Bathos cutover deferred.

**Note:** Shadow harness **already exists** at `tests/shadow/` (M1). M5.1a = CI wiring + drift gate, not greenfield harness.

## Out of scope

- Bathos production cutover (shadow only)
- OTLP exporter epic
- Contemplex **repo** code changes (separate follow-up item M5.2)

## Child packages

| ID | Deliverable | depends_on |
|----|-------------|------------|
| **M5.0** | Import guard | — |
| **M5.1a** | Shadow in export-dogfood CI | — |
| **M5.1b** | `CISTERNA_TELEMETRY` gate + smoke | M5.0 |
| **M5.2** | Contemplex repo cutover backlog stub | M5.1b |

## AC matrix

### Epic DoD

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-0** | M5 merged | `uv run pytest -q` + M4 validate steps | ≥307 tests green |
| **AC-M5-0b** | Fresh interpreter | `import cisterna`; `get_pipeline()` without `init()` | Returns `None` |

### M5.1a — Shadow parity (existing harness)

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-1a** | Bathos pattern fixture | `tests/shadow/test_bathos_shadow.py` | Pass (AC-SHADOW-1) |
| **AC-M5-1b** | Contemplex pattern fixture | `tests/shadow/test_contemplex_shadow.py` | Pass (AC-SHADOW-2) |
| **AC-M5-1c** | export-dogfood workflow | `uv run pytest tests/shadow/ -q` step before example install | Required; fails on drift |

### M5.1b — Cutover gate (cisterna)

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-2a** | `CISTERNA_TELEMETRY=contemplex` | `consumer_telemetry_enabled("contemplex")` | `True` |
| **AC-M5-2b** | env unset | `consumer_telemetry_enabled("contemplex")` | `False` |
| **AC-M5-2c** | Flag set + `init()` + `traced_tool(ContemplexAdapter())` | Tool call | `ShadowExporter` captures ≥1 `mcp.call_start` with tool name |

### M5.2 — External follow-up

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-3** | M5.1b merged | Backlog item for contemplex repo | Registered with `depends_on: [M5 parent]` |

## Adversarial reconciliation

| Issue | Resolution |
|-------|------------|
| Shadow already shipped | M5.1a = CI + spec path alignment |
| Contemplex repo not in tree | M5.1b cisterna gate only; M5.2 external item |
| AC file name mismatch | Cite `test_bathos_shadow.py` not `test_bathos_parity.py` |
