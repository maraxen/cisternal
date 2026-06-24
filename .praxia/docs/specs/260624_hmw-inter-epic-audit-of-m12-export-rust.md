---
session_id: 7506e03e
topic: HMW: inter-epic audit of M12 export Rust bridge (#2665) before selecting next epic (#2667 docs hygiene vs #2666 native-validate)
task_type: architectural
winner: 
created_at: 2026-06-24T15:47:14.508840+00:00
---

# Brainstorm: HMW: inter-epic audit of M12 export Rust bridge (#2665) before selecting next epic (#2667 docs hygiene vs #2666 native-validate)

## Problem Frame
Fixed constraints: M12 code frozen (no new rust_parity features); default_ci = pytest + ruff; no autonomous push; dual-lane export trust model stays. Negotiable: audit sprint scope (mechanical-only vs include docs hygiene epic); which next epic to prioritize; worktree cleanup deferral.

Frame: Verify M12 AC matrix with cited evidence, fix mechanical blockers (ruff), complete backlog/loop hygiene, file followups for deferred M12 items and next-epic candidates, then route to TRIAGE.

## Idea Pool
- [ai] Audit-A: Mechanical verification sprint only — fix ruff, mark #2665 complete, update loop_priorities, verify pytest+ruff green, no new backlog children beyond audit parent
- [ai] Audit-B: Verification + hygiene — Audit-A plus register #2667/#2666 backlog items, dedup orphan 2661/2662, document worktree debt
- [ai] Audit-C: Verification + docs drift — Audit-B plus launch #2667 docs hygiene as immediate child (advisory→blocking spec wording one-pass)
- [user] Three approaches on the table: A mechanical-only, B hygiene+backlog registration, C B plus immediate docs drift fix as #2667. Trade-off: A is fastest to TRIAGE but leaves doc drift and orphan backlog; C risks scope creep into a second epic mid-audit.
- [critic] Audit-D: Oracle-first triage — skip audit sprint execution; accept closeout memo as sufficient; jump directly to TRIAGE with operator picking #2667 vs #2666 (risk: ruff blocker would ship to CI)
- [user] Steelman Audit-B: closes the loop on backlog hygiene without feature work; registers next epics with depends_on audit parent; ruff fix is mandatory regardless. Audit-D rejected because ruff already blocks dogfood CI. Prefer B over C to keep audit sprint bounded.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** _not recorded_
**AI:** _not recorded_

## Acceptance Criteria
**Given** Fixed constraints: M12 code frozen (no new rust_parity features); default_ci = pytest + ruff; no autonomous push; dual-lane export trust model stays. Negotiable: audit sprint scope (mechanical-only vs include docs hygiene epic); which next epic to prioritize; worktree cleanup deferral.

Frame: Verify M12 AC matrix with cited evidence, fix mechanical blockers (ruff), complete backlog/loop hygiene, file followups for deferred M12 items and next-epic candidates, then route to TRIAGE.
**When** implementing the chosen approach
**Then**
  - [ ] _add specific measurable criteria_
