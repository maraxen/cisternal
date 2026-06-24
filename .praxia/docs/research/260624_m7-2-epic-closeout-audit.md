# Epic closeout audit — M7.2 OTLP collector CI promotion (#2658)

**task_id:** `260624_epic-audit_m72`  
**closed_epic:** M7.2 OTLP collector CI promotion  
**depends_on:** M7.1 OTLP HTTP + collector CI (#2627)  
**date:** 2026-06-24  
**verdict:** **APPROVE**

## Shipped vs claimed

> **Note:** M7.2 deliverables verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M7.2-0 | PASS | Workflow, runbook, tests only — no `src/cisterna` OTLP code changes |
| AC-M7.2-1 | PASS | Job `otlp-collector`; `otlp-collector-advisory` absent from workflow |
| AC-M7.2-2 | PASS | Docker run `0.109.0`, integration pytest, `always()` `docker rm` |
| AC-M7.2-2b | PASS | Ready loop: `nc -z localhost 4317 && nc -z localhost 4318` |
| AC-M7.2-3 | PASS | `uv run pytest tests/test_otlp_http.py -m integration -q` in job |
| AC-M7.2-4 | PASS | `uv run pytest -q` → 2 integration skips without local collector |
| AC-M7.2-5 | PASS | Runbook L222 (OTLP smoke) + L318 (CI table) — blocking `otlp-collector` |
| AC-M7.2-6 | PASS | No `continue-on-error` in `.github/`; `test_otlp_collector_job_is_required` |
| AC-M7.2-7 | PASS | **401 passed**, 2 skipped (≥399) |

**Total:** 9/9 ACs satisfied on working tree.

### Adversarial reconciliation

| ID | Status | Evidence |
|----|--------|----------|
| CH-001 dual-port ready | **LANDED** | Workflow L66-67; `test_otlp_collector_ready_loop_checks_both_ports` |
| CH-002 skip passes job | **MITIGATED** | Dual-port ready; M7.2-F deferred |
| CH-003 docker hub flake | **ACCEPTED** | Pinned image unchanged |
| CH-004 runbook drift | **LANDED** | Both sections updated |
| CH-005 yaml guard | **LANDED** | `tests/test_workflow_export_dogfood.py` (+2 tests) |

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `.github/workflows/export-dogfood.yml` | M7.2 deliverable |
| `.praxia/docs/runbooks/cisterna-telemetry.md` | Blocking CI docs |
| `tests/test_workflow_export_dogfood.py` | Workflow contract tests |
| `.praxia/docs/specs/260624_m7-2-otlp-collector-ci-promotion-promote.md` | Spec rev1 |
| `.praxia/docs/designs/260624_m7-2-otlp-collector-ci-promotion_design.md` | Design + adversarial |
| `.praxia/docs/research/260624_m7-2-adversarial-review.md` | Adversarial memo |
| `.praxia/loop_state.toml` | Loop bookkeeping |

## Regression status

```
uv run pytest tests/test_workflow_export_dogfood.py -q → 2 passed
uv run pytest tests/test_otlp_http.py -q → 7 passed, 2 skipped
uv run pytest -q → 401 passed, 2 skipped
rg continue-on-error .github → no matches
```

## CI landscape post-M7.2

| Job | Workflow | Blocking? |
|-----|----------|-----------|
| `dogfood` | `export-dogfood.yml` | Yes |
| `native-validate` | `export-dogfood.yml` | Yes |
| `otlp-collector` | `export-dogfood.yml` | **Yes** (new) |

**No advisory jobs remain** in `export-dogfood.yml`. M7 egress verification loop closed in CI.

## Pillar balance

| Pillar | Status post-M7.2 |
|--------|-------------------|
| Telemetry egress (M7–M7.2) | **Complete** — protocol + integration + required CI |
| Telemetry operator (M10–M10.3) | Complete |
| Export trust (M11–M11.1) | Complete |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M7.2 uncommitted | P1 | Commit before treating epic shipped |
| Docker Hub / daemon flake | P3 | Monitor first week of required job |
| M7.2-F fail-on-skip | P3 | Deferred unless CI passes with skips |
| M7.1 spec still says "advisory" | P3 | Historical doc; optional hygiene update |
| M10 spec AC-M10-8 advisory wording | P3 | Same |

## Next epic candidates

| Candidate | Rationale |
|-----------|-----------|
| **Commit + triage** | Close M7.2 loop |
| **M10.4** `--consumer` doctor filter | Post-M10.2 deferred |
| **M12** Rust bridge / praxia-agent-assets parity | Large; PI-gated |
| **#240** PCW template | Out of cisterna scope |

## Verdict rationale

**APPROVE** — Minimal promotion mirrors M11.1; adversarial dual-port ready landed; workflow contract tests prevent regression to advisory; all `export-dogfood` jobs now blocking. Residual risk is docker infrastructure flake only.
