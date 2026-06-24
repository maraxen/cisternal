---
session_id: bdc45ba0
topic: M7.2 OTLP collector CI promotion
task_type: constrained-technical
winner: M7.2-A+B+C+D+E — rename otlp-collector required; separate job; integration pytest; runbook blocking; pinned collector + ready loop
runner_up: M7.2-G merge otlp docker steps into dogfood job
backlog_id: 2658
depends_on: M7.1 (#2627)
created_at: 2026-06-24T04:45:00+00:00
design: .praxia/docs/designs/260624_m7-2-otlp-collector-ci-promotion_design.md
---

# Brainstorm: M7.2 OTLP collector CI promotion

> **Shipped:** Job `otlp-collector` is blocking (`1ef43af`). See
> [CI promotion status](260623_ci-promotion-status.md).

## Problem Frame

Promote `otlp-collector-advisory` in `export-dogfood.yml` to a **required** blocking job — last soft CI lane after M10.3 doctor preflight and M11.1 native-validate.

**Fixed:** Keep separate docker job (M11.1-B precedent); integration tests skip locally without collector; pinned collector image; existing grpc+HTTP smoke tests.

**Negotiable:** fail-on-skip env (M7.2-F deferred); workflow retry on docker pull.

## Winner

**M7.2-A+B+C+D+E:** Remove `continue-on-error: true`; rename job `otlp-collector`; keep docker start + `pytest tests/test_otlp_http.py -m integration -q`; update runbook CI table to blocking.

## Check severity / CI contract

| Step | Fail job when |
|------|----------------|
| Docker start | Collector not listening on 4317 within 30s |
| Integration pytest | Any test failure (not skip when collector up) |
| Cleanup | `always()` docker rm (non-blocking) |

## Pre-mortem

- Docker Hub rate limit → pinned `0.109.0`; mirror deferred
- Silent skip on port race → M7.2-F deferred unless observed
- Re-add `continue-on-error` → AC forbids

## Acceptance Criteria (rev1)

**AC-M7.2-0 (scope):** Promotion only — no OTLP protocol or exporter code changes unless required for CI green.

**AC-M7.2-1 (required job):** `export-dogfood.yml` job `otlp-collector-advisory` renamed to `otlp-collector` with **no** `continue-on-error: true`.

**AC-M7.2-2 (steps parity):** Required job retains M7.1 steps: docker run pinned collector, ready loop, integration pytest, `always()` cleanup.

**AC-M7.2-2b (dual-port ready):** Ready loop must verify **both** gRPC **4317** and HTTP **4318** are accepting connections before integration pytest (not gRPC-only).

**AC-M7.2-3 (integration tests):** `uv run pytest tests/test_otlp_http.py -m integration -q` runs in required job (grpc + http smoke).

**AC-M7.2-4 (local dev):** Default `uv run pytest -q` unchanged — integration tests still skip without local collector.

**AC-M7.2-5 (runbook):** `cisterna-telemetry.md` Related CI jobs + OTLP smoke section mark `otlp-collector` as **blocking**.

**AC-M7.2-6 (forbidden):** No `continue-on-error` on `otlp-collector` job (grep CI workflow).

**AC-M7.2-7 (baseline):** `uv run pytest -q` ≥ 399 passed, 2 skipped.

## Reconciliation log (adversarial → rev1)

| Finding | Resolution |
|---------|------------|
| CH-001 dual-port ready | AC-M7.2-2b verify 4317 + 4318 |
| CH-002 skip passes job | Mitigated by dual-port; M7.2-F deferred |
| CH-003 docker hub flake | Accepted; pinned image |
| CH-004 runbook drift | AC-M7.2-5 both sections |
| CH-005 no yaml unit test | Epic audit grep |

## Deferred

- M7.2-F `CISTERNA_OTLP_INTEGRATION_REQUIRED` fail-on-skip
- Merge otlp into dogfood job
- Docker Hub mirror / workflow retry

## INVEST

I: pass · N: pass · V: pass · E: pass · S: pass · T: pass
