---
session_id: f04480ad
topic: Cisterna M3.1b (#2487): Cursor + Copilot emitters, HookSpec surface filter, golden validate — should Antigravity CLI emitter fold into this wave or stay M3.2?
task_type: architectural
winner: OPTION-C (M31C-SPLIT): M3.1b = Cursor + Copilot per rev2; register M3.1c Antigravity child with depends_on #2487 and explicit librarian doc gate (gemini-extension.json vs plugin.json) before emitter implementation. Parent #2326 closes after M3.1c.
created_at: 2026-06-23T19:58:50.683464+00:00
---

# Brainstorm: Cisterna M3.1b (#2487): Cursor + Copilot emitters, HookSpec surface filter, golden validate — should Antigravity CLI emitter fold into this wave or stay M3.2?

## Problem Frame
Fixed constraints: (1) M3.1a shipped — Composite, validate golden harness, ClaudeEmitter default byte-identical to M3. (2) Emitter ABC + pure emit pattern. (3) Praxia parity for hook dialects (cursor camelCase, copilot inline). (4) L2 gates before sprint execute. Negotiable: whether Antigravity is in #2487, a new M3.1c item, or M3.2; golden strictness for antigravity; doc gate before emitter code. Frame: maximize four-surface export value while minimizing schema-churn rework — Antigravity is the only surface with active format uncertainty.

## Idea Pool
- [ai] OPTION-A (SPEC-LOCKED): Execute rev2 as written — M3.1b = CursorEmitter + CopilotEmitter + HookSpec surface filter + cursor|copilot golden. Register Antigravity as M3.2 backlog child with depends_on #2487. Lowest risk; closes two structurally distinct surfaces first.
- [ai] OPTION-B (EXPAND-M31B): Add AntigravityEmitter to #2487 same sprint — port bundle_antigravity.rs (gemini-extension.json), extend validate --surface antigravity, vendor map already stubbed. Closes four-surface parity in one epic but schema drift may force rework.
- [ai] OPTION-C (M31C-SPLIT): M3.1b ships Cursor/Copilot only; new backlog #M3.1c "Antigravity emitter" gated on librarian doc pass confirming gemini-extension.json vs plugin.json. Parent #2326 closes after M3.1c not M3.1b.
- [ai] OPTION-D (EXPERIMENTAL-STUB): M3.1b adds AntigravityEmitter behind --experimental-antigravity with praxia-frozen schema, no golden hash lock until doc gate passes. Enables early dogfooding without blocking Cursor/Copilot golden CI.
- [user] Four approaches on the table:
- [user] A — SPEC-LOCKED: Ship rev2 M3.1b (Cursor + Copilot only); Antigravity stays M3.2. Matches approved spec and #2487 title.
- [user] B — EXPAND-M31B: Add AntigravityEmitter in same sprint as Cursor/Copilot. Fastest four-surface parity; highest schema-churn risk (gemini-extension.json vs future plugin.json).
- [user] C — M31C-SPLIT: M3.1b Cursor/Copilot on schedule; new M3.1c backlog item for Antigravity after a librarian doc gate. De-risks format bet without blocking Cursor/Copilot.
- [user] D — EXPERIMENTAL-STUB: Antigravity behind --experimental-antigravity, praxia-frozen gemini-extension.json, no golden lock until docs verified. Dogfood early without blocking CI golden for cursor/copilot.
- [user] My lean: C over B — Antigravity has UNVERIFIED format drift; Cursor/Copilot are structurally ready (praxia ports exist, AC-M31b-1..7 drafted). A is safe default if PI wants zero scope change.

## Decision Log
- [REJECT] OPTION-B (EXPAND-M31B): Schema drift risk + sprint slip; golden CI would lock gemini-extension.json before doc verification. Reject for M3.1b wave.
- [DEFER] OPTION-D (EXPERIMENTAL-STUB): Adds CLI complexity and two-tier quality bar; stub without golden still needs maintenance. Defer unless PI demands early dogfood.

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem failure (6 months): M3.1b shipped Cursor/Copilot but Cursor fail-closed gate was wrong — agents key present without files broke real plugins; we blamed M3.1c deferral while users churned. M3.1c Antigravity never started because librarian gate kept finding doc deltas; #2326 rotted open. Mitigation: time-box doc gate to 1 sprint; ship M3.1b with AC-M31b-6/7 strictly enforced; register M3.1c with concrete ACs and gemini-extension.json golden from praxia fixture on day one of M3.1c.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Fixed constraints: (1) M3.1a shipped — Composite, validate golden harness, ClaudeEmitter default byte-identical to M3. (2) Emitter ABC + pure emit pattern. (3) Praxia parity for hook dialects (cursor camelCase, copilot inline). (4) L2 gates before sprint execute. Negotiable: whether Antigravity is in #2487, a new M3.1c item, or M3.2; golden strictness for antigravity; doc gate before emitter code. Frame: maximize four-surface export value while minimizing schema-churn rework — Antigravity is the only surface with active format uncertainty.
**When** implementing OPTION-C (M31C-SPLIT): M3.1b = Cursor + Copilot per rev2; register M3.1c Antigravity child with depends_on #2487 and explicit librarian doc gate (gemini-extension.json vs plugin.json) before emitter implementation. Parent #2326 closes after M3.1c.
**Then**
  - [ ] _add specific measurable criteria_
