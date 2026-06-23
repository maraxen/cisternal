# Epic closeout audit — M4 Export Trust (#2597)

**task_id:** `260623_epic-audit_m4`  
**closed_epic:** #2597 M4 Export Trust — dogfood CI, manifest goldens, example emitter  
**children:** M4.1a (#2598), M4.1b (#2599), M4.4 (#2600), M4-GOLDEN (#2601), M4.2 (#2602), M4.3 (#2603)  
**depends_on:** #2581 M3.3  
**next_milestone:** UNVERIFIED — no M5 epic registered; brainstorm winner deferred telemetry (FACTION-C)  
**date:** 2026-06-23

## Shipped vs claimed

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M4-0 | PASS | `uv run pytest -q` → 307 passed; `uv run ruff check .` clean |
| AC-M4-0b | PASS | `git diff` empty on `tests/golden/{claude,cursor,copilot,antigravity}/` |
| AC-M4-0c | PASS | New trees `self_manifest/`, `dogfood_praxia/` introduced in this epic (documented here) |

### M4.1a — self-manifest (#2598)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M4-1a | PASS | `tests/test_self_manifest.py::test_self_manifest_loads_clean` |
| AC-M4-1b | PASS | `tests/test_self_manifest.py::test_self_manifest_inspect_metadata_name` |

### M4.1b — praxia dogfood fixture (#2599)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M4-1c | PASS | `tests/test_dogfood_praxia_fixture.py::test_dogfood_praxia_fixture_richness` |
| AC-M4-1d | PASS | `tests/test_dogfood_praxia_fixture.py::test_dogfood_missing_workflow_validate_exits_one` |

### M4-GOLDEN — manifest-scoped goldens (#2601)

| AC | Status | Evidence |
|----|--------|----------|
| Resolver | PASS | `src/cisterna/assets/validate_golden.py::resolve_golden_slug`; `tests/test_validate_golden_resolver.py` |
| Self goldens | PASS | `tests/golden/self_manifest/` (5 digest files) |
| Dogfood goldens | PASS | `tests/golden/dogfood_praxia/` (5 digest files) |
| Fail closed | PASS | `tests/test_validate_golden_resolver.py::test_unknown_manifest_raises` |
| CLI wiring | PASS | `src/cisterna/cli.py` passes manifest to `golden_digest_path` |

### M4.2 — dogfood CI (#2602)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M4-2a | PASS | `.github/workflows/export-dogfood.yml` — `ubuntu-latest`, `uv sync`, `uv run` |
| AC-M4-2b | PASS | Workflow lines 19–24; manual verify all four surfaces exit 0 |
| AC-M4-2c | PASS | Workflow lines 25–28 |
| AC-M4-2d | PASS | Workflow lines 29–34 |
| AC-M4-2e | PASS | Workflow lines 35–38 |
| AC-M4-2f | PASS | Required job has no `continue-on-error` |
| AC-M4-2g | PASS | `pytest` + validate steps precede `uv pip install -e` (lines 18–41) |

### M4.3 — subprocess validate (#2603)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M4-3a | PASS | `tests/test_cli_native_validate.py::test_native_cli_validate_claude_names_only` |
| AC-M4-3b | PASS | `tests/test_cli_native_validate.py::test_native_cli_matches_in_process_digest` |
| AC-M4-3c | PASS | ≥3 tests in `tests/test_cli_native_validate.py` |
| AC-M4-3d | PASS | `native-validate-advisory` job `continue-on-error: true` |
| AC-M4-3e | PASS | `tests/test_cli_native_validate.py::test_native_cli_zero_files_exits_one` |

### M4.4 — example emitter (#2600)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M4-4a | PASS | `uv pip install -e examples/minimal_emitter` succeeds |
| AC-M4-4b | PASS | `examples/minimal_emitter/tests/test_emitter.py::test_minimal_surface_registered` |
| AC-M4-4c | PASS | `examples/minimal_emitter/tests/test_emitter.py::test_minimal_emitter_emits_file` |
| AC-M4-4d | PASS | CI step after AC-M4-2g ordering |
| AC-M4-4e | PASS | `examples/minimal_emitter/README.md` |

**Total:** 22/22 acceptance criteria cited across six children.

## Parallel wave verification

| Track | Module ownership | Merge conflict |
|-------|------------------|----------------|
| M4.1a | `.praxia/**` | None |
| M4.1b | `tests/fixtures/manifest_dogfood_praxia/**` | None |
| M4.4 | `examples/minimal_emitter/**` | None |
| M4-GOLDEN | `validate_golden.py`, `cli.py`, new golden trees | Serialized `cli.py` after golden |
| M4.3 | `test_cli_native_validate.py` | None |
| M4.2 | `.github/workflows/export-dogfood.yml` | None |

## Git delta (M4 epic)

**Uncommitted on working tree** (implementation session; not yet committed to `main`):

- New: `.praxia/manifest.toml` + asset tree, `manifest_dogfood_praxia/` fixture, `examples/minimal_emitter/`
- New: `tests/golden/{self_manifest,dogfood_praxia}/`, M4 test modules
- Changed: `validate_golden.py` (manifest-scoped resolver), `cli.py` (golden + native guard)
- New: `.github/workflows/export-dogfood.yml`
- Changed: `pyproject.toml` (`testpaths = ["tests"]`)

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 307 passed; All checks passed!

uv pip install -e examples/minimal_emitter && uv run pytest examples/minimal_emitter/tests/ -q
→ 2 passed
```

Baseline at M3.3 closeout: 296 tests. Net **+11** for M4 epic.

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| `minimal_emitter` pollutes dev venv | P3 | After `pip install -e examples/minimal_emitter`, M3.2 registry exact-count tests fail until uninstall; CI ordering prevents this |
| Vendor IDE validators (TBD-1) | deferred | Subprocess parity only; no Claude Code `plugin validate` |
| Debt #238 flaky test | P3 | Pre-existing |
| No M5 epic registered | triage | Telemetry brainstorm runner-up deferred |
| M4 code uncommitted | process | PI should commit before merge |

## Export trust scope delivered

| Capability | Status |
|------------|--------|
| Self-manifest dogfood | Shipped |
| Praxia-scale fixture | Shipped |
| Manifest-scoped golden validate | Shipped |
| Required CI dogfood workflow | Shipped |
| Advisory native subprocess lane | Shipped |
| Third-party entry-point example | Shipped |

## Verdict

**VERIFY: APPROVE** — M4 parent DoD satisfied (22/22 ACs). Route to **TRIAGE** for M5 milestone selection (telemetry per brainstorm deferral).
