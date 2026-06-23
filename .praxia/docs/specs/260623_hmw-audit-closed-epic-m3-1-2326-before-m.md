---
session_id: 93eb820f
topic: HMW: audit closed epic M3.1 (#2326) before M3.2 entry_point plugins — verify shipped vs claimed, identify drift/debt, and scope safe M3.2 triage
task_type: constrained-technical
winner: OPTION-D HYBRID: W1 mechanical AC matrix + pytest; W2 close stale debt + doc drift fix; W3 entry_point research memo; W4 register M3.2 parent backlog + loop_state TRIAGE
created_at: 2026-06-23T20:32:01.501247+00:00
---

# Brainstorm: HMW: audit closed epic M3.1 (#2326) before M3.2 entry_point plugins — verify shipped vs claimed, identify drift/debt, and scope safe M3.2 triage

## Problem Frame
Fixed: M3.1 epic closed (#2326, children #2486/#2487/#2559 completed); 275 tests + ruff must stay green; four emitters + golden harness shipped; M3.2 scope locked to entry_point plugins + deferred rev2 items (WriterSink, snapshot API, L14 validate-only workflows). Negotiable: audit sprint depth (mechanical VERIFY vs librarian research on entry_points packaging); whether to fix doc drift in rev2 spec in audit sprint or defer to M3.2 planning.

## Idea Pool
- [ai] OPTION-A MECHANICAL-VERIFY: Epic audit sprint = full pytest + AC matrix crosswalk (M31a/b/c) + close stale debt #235 + loop_state EPIC_AUDIT→TRIAGE. No code changes. Fast gate before M3.2 brainstorm.
- [ai] OPTION-B VERIFY-PLUS-RESEARCH: Mechanical verify + librarian memo on entry_point packaging (PEP 621 entry-points group cisterna.emitters) and praxia plugin patterns before M3.2 spec.
- [ai] OPTION-C VERIFY-PLUS-DOC-FIX: Mechanical verify + surgical rev2 spec amendment (Antigravity shipped M3.1c not M3.2) + backlog parent M3.2 registration with depends_on #2326.
- [user] PEGS: Processes=pytest golden validate export inspect; Events=epic close #2326, audit VERIFY; Goals=prove all ACs cited, route to M3.2; States=275 green baseline, debt #235 possibly stale. Components=4 emitters, 5 golden digests, vendor_tools.toml, hooks_for_surface. Constraints=L2 gates, no API freeze violations for M3.2 prep.
- [ai] OPTION-D HYBRID (recommended): W1 mechanical AC matrix + pytest; W2 close stale debt + doc drift fix in rev2 deferred section; W3 librarian research stub for entry_points; W4 register M3.2 parent backlog + loop_state TRIAGE. Balances speed with M3.2 readiness.
- [user] Converge on OPTION-D HYBRID: mechanical verify first, doc drift fix as hygiene, entry_point research memo gates M3.2 spec, register M3.2 parent backlog item.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem failure: M3.2 entry_point spec assumed setuptools discovery but project uses uv/hatchling — sprint blocked 2 weeks. Mitigation: W3 research must cite pyproject.toml packaging backend and test a minimal entry_point stub before M3.2 spec lock.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Fixed: M3.1 epic closed (#2326, children #2486/#2487/#2559 completed); 275 tests + ruff must stay green; four emitters + golden harness shipped; M3.2 scope locked to entry_point plugins + deferred rev2 items (WriterSink, snapshot API, L14 validate-only workflows). Negotiable: audit sprint depth (mechanical VERIFY vs librarian research on entry_points packaging); whether to fix doc drift in rev2 spec in audit sprint or defer to M3.2 planning.
**When** implementing OPTION-D HYBRID: W1 mechanical AC matrix + pytest; W2 close stale debt + doc drift fix; W3 entry_point research memo; W4 register M3.2 parent backlog + loop_state TRIAGE
**Then**
  - [ ] _add specific measurable criteria_
