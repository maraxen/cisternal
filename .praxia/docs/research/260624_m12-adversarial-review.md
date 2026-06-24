# Adversarial review — M12 Export Rust bridge (#2665)

**date:** 2026-06-24  
**spec:** `.praxia/docs/specs/260624_m12-export-rust-bridge-buildable-spec-rev1.md`  
**design:** `.praxia/docs/designs/260624_m12-export-rust-bridge_design.md`  
**spike:** `.praxia/docs/research/260624_m12-hash-parity-spike.md`  
**depends_on:** M11 golden matrix (#2649), M11.1 native-validate  
**verdict:** **ACCEPT_WITH_NITS**

## Summary

M12.1 (subprocess bridge + conformance fixtures + advisory CI) is shippable without touching existing 15 legacy goldens or `golden_matrix`. Cross-repo work is scoped to one praxia binary and a pinned CI checkout. Emitter port (M12.2+) correctly deferred. Blast radius M12.1: new modules + optional validate flag + new CI job — no change to default validate or export paths.

## Findings → reconciliation

| ID | Sev | Challenger | Defender | Synthesis |
|----|-----|------------|----------|-----------|
| **CH-001** | BLOCKER | M12.1a lives in praxia — cisterna-only sprint cannot ship without cross-repo PR | PI epic; design names praxia deliverable | **Fixed** — AC-M12-0: M12.1 blocked on praxia `bundle-hash` merge; cisterna can stub with `CISTERNA_PRAXIA_ASSETS_BIN` for local dev |
| **CH-002** | MAJOR | `asset_bundle_to_praxia_json` may omit fields Rust expects (`description` on skills, empty `surfaces` on hooks) | Spike hand-built bundle matched Rust; mapper needs explicit defaults | **Fixed** — AC-M12-1c: round-trip test asserts subprocess digest equals hand-built JSON for manifest_minimal |
| **CH-003** | MAJOR | `--rust-parity` vs golden file — design says "no golden required" but also `rust_parity/` tree | Live compare is oracle; golden files pin CI expected values | **Fixed** — AC-M12-1f: tests assert against pinned `tests/conformance/expected/{surface}.sha256`; validate flag runs live compare for operator use |
| **CH-004** | MAJOR | Dual checkout in CI — cisterna PRs from forks lack praxia access | Same as any cross-repo dep | **Fixed** — AC-M12-1g: job checks out `marielle/praxia` or monorepo path; `continue-on-error: true` until pin stable; document fork limitation |
| **CH-005** | MAJOR | M12.1 advisory passes while `golden_matrix` still Python-only — false confidence | By design; rust-parity expected to fail until M12.2 | **Fixed** — AC-M12-1g: job name `rust-parity-advisory`; README/runbook states "expected fail until emitter port"; do not promote blocking until M12.3 |
| **CH-006** | MINOR | `bundle-hash` stdin JSON vs TOML bundle file | JSON matches `PraxiaBundle` serde; manifest load is cisterna-side | **Fixed** — stdin JSON only for v1; `--bundle` optional file path same schema |
| **CH-007** | MINOR | `CISTERNA_PRAXIA_ASSETS_BIN` unset — silent skip or hard fail? | validate should fail closed | **Fixed** — `--rust-parity` exit 1 with stderr if bin missing or nonzero exit |
| **CH-008** | MINOR | Claude `with_command_bodies` rust_parity undefined | Rust always emits command bodies in separate paths when in bundle | **Fixed** — rust_parity lane ignores `emit_command_bodies`; claude conformance uses commands in bundle body only |
| **CH-009** | INFO | PyO3 rejected — revisit if subprocess latency blocks interactive validate | Accepted tradeoff | **Accepted** — document in design |
| **CH-010** | INFO | 15 legacy goldens refreshed in M12.2+ not M12.1 | Correct phasing | **Accepted** |

## Scope check

| In M12.1 | Out M12.1 |
|----------|-----------|
| praxia `bundle-hash` bin | ClaudeEmitter byte port |
| `asset_bundle_to_praxia_json` | `bundle_sha256` algorithm switch |
| `validate --rust-parity` | golden_matrix changes |
| conformance fixtures + parity tests | Blocking rust-parity CI |
| advisory CI job | PyO3 / maturin |

## Edge-case matrix (M12.1)

| Condition | `--rust-parity` behavior |
|-----------|------------------------|
| bin missing | exit 1, stderr |
| bin exit 1 (bad JSON) | exit 1, propagate stderr |
| surface unsupported | exit 2 (existing validate) |
| manifest warnings/conflicts | exit 1 (before parity) |
| digest match | exit 0 |
| digest mismatch | exit 1, log expected/actual |

## Residual risks (accepted)

1. Advisory job may stay red for multiple sprints until M12.2 — operators must not treat green `golden_matrix` as cross-repo parity.
2. Fork PRs without praxia checkout skip or fail advisory — acceptable for solo dev on monorepo/WSL layout.
3. Hook env wrapper parity deferred to M12.2 claude port — M12.1 tests document expected mismatch on manifest_minimal.

## Gate

**ACCEPT_WITH_NITS** — proceed to spec rev1 + **M12.1 sprint** (praxia `bundle-hash` + cisterna bridge).
