# Inter-epic audit — M12 export Rust bridge (#2665)

**task_id:** `260623_epic-audit_m12`  
**closed_epic:** #2665 M12 export Rust bridge  
**next_epic:** #2712 docs hygiene (P3) or #2713 native-validate expansion (P3)  
**date:** 2026-06-23

## Shipped vs claimed

| Acceptance criterion | Status | Evidence |
|---------------------|--------|----------|
| AC-M12-1 bridge + advisory CI | PASS | `c0eca94` — `src/cisterna/assets/bridge.py`, `tests/test_rust_parity.py` |
| AC-M12-2 Claude rust_parity wedge | PASS | `093a54d` — `src/cisterna/export/claude_rust.py`, `tests/test_claude_rust_parity.py` |
| AC-M12-3 cursor/copilot/antigravity | PASS | `25e1b8c` — `*_rust.py` emitters + golden digests |
| AC-M12-4 blocking rust-parity job | PASS | `5e05e87` — `.github/workflows/export-dogfood.yml:81-111`, `tests/test_workflow_export_dogfood.py:39-47` |
| AC-M12-4 no continue-on-error | PASS | `rg continue-on-error .github` → no matches |
| Closeout memo | PASS | `.praxia/docs/research/260623_m12-4-epic-closeout-audit.md` |
| default_ci (pytest+ruff) | PASS | 450 passed, 2 skipped; ruff clean after F401 fix |
| Backlog hygiene | PASS | Audit #2709; M12 #2710; next #2712, #2713 |
| loop_priorities m12 flag | PASS | `m12_export_rust_bridge_complete = true` |
| First green GHA rust-parity | UNVERIFIED | Operator checklist CH-404 |

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 450 passed, 2 skipped; All checks passed!
```

## Remediation applied

- Removed unused `os`/`Path` imports in `tests/test_rust_parity.py` (F401)
- Updated `loop_priorities.toml` — `closed = 2665`, `m12_export_rust_bridge_complete = true`

## Open risks for next epic

1. **Doc drift** — historical specs say advisory; #2712 scope
2. **Fork PR rust-parity** — cross-repo checkout limitation (accepted)
3. **Worktree hygiene** — debt #294; 28+ stale worktrees
4. **Deferred M12** — matrix rust_parity slugs, default validate flip

## Verdict

**VERIFY PASS** — route to TRIAGE. Pick #2712 (docs) or #2713 (native-validate).
