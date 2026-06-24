# Epic closeout audit — M12.1 Rust parity bridge (#2665)

**date:** 2026-06-24  
**commit:** (cisterna pending)  
**praxia pin:** `04bb683f11d6e879dcfc5dafbedfed426254985a`  
**baseline:** 413 passed → **424 passed**, 2 skipped

## Verdict

**APPROVE** — M12.1 subprocess bridge shipped; legacy export trust unchanged; advisory CI wired.

## AC matrix (M12.1)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M12-0 | PASS | praxia `bundle-hash` @ `04bb683` |
| AC-M12-0a/b | PASS | `bundle_hash.rs` + `bundle_hash_cli.rs` |
| AC-M12-1a/b | PASS | `src/cisterna/assets/bridge.py` |
| AC-M12-1c | PASS | `tests/test_rust_parity_bridge.py` |
| AC-M12-1d/e | PASS | `rust_surface_digest()`, env resolver |
| AC-M12-1f/g | PASS | `validate --rust-parity` + `test_cli_rust_parity.py` |
| AC-M12-1h/i | PASS | `tests/conformance/` fixtures + expected digests |
| AC-M12-1j | PASS | `tests/test_rust_parity.py` (4 surfaces) |
| AC-M12-1k | PASS | `rust-parity-advisory` job, `continue-on-error: true` |
| AC-M12-1l | PASS | dogfood/golden_matrix/native-validate/otlp unchanged |
| AC-M12-1m | PASS | `tests/conformance/README.md` + `test_rust_parity.py` docstring |

## Residual / deferred

- M12.2 claude emitter byte-align (digests still differ for Python export path)
- Promote rust-parity to blocking (M12.4)
- Fork PRs without praxia checkout: advisory may fail (accepted)

## Next

**M12.2** — ClaudeEmitter wedge + `rust_parity` golden tree.
