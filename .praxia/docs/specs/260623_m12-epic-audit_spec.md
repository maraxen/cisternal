# Inter-epic audit spec — M12 closeout (#2665)

**task_id:** `260623_epic-audit_m12`  
**winner:** Audit-B (verification + hygiene)  
**spec_path:** `.praxia/docs/specs/260623_m12-epic-audit_spec.md`  
**date:** 2026-06-23

## Problem

M12 (#2665) shipped across four commits (`c0eca94`..`5e05e87`). Before TRIAGE for the next epic, verify claimed ACs, remediate mechanical CI gaps, and register backlog hygiene.

## Decision log

| ID | Decision | Rationale |
|----|----------|-----------|
| D-1 | Winner: Audit-B | Mechanical verify + backlog/loop hygiene without bundling #2667 docs epic |
| D-2 | Reject Audit-C | Docs drift is separate P3 epic (#2667), not audit sprint scope |
| D-3 | Reject Audit-D | Ruff F401 blocks `dogfood` job — cannot skip execute |
| D-4 | Defer worktree purge | 28+ worktrees → debt note only |

## Assumptions

- Local `default_ci` matches `loop_priorities.toml` invariants.
- M12 feature code is frozen; audit may only touch hygiene/docs/loop artifacts.
- First green GHA `rust-parity` job verified by operator post-push (CH-404).

## TBDs

| ID | Item | Owner |
|----|------|-------|
| T-1 | First green `rust-parity` on GHA `main` | Operator |
| T-2 | Next epic pick: #2667 vs #2666 | Operator at TRIAGE |

## Pre-mortem

**Risk:** Audit sprint expands into docs rewrite → **Mitigation:** #2667 registered as separate backlog child, not in audit execute tracks.

**Risk:** Orphan backlog items confuse triage → **Mitigation:** Close/dedup 2661/2662 in hygiene track.

## Acceptance criteria

**AC-AUDIT-1 (regression):** Given `uv run pytest -q && uv run ruff check .`, when run on `main` at `5e05e87+`, then all tests pass and ruff is clean.

**AC-AUDIT-2 (M12 matrix):** Given closeout research memo `.praxia/docs/research/260623_m12-epic-audit.md`, when AC rows are reviewed, then M12.1–M12.4 substantive ACs are PASS with file/test citations.

**AC-AUDIT-3 (backlog):** Given audit sprint completes, when backlog is queried, then parent audit item and #2665 M12 epic are `completed`; #2666 and #2667 are `open` with `depends_on` audit parent.

**AC-AUDIT-4 (loop):** Given audit VERIFY PASS, when `loop_state.toml` is read, then `current_phase = "TRIAGE"`, `closed_epic_id = 2665`, `loop_priorities.toml` includes `m12_export_rust_bridge_complete = true`.

**AC-AUDIT-5 (no scope creep):** Given audit sprint boundaries, when diff is reviewed, then no new rust_parity emitters, no default validate flip, no `golden_matrix` rust slug expansion.
