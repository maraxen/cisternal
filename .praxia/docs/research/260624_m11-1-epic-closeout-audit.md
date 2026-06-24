# Epic closeout audit — M11.1 Native-validate promotion (#2655)

**task_id:** `260624_epic-audit_m111`  
**closed_epic:** M11.1 native-validate promotion — required CI gate  
**depends_on:** M11 golden matrix (#2649), M4.3 subprocess validate lane  
**next_milestone:** M10.1 telemetry doctor CLI (#2650) or M3.1 (#2326)  
**date:** 2026-06-24  
**verdict:** **APPROVE**

## Shipped vs claimed

> **Note:** M11.1 deliverables verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M11.1-0 | PASS | `_native_cli_surface_digest` subprocesses `cisterna assets export`; no vendor CLI; module docstring states scope |
| AC-M11.1-1 | PASS | Job renamed `native-validate`; no `continue-on-error` in `export-dogfood.yml` |
| AC-M11.1-2 | PASS | CI runs self-manifest claude `--use-native-cli` names_only + `--emit-command-bodies` |
| AC-M11.1-3 | PASS | `test_native_cli_validate_self_manifest_names_only` + `_with_bodies` exit 0 |
| AC-M11.1-4 | PASS | manifest_minimal tests unchanged; 6/6 native validate tests green |
| AC-M11.1-5 | PASS | Module docstring + runbook CI table row documents subprocess parity |
| AC-M11.1-6 | PASS | `uv run pytest -q` → **376 passed**, 2 skipped (≥374) |

**Total:** 7/7 ACs satisfied on working tree.

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `.github/workflows/export-dogfood.yml` | Required `native-validate` job |
| `tests/test_cli_native_validate.py` | Self-manifest cases + docstring |
| `.praxia/docs/runbooks/cisterna-telemetry.md` | CI jobs table update |
| `.praxia/docs/specs/260624_m11-1-native-validate-promotion-for-cist.md` | Brainstorm spec + ACs |
| `.praxia/loop_state.toml` | Loop AUDIT → CLOSE |

## Regression status

```
uv run pytest tests/test_cli_native_validate.py -q → 6 passed
uv run pytest -q && uv run ruff check . → 376 passed, 2 skipped; All checks passed!
```

No product API changes. `cli.py` untouched.

## Pillar balance

| Pillar | Status post-M11.1 |
|--------|-------------------|
| Export trust (M4–M11) | Digest matrix (M11) + subprocess parity (M11.1) both required in CI |
| Telemetry (M5–M10) | Unchanged |
| Operator docs | Runbook CI table reflects blocking native-validate |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M11.1 artifacts uncommitted | P1 | Commit before treating epic shipped |
| Separate CI job vs dogfood merge | P3 | M11.1-B runner-up; extra job startup cost |
| Flaky `test_raising_exporter_swallowed` | P3 | #238; not bundled |
| dogfood native validate | P3 | Deferred M11.2 |

## Next epic candidates

| Candidate | Rationale |
|-----------|-----------|
| **M10.1** doctor CLI (#2650) | Operator UX; both export-trust lanes now required |
| **#238** flaky test fix | Quick debt; observed in M11 audit |
| **M3.1** (#2326) | PI-gated; separate brainstorm |

## Verdict rationale

**APPROVE** — Minimal scoped promotion completes M4.3 intent; CI job blocking without external deps; unit tests mirror CI on self-manifest; export-trust pillar fully gated (golden_matrix + native-validate).
