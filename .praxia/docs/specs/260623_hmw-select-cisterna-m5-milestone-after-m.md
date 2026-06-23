---
session_id: 804e2e1a
topic: HMW: select Cisterna M5 milestone after M4 Export Trust — rebalance toward telemetry pillar without regressing export trust
task_type: architectural
winner: FACTION-E M5-HYBRID: M5a shadow parity (bathos+contemplex) then M5b contemplex cutover behind flag; export CI unchanged
created_at: 2026-06-23T21:31:16.615300+00:00
---

# Brainstorm: HMW: select Cisterna M5 milestone after M4 Export Trust — rebalance toward telemetry pillar without regressing export trust

## Problem Frame
Fixed: export trust CI must stay green; M1 telemetry modules largely exist. Negotiable: which consumer cuts over first. Frame: ONE M5 epic delivering measurable observability adoption in ≥1 consumer without export regression.

## Idea Pool
- [ai] FACTION-A M5-SHADOW-PARITY: Complete M1 shadow harness (AC-SHADOW-1/2) + bathos/contemplex parity tests; no consumer cutover yet.
- [ai] FACTION-B M5-CONTEMPLEX-CUTOVER: Wire contemplex MCP to cisterna v2 decorator telemetry; bathos stays legacy.
- [ai] FACTION-C M5-BATHOS-CUTOVER: Wire bathos CLI to cisterna init + v3 middleware; higher production risk.
- [ai] FACTION-D M5-OTLP-EXPORT: Optional OTLP exporter + advisory CI; JSONL remains default.
- [ai] FACTION-E M5-HYBRID (recommended): M5a shadow parity harness for bathos+contemplex; M5b contemplex cutover behind feature flag; export dogfood CI unchanged.
- [ai] FACTION-F M5-EXPORT-HARDENING: Defer telemetry; hygiene only (#238, vendor validators).
- [user] Competing approaches recorded. Converge on FACTION-E hybrid: prove parity before cutover; contemplex is lower-risk first consumer than bathos HPC path.

## Decision Log
- [ACCEPT] FACTION-E M5-HYBRID: Parity-before-cutover de-risks telemetry; contemplex lower blast radius than bathos
- [DEFER] FACTION-F M5-EXPORT-HARDENING: Export trust complete; hygiene can be parallel debt items
- [DEFER] FACTION-C M5-BATHOS-CUTOVER: Runner-up; bathos cutover deferred to M5.1 or M6 after shadow proves parity

## Assumptions

- **A1:** M1 telemetry modules (`cisterna/telemetry/`, adapters) are the implementation base — no greenfield pipeline.
- **A2:** `export-dogfood` CI remains required gate; telemetry must not auto-init on `import cisterna`.
- **A3:** Contemplex cutover is **opt-in** via env flag (e.g. `CISTERNA_TELEMETRY=contemplex`).
- **A4:** Bathos cutover is **out of M5 scope** (shadow parity only).

## TBDs

| ID | Item | Default |
|----|------|---------|
| TBD-1 | Contemplex repo path / version pin for cutover PR | Document in M5b design; may be sibling repo PR |
| TBD-2 | Shadow fixture source | Vendored logger capture fixtures under `tests/shadow/` |

## Pre-mortem Record
**User:** Pre-mortem: shadow tests bit-rotted when bathos logger names changed; contemplex cutover flag defaulted off and never enabled; export-dogfood CI broke when telemetry init ran at import time. Mitigation: pin shadow fixtures to consumer logger contracts; cutover flag env-gated with CI smoke; lazy telemetry init only on explicit cisterna.init().
**AI:** _not recorded_

## Child work packages

| ID | Deliverable |
|----|-------------|
| **M5.1a** | Shadow harness `tests/shadow/` (bathos + contemplex capture parity) |
| **M5.1b** | Contemplex cutover behind `CISTERNA_TELEMETRY` flag |
| **M5.0** | Export CI guard test (no telemetry side effects on import) |

## Acceptance Criteria

### Epic DoD

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-0** | M5 merged | `uv run pytest -q` + export-dogfood steps | ≥307 tests green; M4 validate loops pass |
| **AC-M5-0b** | `import cisterna` | No `cisterna.init()` called | No QueueListener started; export-dogfood unaffected |

### M5.1a — Shadow parity

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-1a** | Bathos fixture run | `tests/shadow/test_bathos_parity.py` | Legacy vs cisterna JSONL records match (AC-SHADOW-1) |
| **AC-M5-1b** | Contemplex fixture run | `tests/shadow/test_contemplex_parity.py` | Legacy vs cisterna records match (AC-SHADOW-2) |
| **AC-M5-1c** | Logger contract change | Shadow test failure | CI fails on drift |

### M5.1b — Contemplex cutover

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M5-2a** | `CISTERNA_TELEMETRY=contemplex` | contemplex MCP tool call | Events emitted via cisterna pipeline |
| **AC-M5-2b** | Flag unset | contemplex MCP tool call | Legacy telemetry path unchanged |
| **AC-M5-2c** | Cutover enabled | Integration smoke test | ≥1 tool call produces JSONL with cisterna record shape |

## Acceptance Criteria (summary)

**Given** M4 export trust complete (307 tests, dogfood CI).  
**When** M5 Telemetry Adoption ships (shadow + contemplex cutover).  
**Then** AC-M5-0 through AC-M5-2c pass; bathos cutover remains deferred.
