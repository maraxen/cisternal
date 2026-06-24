# Adversarial review — M7.2 OTLP collector CI promotion (#2658)

**date:** 2026-06-24  
**spec:** `.praxia/docs/specs/260624_m7-2-otlp-collector-ci-promotion-promote.md` (rev1)  
**design:** `.praxia/docs/designs/260624_m7-2-otlp-collector-ci-promotion_design.md`  
**precedent:** M11.1 native-validate promotion  
**verdict:** **ACCEPT_WITH_NITS**

## Summary

M7.2 is a **workflow-only promotion** mirroring M11.1: remove `continue-on-error`, rename job, update runbook. No exporter code changes. Blast radius is CI merge gating on docker + 2 integration smokes.

## Findings → reconciliation

| ID | Sev | Challenger | Synthesis |
|----|-----|------------|-----------|
| **CH-001** | MAJOR | Ready loop only probes **4317**; HTTP smoke needs **4318** — port race could yield skipped HTTP test while job passes | **Fixed** — AC-M7.2-2b: ready loop must verify **both** 4317 and 4318 before pytest |
| **CH-002** | MAJOR | Integration tests **skip** when ports closed; required job could pass with 2 skipped if docker step regresses | **Mitigated** by CH-001; defer `CISTERNA_OTLP_INTEGRATION_REQUIRED` / `--fail-skips` unless observed post-promotion |
| **CH-003** | MINOR | Docker Hub pull flake blocks all PRs after promotion | **Accepted** — pinned `0.109.0`; workflow retry deferred |
| **CH-004** | MINOR | Runbook has **two** references to `otlp-collector-advisory` (OTLP smoke + CI table) | **Fixed** — AC-M7.2-5 names both sections |
| **CH-005** | MINOR | No unit test guards workflow YAML | **Nit** — epic audit greps `continue-on-error` absent on `otlp-collector` job (M11.1 used audit-only too) |
| **CH-006** | INFO | Merge into dogfood rejected | **Accepted** — steelman recorded in brainstorm; separate job isolates docker flake |

## Scope check

| In scope | Out of scope |
|----------|----------------|
| `export-dogfood.yml` rename + flip | OTLP protocol / exporter code |
| Runbook CI table + OTLP smoke paragraph | `CISTERNA_OTLP_INTEGRATION_REQUIRED` |
| Dual-port ready loop hardening | Docker Hub mirror |
| Baseline pytest unchanged locally | Merge otlp into dogfood |

## Residual risks (accepted)

1. **Docker daemon** intermittent on `ubuntu-latest` — monitor after promotion; re-advisory only if flake rate spikes.
2. **Skipped integration path** — if both ports verified, tests should execute not skip; watch first week of required job.
3. **M7.1 spec** still says "advisory" — update cross-ref in implementation commit or docs hygiene follow-up.

## Gate

**ACCEPT_WITH_NITS** — proceed to **`go m7.2`**.
