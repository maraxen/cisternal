# M3.1 epic audit — staff design

**task_id:** `260623_epic-audit_m31`  
**spec:** `.praxia/docs/specs/260623_hmw-audit-closed-epic-m3-1-2326-before-m.md` (brainstorm winner OPTION-D)  
**research:** `.praxia/docs/research/260623_m31-epic-closeout-audit.md`

## Audit scope

**In:** AC matrix crosswalk (M31a/b/c), pytest+ruff CI, stale debt closure, rev2 doc drift fix, entry_point packaging memo, M3.2 backlog registration, loop_state handoff.

**Out:** Emitter plugin implementation, WriterSink, L14 workflow parsing, code refactors beyond doc/debt hygiene.

## Subagent routing

| Track | Agent | Deliverable |
|-------|-------|-------------|
| W1 | reviewer | AC matrix + pytest log |
| W2 | fixer (docs only) | rev2 deferred section amend; `debt close #235` |
| W3 | librarian | `260623_m32-entry-point-packaging.md` |
| W4 | orchestrator | `backlog add` M3.2 parent; `loop_state.toml` TRIAGE |

## Worktree safety

Audit executes on `main` (worktree_safe=false). No promote/merge required — verification read-only except docs and `.praxia` artifacts.

## Success metrics

- 275+ pytest green, ruff clean
- 24/24 ACs cited in closeout memo
- Debt #235 closed
- M3.2 parent backlog item registered with `depends_on: [2326]`
- `loop.current_phase = "TRIAGE"`, `closed_epic_id = 2326`

## Adversarial verdict

**ACCEPT** — audit scope bounded; no product code risk in W2 beyond spec amendment; M3.2 research stub addresses pre-mortem packaging assumption.
