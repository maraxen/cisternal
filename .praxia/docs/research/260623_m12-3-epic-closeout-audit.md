# M12.3 epic closeout audit

**date:** 2026-06-23  
**backlog:** #2665  
**baseline:** 431 passed → **450 passed**, 2 skipped

## AC matrix

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-M12-3a | PASS | `test_cursor_rust_parity.py` — digest `ca8d6a3e…`, 3-file set, no agent `.md` |
| AC-M12-3b | PASS | `test_copilot_rust_parity.py` — digest `40524672…` |
| AC-M12-3c | PASS | `test_antigravity_rust_parity.py` — digest `63768b08…` |
| AC-M12-3d | PASS | `tests/golden/rust_parity/legacy/{cursor,copilot,antigravity}/digest.sha256` |
| AC-M12-3e | PASS | `surface_digest_rust_parity` dispatches all 4 surfaces via `_RUST_PARITY_EMITTERS` |
| AC-M12-3f | PASS | `test_cli_rust_parity.py` parametrized 4 surfaces; in-process via `test_*_rust_parity.py` |

## Deliverables

- `src/cisterna/export/_rust_emit.py` — shared helpers (refactor from M12.2)
- `cursor_rust.py`, `copilot_rust.py`, `antigravity_rust.py`
- `CursorEmitter` / `CopilotEmitter` / `AntigravityEmitter` `rust_parity=True`
- `test_rust_parity_hook_filter.py` (CH-303)
- Advisory CI expanded with in-process parity tests

## Unchanged

- `tests/golden/` legacy Python-canonical digests
- `golden_matrix` blocking job
- `rust-parity-advisory` `continue-on-error: true` (M12.4)

## Next

**M12.4** — promote `rust-parity-advisory` to blocking; optional default validate flip.
