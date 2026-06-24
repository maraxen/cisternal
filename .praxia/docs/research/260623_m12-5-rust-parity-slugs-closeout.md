# M12.5 rust-parity golden slug expansion — closeout

**date:** 2026-06-23  
**verdict:** **APPROVE**

## Deliverables

| AC | Status | Evidence |
|----|--------|----------|
| AC-M12-5-1 | PASS | 8 new digests under `rust_parity/{dogfood_praxia,self_manifest}/` |
| AC-M12-5-2 | PASS | `test_rust_parity_matrix.py` — 12 tuples (3 slugs × 4 surfaces) |
| AC-M12-5-3 | PASS | `write_rust_parity_golden_digest` dev helper |
| AC-M12-5-4 | PASS | `rust-parity` CI job includes matrix test |

## Unchanged

- `golden_matrix` Python-canonical tuples
- Default `validate` path (still Python)
- Legacy slug goldens (covered by matrix + per-surface tests)
