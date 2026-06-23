---
session_id: 179dcc85
topic: M3.3 (#2581) triage: which deferred rev2 child ships first — snapshot API vs WriterSink vs vendor commands vs L14 validate
task_type: constrained-technical
winner: OPTION-A M33A-SNAPSHOT
created_at: 2026-06-23T20:50:29.853939+00:00
---

# Brainstorm: M3.3 (#2581) triage: which deferred rev2 child ships first — snapshot API vs WriterSink vs vendor commands vs L14 validate

## Problem Frame
Confirmed frame.

## Idea Pool
- [ai] OPTION-A M33A-SNAPSHOT: public snapshot() + list_registries(); _snapshot alias; source.py migrates; register M3.3b/c/d children.
- [ai] OPTION-B M33A-WRITERSINK: WriterSink ABC first — higher refactor risk, lower immediate value.
- [user] Converge OPTION-A M33A-SNAPSHOT. Pre-mortem: exposing _REGISTRIES leak — mitigate with list_registries() only.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem: public snapshot encouraged direct mutation of returned dict breaking wire freeze. Mitigation: document shallow copy; tests assert mutating snapshot does not affect registry.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Confirmed frame.
**When** implementing OPTION-A M33A-SNAPSHOT
**Then**
  - [ ] _add specific measurable criteria_
