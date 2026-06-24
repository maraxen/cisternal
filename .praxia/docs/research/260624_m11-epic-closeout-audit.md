# Epic closeout audit — M11 Export hardening II (#2649)

**task_id:** `260624_epic-audit_m11`  
**closed_epic:** M11 Export hardening II — golden matrix pytest gate  
**depends_on:** M4 export trust (validate_golden resolver, export-dogfood CI)  
**next_milestone:** M11.1 native-validate promotion (runner-up) or M10.1 telemetry doctor CLI  
**date:** 2026-06-24  
**verdict:** **APPROVE**

## Shipped vs claimed

> **Note:** M11 deliverables verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M11-0 | PASS | `GOLDEN_MATRIX_CASES` in `tests/test_golden_matrix.py` — 15 tuples (3 manifests × 5 modes) |
| AC-M11-0b | PASS | `pyproject.toml` marker `golden_matrix: export trust digest matrix (M11)` |
| AC-M11-1 | PASS | `load_asset_report`, conflicts/warnings asserts, `surface_digest` vs `golden_digest_path`, slug in failure msg |
| AC-M11-2 | PASS | 15 `digest.sha256` files on disk under `tests/golden/` |
| AC-M11-3 | PASS | Matrix includes `tests/fixtures/manifest_minimal/manifest.toml` (legacy slug) |
| AC-M11-4 | PASS | `export-dogfood.yml` required step `pytest -m golden_matrix -q`; shell validate loops removed |
| AC-M11-4b | PASS | Golden matrix step precedes `minimal_emitter` install |
| AC-M11-5 | PASS | ruff, full pytest, shadow, dry-run export, minimal_emitter retained |
| AC-M11-6 | PASS | Module docstring documents `write_golden_digest` refresh workflow |
| AC-M11-7 | PASS | No `skip`/`xfail` in `test_golden_matrix.py` |
| AC-M11-8 | PASS | `test_export_regression_m32.py` slimmed to registry-dispatch smoke; matrix owns goldens |
| AC-M11-9 | PASS | `uv run pytest -q` → **374 passed** (≥359 baseline) |

**Total:** 12/12 ACs satisfied on working tree.

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `tests/test_golden_matrix.py` | M11 deliverable — 15-tuple matrix |
| `tests/test_export_regression_m32.py` | M32 dedupe |
| `.github/workflows/export-dogfood.yml` | CI gate migration |
| `pyproject.toml` | `golden_matrix` marker |
| `.praxia/docs/specs/260624_m11-export-hardening-ii-for-cisterna-exp.md` | Brainstorm + rev1 ACs |
| `.praxia/docs/designs/260624_m11-export-hardening-ii_design.md` | Staff design + adversarial |
| `.praxia/loop_state.toml` | Loop AUDIT → CLOSE |
| `.praxia/loop_triage_cache.json` | Prior triage (housekeeping) |

## Regression status

```
uv run pytest -m golden_matrix -q → 15 passed
uv run pytest -q && uv run ruff check . → 374 passed, 2 skipped; All checks passed!
```

One transient failure observed during audit (`test_core.py::TestNeverRaise::test_raising_exporter_swallowed`); passes in isolation and on re-run — matches open debt **#238** (flaky test).

No frozen API changes. `validate_golden.py` and `cli.py` untouched.

## Pillar balance

| Pillar | Status post-M11 |
|--------|-----------------|
| Export trust (M4) | CI now pytest-matrix gated across legacy + dogfood + self manifests |
| Telemetry (M5–M10) | Unchanged; shadow step retained in export-dogfood |
| Operator docs | M10 runbook unchanged; golden refresh in test module docstring |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M11 artifacts uncommitted | P1 | Commit before treating epic shipped |
| Flaky `test_raising_exporter_swallowed` | P3 | #238; unrelated to M11 |
| Native validate still advisory | P3 | M11.1 runner-up |
| No CI doc-check for golden refresh | P3 | Pre-mortem mitigated by AC-M11-6 docstring |

## Next epic candidates

| Candidate | Rationale |
|-----------|-----------|
| **M11.1** native-validate promotion | M11 runner-up; vendor CLI parity |
| **M10.1** telemetry doctor CLI | Operator ergonomics |
| **M3.1** file manifest (#2326) | PI-gated; separate brainstorm |

## Verdict rationale

**APPROVE** — Parameterized golden matrix closes the M6–M10 deferred export-trust gap; adversarial nits (load path, structural checks, CI order) all landed; 15/15 matrix green; net +15 tests with M32 dedupe; export-dogfood shell loops correctly retired.
