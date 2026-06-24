# CI job promotion status — export-dogfood.yml

**task_id:** `260623_docs-hygiene-2712`  
**backlog:** #2712  
**date:** 2026-06-23  
**workflow:** `.github/workflows/export-dogfood.yml`

Canonical mapping from **advisory** (historical spec wording) to **blocking** (current CI). Historical sprint plans and closeout memos are point-in-time records and are not rewritten.

## Current blocking jobs

| Job | Blocking | Introduced | Notes |
|-----|----------|------------|-------|
| `dogfood` | Yes | M4 | pytest, ruff, golden_matrix, shadow, dry-run export |
| `native-validate` | Yes | M11.1 → M11.2 | self-manifest `--use-native-cli` × 4 surfaces + claude bodies |
| `otlp-collector` | Yes | M7.2 | docker collector + OTLP integration smoke |
| `rust-parity` | Yes | M12.4 | praxia `bundle-hash` pin + rust-parity pytest suite |

No `continue-on-error` on any export-dogfood job (verified by `tests/test_workflow_export_dogfood.py`).

## Promotion history

| Epic | Advisory name (spec) | Blocking name (shipped) | Commit |
|------|----------------------|-------------------------|--------|
| M4 → M11.1 | `native-validate-advisory` | `native-validate` | M11.1 promotion |
| M7.1 → M7.2 | `otlp-collector-advisory` | `otlp-collector` | `1ef43af` |
| M12.1 → M12.4 | `rust-parity-advisory` | `rust-parity` | `5e05e87` |

## Dual-lane export trust (M12+)

| Lane | Gate | Golden path |
|------|------|-------------|
| Python-canonical | `dogfood` → `golden_matrix` | `tests/golden/{slug}/` |
| Rust byte parity | `rust-parity` job | `tests/golden/rust_parity/` + conformance fixtures |

Default `cisterna assets validate` remains Python-canonical; `--rust-parity` uses praxia subprocess digest.

## Operator reference

Primary runbook: `.praxia/docs/runbooks/cisterna-telemetry.md` (CI table § export-dogfood).

## Specs updated by #2712

- `260624_m7.1-otlp-http-buildable-spec-rev1.md`
- `260624_m10-operator-runbook-for-cisterna-docume.md`
- `260624_m12-export-rust-bridge-buildable-spec-rev1.md`
- `260624_m12-export-rust-bridge_design.md`
