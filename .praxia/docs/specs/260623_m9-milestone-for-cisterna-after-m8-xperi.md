---
session_id: 76929000
topic: M9 milestone for cisterna after M8 XpeririAdapter — primary candidate MyxcelAdapter (#2146) with job-span semantics, alternatives: M8.2 xperiri cutover, M7.1 OTLP hardening, export hardening II, operator runbook. What should M9 optimize for?
task_type: constrained-technical
winner: M9-A scoped: MyxcelAdapter (recon-gated envelope) + job_span() context helper in cisterna.telemetry; tests/shadow/test_myxcel_shadow.py for MCP + job span paths; closes #2146; myxcel repo cutover M9.2
created_at: 2026-06-23T23:17:31.602719+00:00
---

# Brainstorm: M9 milestone for cisterna after M8 XpeririAdapter — primary candidate MyxcelAdapter (#2146) with job-span semantics, alternatives: M8.2 xperiri cutover, M7.1 OTLP hardening, export hardening II, operator runbook. What should M9 optimize for?

## Problem Frame
Frame (PEGS): Problem — myxcel cluster jobs lack cisterna telemetry path; MCP tools exist but primary surface is SLURM submit/run spans. Goal — MyxcelAdapter + job-span helper (cisterna.span) + tests/shadow/test_myxcel_shadow.py; close #2146. Environment — myxcel repo sibling; bathos-like dict envelopes vs job metadata. Solution space — adapter for MCP-shaped calls; separate job_span() context manager mapping run_uuid/task_id; shadow fixture stubs myxcel logger. Defer myxcel repo telemetry_bridge to M9.2.

## Idea Pool
- [ai] M9-A MyxcelAdapter + job_span helper: MyxcelAdapter in base.py (bathos-like dict envelope); job_span(name) sets task_id/run_uuid context; tests/shadow/test_myxcel_shadow.py
- [ai] M9-B MCP-only MyxcelAdapter: traced_tool path only, no job spans — insufficient for HPC
- [ai] M9-C myxcel repo cutover bundle: adapter + shadow + telemetry_bridge in myxcel — scope creep
- [ai] M9-D M8.2 xperiri cutover instead — wrong priority
- [ai] M9-E M7.1 OTLP HTTP + collector CI — deferred again
- [ai] M9-F job_span in cisterna.telemetry.span only: extend span() with SLURM metadata fields; adapter thin
- [ai] M9-G Dual: MyxcelAdapter stub + document M9.2 cutover only — too thin
- [user] PEGS: Processes — bth submit → SLURM job → runner spans; MCP tools for cluster query. Events — job.start/end, mcp.call_* for myxcel MCP. Goals — propagate BTH_TASK_ID / run_uuid into Record. States — adapter for MCP; job_span for batch. Constraints — myxcel logger name "myxcel". Assumption: bathos envelope shape works for myxcel MCP errors.
- [user] Ready to converge — M9-A MyxcelAdapter + job_span helper is leading candidate.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Critic: recon myxcel MCP first; if envelope differs from bathos, MyxcelAdapter gets custom shape_error. job_span sets task_id_var from env BTH_TASK_ID / MYX_JOB_ID. M8.2/M7.1 out of M9.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Frame (PEGS): Problem — myxcel cluster jobs lack cisterna telemetry path; MCP tools exist but primary surface is SLURM submit/run spans. Goal — MyxcelAdapter + job-span helper (cisterna.span) + tests/shadow/test_myxcel_shadow.py; close #2146. Environment — myxcel repo sibling; bathos-like dict envelopes vs job metadata. Solution space — adapter for MCP-shaped calls; separate job_span() context manager mapping run_uuid/task_id; shadow fixture stubs myxcel logger. Defer myxcel repo telemetry_bridge to M9.2.
**When** implementing M9-A scoped: MyxcelAdapter (recon-gated envelope) + job_span() context helper in cisterna.telemetry; tests/shadow/test_myxcel_shadow.py for MCP + job span paths; closes #2146; myxcel repo cutover M9.2
**Then**
  - [ ] _add specific measurable criteria_
