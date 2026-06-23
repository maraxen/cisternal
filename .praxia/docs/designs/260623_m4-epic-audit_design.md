# M4 epic audit — staff design

**task_id:** `260623_epic-audit_m4`  
**closed_epic:** #2597  
**spec:** `.praxia/docs/specs/260623_m4-export-trust-buildable-spec-rev1.md`

## Scope

**In:** AC matrix (22 ACs across 6 children), mechanical verify (pytest+ruff+validate loops), legacy golden stability, CI workflow structure, loop TRIAGE.

**Out:** M5 planning, vendor IDE validators (TBD-1), debt #238 fix, git commit (parent/PI).

## Adversarial verdict

**ACCEPT** — all M4 children verified; parallel W1 ownership succeeded; CI ordering preserves M3.2 registry test isolation.

## Worktree safety

Audit read-only on `main`; M4 implementation is uncommitted working-tree delta.
