---
session_id: 80ac261d
topic: M8 milestone for cisterna after M7 OTLP egress — candidates: external adapter epics (#2145 Xperiri, #2146 Myxcel), M7.1 OTLP hardening (HTTP + collector CI), export hardening II (multi-emitter goldens), telemetry operator runbook. What should M8 optimize for?
task_type: constrained-technical
winner: M8-A XpeririAdapter (scoped): XpeririAdapter in base.py + tests/shadow/test_xperiri_shadow.py + AC-SHADOW parity; recon xperiri MCP return shapes first; repo cutover deferred to M8.2; closes #2145
created_at: 2026-06-23T23:03:52.006731+00:00
---

# Brainstorm: M8 milestone for cisterna after M7 OTLP egress — candidates: external adapter epics (#2145 Xperiri, #2146 Myxcel), M7.1 OTLP hardening (HTTP + collector CI), export hardening II (multi-emitter goldens), telemetry operator runbook. What should M8 optimize for?

## Problem Frame
Frame (PEGS): Problem — M2.5 adapter surface incomplete (#2145/#2146 open since M2); operators lack cutover path for xperiri/myxcel MCP shapes. Goal — pick ONE adapter epic: cisterna shadow parity + sibling-repo telemetry_bridge OR adapter-only in cisterna if repos blocked. Environment — Xperiri returns JSON string errors; Myxcel HPC/SLURM hooks; both differ from Bathos/Contemplex. Solution space — shadow tests in tests/shadow/, adapter in base.py, optional consumer cutover PR. Export/OTLP hardening deferred unless adapter blocked.

## Idea Pool
- [ai] M8-A XpeririAdapter: implement in cisterna adapters/base.py; tests/shadow/test_xperiri_shadow.py; JSON-string error shape; backlog #2145
- [ai] M8-B MyxcelAdapter: HPC/SLURM job-span shape; shadow test; backlog #2146; higher complexity
- [ai] M8-C Dual-adapter M8: thin Xperiri + Myxcel stubs only — risk split focus
- [ai] M8-D M7.1 OTLP hardening: HTTP exporter + export-dogfood collector job advisory
- [ai] M8-E Export hardening II: multi-emitter validate_golden matrix expansion
- [ai] M8-F Operator runbook: cutover playbook doc for CISTERNA_TELEMETRY + OTLP — no code
- [ai] M8-G Xperiri cutover bundle: adapter + shadow + xperiri repo telemetry_bridge (mirror M6 bathos)
- [user] PEGS: Processes — MCP tool call → adapter shape_ok/shape_error → emit_event. Events — xperiri uses JSON string returns; myxcel uses job spans + cluster context. Goals — complete adapter matrix from M1 spec §5. States — adapter defined / shadow proven / consumer cutover. Constraints — adapters in consumer repos per backlog titles but shadow lives in cisterna. Assumption: xperiri repo exists and is smaller blast radius than myxcel HPC.
- [user] Neglected: xperiri may be read-only research MCP (lower production traffic) — adapter + shadow sufficient without repo cutover in M8. Myxcel needs job-span not traced_tool — defer cutover to M9. Eliminate dual-adapter and export hardening from M8. Reverse: start from backlog age #2145 open since M2 — clearing oldest debt wins.
- [user] Ready to converge — leading candidate M8-A XpeririAdapter + shadow parity; myxcel deferred.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Critic response: recon gate before implement — spike read xperiri mcp.py return types. If str-only confirmed, M8-A proceeds; if mixed dict/str, adapter handles both. Myxcel (#2146) explicit M9. OTLP/export hardening out of M8.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Frame (PEGS): Problem — M2.5 adapter surface incomplete (#2145/#2146 open since M2); operators lack cutover path for xperiri/myxcel MCP shapes. Goal — pick ONE adapter epic: cisterna shadow parity + sibling-repo telemetry_bridge OR adapter-only in cisterna if repos blocked. Environment — Xperiri returns JSON string errors; Myxcel HPC/SLURM hooks; both differ from Bathos/Contemplex. Solution space — shadow tests in tests/shadow/, adapter in base.py, optional consumer cutover PR. Export/OTLP hardening deferred unless adapter blocked.
**When** implementing M8-A XpeririAdapter (scoped): XpeririAdapter in base.py + tests/shadow/test_xperiri_shadow.py + AC-SHADOW parity; recon xperiri MCP return shapes first; repo cutover deferred to M8.2; closes #2145
**Then**
  - [ ] _add specific measurable criteria_
