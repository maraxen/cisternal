# M12 epic closeout audit — Export Rust bridge (#2665)

**date:** 2026-06-23  
**final commit slice:** M12.4 (blocking CI promotion)  
**baseline:** 450 passed → verify post-M12.4

## Epic verdict: **APPROVE** — #2665 complete

## AC matrix (M12.0–M12.4)

| Slice | Key ACs | Verdict |
|-------|---------|---------|
| **M12.1** bridge | AC-M12-0..1m: bundle-hash, bridge, validate --rust-parity, advisory CI | PASS (c0eca94) |
| **M12.2** claude | AC-M12-2a..c: ClaudeEmitter rust_parity, bundle_sha256_rust, legacy goldens unchanged | PASS (093a54d) |
| **M12.3** surfaces | AC-M12-3a..f: cursor/copilot/antigravity wedges, rust_parity goldens | PASS (25e1b8c) |
| **M12.4** promotion | AC-M12-4: rust-parity job blocking | PASS (this slice) |

## AC-M12-4 scope interpretation (CH-401)

Spec literal: “matrix rust_parity tuples green.” **Minimal closeout:**

- **Conformance gate:** `manifest_minimal` × 4 surfaces — in-process + subprocess green
- **Rust parity goldens:** `tests/golden/rust_parity/legacy/{claude,cursor,copilot,antigravity}/`
- **Deferred:** `rust_parity` digests for `dogfood_praxia` and `self_manifest` slugs (future work)
- **Unchanged:** `golden_matrix` 15 Python-canonical tuples

## M12.4 deliverables

- `rust-parity-advisory` → **`rust-parity`** (no `continue-on-error`)
- `test_workflow_export_dogfood.py` — blocking contract
- Runbook + conformance README dual-lane docs

## Operator checklist (CH-404)

- [ ] Verify first green `rust-parity` job on GitHub Actions `main` after merge
- [ ] Fork PRs without `maraxen/praxia` checkout may fail `rust-parity` (accepted)

## Residual / deferred

- Default `validate` flip to rust parity (oracle decision)
- `golden_matrix` rust_parity slug expansion
- Optional `CISTERNA_PRAXIA_ASSETS_REV` bump to `81bff16`
- Registry `rust_parity` kwarg on `get_emitter`

## Next epics (suggested)

- **#2667** docs hygiene (P3)
- **#2666** M11.2 native-validate surface expansion (P3)
