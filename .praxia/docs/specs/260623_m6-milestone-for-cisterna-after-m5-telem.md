---
session_id: 17c50011
topic: M6 milestone for cisterna after M5 telemetry adoption — candidates: bathos cutover (M5 runner-up), OTLP exporter wiring, export hardening (Rust bridge, multi-emitter CI), consumer adapter expansion (Xperiri/Myxcel). Prior: M4 export trust shipped, M5 shadow gate + contemplex cutover (#2613). What should M6 optimize for?
task_type: open-creative
winner: M6-A Bathos cutover (scoped): shadow parity tests + telemetry_bridge in bathos repo behind CISTERNA_TELEMETRY=bathos; spike job-span hook if traced_tool insufficient; reuse M5 FACTION-E playbook
created_at: 2026-06-23T21:44:45.708771+00:00
---

# Brainstorm: M6 milestone for cisterna after M5 telemetry adoption — candidates: bathos cutover (M5 runner-up), OTLP exporter wiring, export hardening (Rust bridge, multi-emitter CI), consumer adapter expansion (Xperiri/Myxcel). Prior: M4 export trust shipped, M5 shadow gate + contemplex cutover (#2613). What should M6 optimize for?

## Problem Frame
Frame: Fixed — never-raise telemetry, CISTERNA_TELEMETRY opt-in cutover, shadow parity tests before flipping default, cisterna stays library not app, 311-test baseline. Negotiable — which consumer repo next, OTLP vs JSONL-only, export scope depth. M6 should close the "second consumer" gap (bathos runner-up) OR deliver observability egress (OTLP) if bathos blocked. Optimize for: one repo cutover PR + CI gate + shadow golden, same pattern as M5.

## Idea Pool
- [ai] M6-A Bathos cutover: mirror M5 pattern — shadow tests in cisterna/tests/shadow/bathos/, CISTERNA_TELEMETRY=bathos in bathos repo, BathosAdapter traced_tool bridge, CI gate in export-dogfood.yml
- [ai] M6-B OTLP egress: wire optional opentelemetry-sdk exporter behind CISTERNA_OTLP_ENDPOINT; shadow tests assert span attributes; no consumer cutover required
- [ai] M6-C Export hardening II: multi-emitter validate_golden matrix expansion, Rust bridge spike for asset hashing, required native job in CI
- [ai] M6-D Dual-consumer sprint: thin bathos bridge + OTLP stub (config only, no full SDK) — split focus risk
- [ai] M6-E Telemetry defaults doc + operator runbook: document cutover playbook, defer code to M7
- [ai] M6-F Myxcel/Xperiri adapters only in cisterna (no repo cutover) — expand adapter surface, shadow mocks only
- [user] SCAMPER substitute: instead of another repo cutover, ship OTLP as M6. Combine: bathos cutover + existing shadow harness only (no new exporter). Adapt from M5: reuse telemetry_bridge pattern. Modify: make shadow tests the definition of done. Put to other use: export-dogfood workflow as universal gate. Eliminate: Rust bridge from M6 scope. Reverse: start from operator pain (can't see traces in Grafana) → OTLP wins.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** _not recorded_
**AI:** _not recorded_

## Acceptance Criteria
**Given** Frame: Fixed — never-raise telemetry, CISTERNA_TELEMETRY opt-in cutover, shadow parity tests before flipping default, cisterna stays library not app, 311-test baseline. Negotiable — which consumer repo next, OTLP vs JSONL-only, export scope depth. M6 should close the "second consumer" gap (bathos runner-up) OR deliver observability egress (OTLP) if bathos blocked. Optimize for: one repo cutover PR + CI gate + shadow golden, same pattern as M5.
**When** implementing M6-A Bathos cutover (scoped): shadow parity tests + telemetry_bridge in bathos repo behind CISTERNA_TELEMETRY=bathos; spike job-span hook if traced_tool insufficient; reuse M5 FACTION-E playbook
**Then**
  - [ ] _add specific measurable criteria_
