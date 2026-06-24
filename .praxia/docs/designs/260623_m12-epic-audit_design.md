# Inter-epic audit design — M12 closeout

**task_id:** `260623_epic-audit_m12`  
**spec:** `.praxia/docs/specs/260623_m12-epic-audit_spec.md`  
**research:** `.praxia/docs/research/260623_m12-epic-audit.md`

## Scope

**In:** Mechanical verification, ruff remediation, backlog/loop hygiene, followup registration, loop_state → TRIAGE.

**Out:** M12 feature work, #2667 doc rewrites, worktree deletion, praxia pin bump, matrix rust_parity slug expansion.

## Subagent routing

| Track | Agent | Deliverable |
|-------|-------|-------------|
| a | reviewer | pytest + ruff green; workflow grep no `continue-on-error` |
| b | orchestrator | backlog DAG: complete #2665, add audit parent + #2666/#2667 |
| c | fixer | ruff F401 in `tests/test_rust_parity.py` |
| d | orchestrator | loop_state, loop_priorities, triage cache, lesson/debt |

## Worktree safety

Main-branch edits only. No worktree attach/teardown during audit. Document 28 unmanaged worktrees as debt; do not purge in this sprint.

## Success metrics

- `default_ci` green locally
- Research memo verdict → VERIFY PASS after track c
- Backlog reflects closed M12 + open next candidates
- `iteration_count` incremented; `next_phase = TRIAGE`
