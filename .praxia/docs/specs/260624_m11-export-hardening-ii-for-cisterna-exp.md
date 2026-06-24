---
session_id: e1186493
topic: M11 Export hardening II for cisterna — expand multi-emitter validate_golden matrix + CI gate. M4 shipped manifest-scoped golden resolver for claude/cursor/copilot/antigravity; deferred since M6–M10 while telemetry arc ran. Backlog #2649. What should M11 optimize for: which emitters/surfaces, CI strictness, native CLI parity, Rust bridge, or dogfood workflow?
task_type: constrained-technical
winner: M11-A+B+C: Parameterized pytest golden matrix — complete surface×manifest×mode tuples, fill golden gaps (dogfood claude bodies + legacy in matrix), consolidate export-dogfood CI to required `pytest -m golden_matrix` gate replacing shell validate loops
created_at: 2026-06-24T01:27:05.088284+00:00
adversarial_verdict: ACCEPT_WITH_NITS
design: .praxia/docs/designs/260624_m11-export-hardening-ii_design.md
---

# Brainstorm: M11 Export hardening II for cisterna — expand multi-emitter validate_golden matrix + CI gate. M4 shipped manifest-scoped golden resolver for claude/cursor/copilot/antigravity; deferred since M6–M10 while telemetry arc ran. Backlog #2649. What should M11 optimize for: which emitters/surfaces, CI strictness, native CLI parity, Rust bridge, or dogfood workflow?

## Problem Frame
Confirmed. Frame: M11 hardens export trust by making the emitter×manifest×mode golden matrix explicit, complete, and CI-enforced — building on M4 validate_golden without new surfaces or ABC changes. Fixed: fail-closed resolver, get_emitter registry, cisterna-only. Negotiable: pytest matrix vs workflow loops, legacy manifest inclusion, dogfood claude bodies golden, minimal_emitter plugin coverage, native CLI gate promotion from advisory.

## Idea Pool
- [ai] M11-A Parameterized pytest golden matrix: one test module enumerates surface×manifest_slug×mode tuples; replaces fragile CI shell loops with single `pytest -m golden` gate.
- [ai] M11-B Complete golden tree gaps: add dogfood_praxia/claude/with_command_bodies digest; verify self_manifest + dogfood_praxia have parity with export-dogfood workflow cases.
- [ai] M11-C CI consolidation: required `golden-matrix` job runs pytest matrix; export-dogfood keeps dogfood integration steps only (dry-run, minimal_emitter).
- [ai] M11-D Third-party emitter fixture: extend matrix to examples/minimal_emitter as plugin surface proving entry-point registry trust.
- [ai] M11-E Promote native-validate-advisory to required for claude×self_manifest (M4.3 completion).
- [ai] M11-F Operator golden refresh: document `write_golden_digest` workflow in runbook when .praxia/manifest changes.
- [ai] M11-G Declarative matrix manifest (YAML/TOML) listing tuples — tests and CI read same source of truth.
- [ai] M11-H Rust/native asset hashing bridge — defer (spike not sprint).
- [user] PEGS decomposition:
- [user] Processes: load manifest → AssetBundle → get_emitter(surface) → emit → surface_digest → compare golden sha256; CI export-dogfood runs cisterna assets validate in shell loops; pytest regression (test_export_regression_m32) only covers legacy/manifest_minimal (5 tuples).
- [user] Events: manifest change, emitter code change, golden drift on PR.
- [user] Goals: fail-closed drift detection; single source of truth for which tuples are gated; no duplicate shell vs pytest coverage gaps.
- [user] States: golden trees exist for legacy, dogfood_praxia, self_manifest (15 digest files); dogfood_praxia lacks claude/with_command_bodies; CI validates self+dogfood via CLI but not legacy manifest; native CLI parity advisory only.
- [user] Components: validate_golden.py, golden_digest_path/resolve_golden_slug, export-dogfood.yml, test_export_regression_m32.py, examples/minimal_emitter.
- [user] Constraints: no new surfaces; no Emitter ABC break; ~359 test baseline.
- [user] Assumption: M11 scope is matrix completeness + CI enforcement, not new export features.
- [user] converge

## Decision Log
- [DEFER] M11-H Rust/native asset hashing bridge: Out of scope for M11; no spike in this sprint
- [DEFER] M11-D Third-party minimal_emitter in matrix: Valuable but expands scope; defer to M11.1 unless trivial
- [DEFER] M11-E Promote native-validate to required: Runner-up; CI env dependency on vendor CLI
- [ACCEPT] M11-A + M11-B + M11-C bundled golden matrix pytest gate: Closes deferred gap: explicit tuples, complete digests, single required CI path

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem (6 months, failed): Engineers stopped updating goldens when .praxia/manifest.toml changed — matrix went red, someone `@pytest.mark.skip`ped legacy tuples or disabled the job. Mitigation in spec: AC-M11-6 documents refresh workflow; AC-M11-7 forbids skipping required tuples; matrix defined in code constant (not external YAML) to avoid dual-source drift.

Proceed to synthesis.
**AI:** _not recorded_

## Acceptance Criteria (rev1 — adversarially reconciled)

**AC-M11-0 (matrix constant):** `tests/test_golden_matrix.py` defines `GOLDEN_MATRIX_CASES` as a single in-code list of `(manifest_path, surface, emit_command_bodies)` tuples covering:
- `legacy` (`tests/fixtures/manifest_minimal/manifest.toml`): claude names_only + with_command_bodies, cursor, copilot, antigravity
- `dogfood_praxia` (`tests/fixtures/manifest_dogfood_praxia/manifest.toml`): same five tuples
- `self_manifest` (`.praxia/manifest.toml`): same five tuples  
Total: **15 tuples**.

**AC-M11-0b (marker):** `pyproject.toml` registers `golden_matrix: export trust digest matrix (M11)`.

**AC-M11-1 (parameterized test):** `@pytest.mark.golden_matrix` parameterized test:
1. `report = load_asset_report(manifest=path)` (same load path as `cli validate`)
2. Assert `report.conflicts == ()` and `report.warnings == ()`
3. `surface_digest(report.bundle, surface, emit_command_bodies=...)` vs `golden_digest_path(..., manifest=path)`
4. On mismatch, failure message includes manifest slug + surface + mode.

**AC-M11-2 (golden on-disk):** All 15 tuples have existing digest files under `tests/golden/`; if dogfood claude bodies drifts, refresh via `write_golden_digest` before merge.

**AC-M11-3 (legacy in CI parity):** Matrix includes legacy manifest — closes gap where export-dogfood shell loops skipped `manifest_minimal`.

**AC-M11-4 (CI gate):** `.github/workflows/export-dogfood.yml` runs `uv run pytest -m golden_matrix -q` as a **required** step; remove redundant shell `cisterna assets validate` loops once matrix is green.

**AC-M11-4b (CI order):** Golden matrix step runs **before** `uv pip install -e examples/minimal_emitter` (preserves M4 AC-M4-2g).

**AC-M11-5 (retain integration steps):** export-dogfood keeps dry-run export, minimal_emitter example test, shadow telemetry, ruff, full pytest — only validate loops replaced.

**AC-M11-6 (golden refresh doc):** Module docstring or comment in `test_golden_matrix.py`: when `.praxia/manifest.toml` or dogfood fixture changes, run `write_golden_digest` for affected tuples before merge.

**AC-M11-7 (no skips):** Required matrix tuples must not use `@pytest.mark.skip` or `xfail` without linked backlog item.

**AC-M11-8 (dedupe M32):** `test_export_regression_m32.py` no longer loops all five legacy goldens (owned by matrix); retains one AC-M32-7 registry-dispatch smoke or is folded into matrix with comment referencing M32.

**AC-M11-9 (test baseline):** `uv run pytest -q` count ≥ 359 after M11 (no net test deletion).

## Reconciliation log (adversarial → rev1)

| Finding | Resolution |
|---------|------------|
| CH-001 load path | AC-M11-1 uses `load_asset_report` |
| CH-002 structural checks | AC-M11-1 step 2 conflicts/warnings |
| CH-003 marker | AC-M11-0b |
| CH-004 stale gap | AC-M11-2 verify not assume missing |
| CH-005 M32 overlap | AC-M11-8 |
| CH-006 CI order | AC-M11-4b |

## Deferred (M11.1)
- M11-E: Promote `native-validate-advisory` to required
- M11-D: `minimal_emitter` third-party surface in matrix
- M11-H: Rust/native hashing bridge
