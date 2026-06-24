---
session_id: ff7f9874
topic: M11.1 native-validate promotion for cisterna — promote export-dogfood native-validate-advisory job to required; complete M4.3 subprocess parity lane for claude self-manifest. What should M11.1 optimize for: CI env requirements, surface coverage, failure modes, or bundling with flaky test #238 fix?
task_type: constrained-technical
winner: M11.1-A+C+D: Promote native-validate-advisory to required (remove continue-on-error); keep self-manifest claude names_only + with_command_bodies steps; extend test_cli_native_validate.py with SELF_MANIFEST cases mirroring CI
created_at: 2026-06-24T03:14:46.680794+00:00
---

# M11.1 native-validate promotion for cisterna

> **Shipped:** Job `native-validate` is blocking (promoted from `native-validate-advisory`).
> See [CI promotion status](260623_ci-promotion-status.md).

## Problem Frame
confirmed — with recon amendment: --use-native-cli is subprocess cisterna export (not vendor Claude CLI), so CI has no external binary dependency. Frame stands.

## Idea Pool
- [ai] M11.1-A Required job flip: remove continue-on-error from native-validate-advisory; rename to native-validate (required).
- [ai] M11.1-B Merge into dogfood job: native validate steps after golden_matrix in single job.
- [ai] M11.1-C Self-manifest claude names_only + with_command_bodies on .praxia/manifest.toml.
- [ai] M11.1-D Extend test_cli_native_validate.py with self_manifest cases.
- [ai] M11.1-E pytest marker @native_validate for explicit CI/local gate.
- [ai] M11.1-F Runbook note: --use-native-cli = subprocess cisterna export parity.
- [ai] M11.1-G Bundle #238 flaky test fix.
- [ai] M11.1-H Defer dogfood native validate to M11.2.
- [user] PEGS: Process = validate with --use-native-cli spawns subprocess export, hashes files, compares golden. Events = CI advisory job passes silently, promotion makes failure blocking. Goals = catch subprocess/export path drift golden_matrix misses. States = advisory job exists with self-manifest claude×2; unit tests cover manifest_minimal only. Components = export-dogfood.yml native-validate-advisory, test_cli_native_validate.py, cli._native_cli_surface_digest. Constraints = no vendor CLI dep (subprocess only). Assumption = self-manifest sufficient for promotion scope.
- [user] converge. Leading: M11.1-A+C+D — required CI flip on self-manifest claude×2 plus unit tests for .praxia/manifest.toml. Risk: subprocess slower/flakier than in-process — mitigated by existing advisory green history. Runner-up: M11.1-B merge into dogfood job (simpler ops, single required check).

## Decision Log
- [DEFER] M11.1-B Merge into dogfood job: Runner-up; fewer jobs but couples failure modes — defer unless A causes duplicate CI cost pain
- [DEFER] M11.1-E pytest native_validate marker: Overkill for 2 CLI invocations; CI shell steps sufficient
- [ACCEPT] M11.1-A+C+D Required flip + self-manifest CI + unit tests: Minimal change completing M4.3; tests close manifest_minimal vs self-manifest gap

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem: self-manifest grew large; subprocess native validate became slow/flaky on CI; someone re-added continue-on-error. Mitigation: AC time budget note; AC forbids continue-on-error on required job; optional #238 bundle if flake appears in native path.

I: pass N: pass V: pass E: pass S: pass T: pass
**AI:** _not recorded_

## Acceptance Criteria

**AC-M11.1-0 (scope):** `--use-native-cli` validates subprocess `cisterna assets export` parity (not vendor IDE CLIs). No new external CI dependencies.

**AC-M11.1-1 (CI required):** `native-validate-advisory` job in `export-dogfood.yml` has **no** `continue-on-error: true`; job renamed to `native-validate` (or equivalent required name).

**AC-M11.1-2 (CI steps):** Required job runs both:
- `cisterna assets validate --manifest .praxia/manifest.toml --surface claude --use-native-cli`
- same with `--emit-command-bodies`

**AC-M11.1-3 (unit tests):** `tests/test_cli_native_validate.py` adds self-manifest cases mirroring AC-M11.1-2 (names_only + with_command_bodies); exit 0.

**AC-M11.1-4 (parity):** Existing manifest_minimal native tests remain green (no regression).

**AC-M11.1-5 (runbook):** One-line clarification in `cisterna-telemetry.md` export section OR `test_cli_native_validate.py` module docstring: `--use-native-cli` = subprocess export digest parity.

**AC-M11.1-6 (baseline):** `uv run pytest -q` ≥ 374 passed after M11.1.

## Deferred (optional bundle)
- M11.1-B: Merge native steps into dogfood job
- M11.1-G: Flaky test #238 fix
- M11.1-H: dogfood_praxia native validate
