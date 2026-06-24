# Adversarial review — M12.4 blocking promotion (#2665)

**date:** 2026-06-23  
**sprint:** `.praxia/sprint_plans/260623_m12-4-blocking-promotion.toml`  
**spec:** `.praxia/docs/specs/260624_m12-export-rust-bridge-buildable-spec-rev1.md` (AC-M12-4)  
**predecessor:** M12.3 `25e1b8c`  
**verdict:** **ACCEPT_WITH_NITS**

## Summary

M12.4 is the correct closeout for #2665: flip one CI flag, rename the job for clarity, sync workflow contract tests and runbook, audit the epic. No emitter code. Blast radius is small **if** workflow test and YAML land atomically.

Main risks: **spec literal vs minimal scope** on “matrix rust_parity tuples,” **fork PR fragility** on cross-repo checkout, and **CI breakage** if w1 merges without w2 in the same PR.

---

## Findings → reconciliation

| ID | Sev | Challenger | Defender | Synthesis |
|----|-----|------------|----------|-----------|
| **CH-401** | MAJOR | Spec **AC-M12-4** says blocking when “conformance + **matrix** rust_parity tuples green”; plan defers dogfood/self rust_parity goldens | PM triage locked minimal promotion; legacy slug × 4 surfaces green | **Fixed** — interpret AC-M12-4 minimal: “matrix” = conformance matrix (4 surfaces × manifest_minimal) + `tests/golden/rust_parity/legacy/`; document carve-out in M12.4 closeout audit; optional follow-up epic for slug expansion |
| **CH-402** | MAJOR | Blocking `rust-parity` checks out `maraxen/praxia` — **fork PRs** may fail the workflow | Accepted in M12.1 (CH-004); solo/monorepo dev | **Accepted** — note in closeout; same as OTLP docker dependency pattern; no code fix in M12.4 |
| **CH-403** | **BLOCKER** | **w1 alone breaks CI:** `dogfood` runs full `pytest -q`; `test_rust_parity_advisory_job_is_non_blocking` asserts old job name + `continue-on-error: true` | Sequential w1→w2 in sprint | **Fixed** — **w1 and w2 MUST ship in one PR** (or w1 fixer owns `test_workflow_export_dogfood.py` in same commit). Amend sprint orchestration: `sequential = ["w1_w2_atomic", "w3closeout"]` |
| **CH-404** | MAJOR | Promoting to blocking without **GHA smoke** on `main` — local green ≠ Actions green (cargo cache, praxia checkout) | First push after merge is the proof | **Fixed** — w3 closeout: record “verify first green `rust-parity` job on main” as operator checklist; optional: run `act` locally if available |
| **CH-405** | MINOR | `test_cli_rust_parity.py` not in `rust-parity` job pytest line | CLI tests need app import; subprocess covered in job via `test_rust_parity.py` | **Accepted** — optional nit: add to job pytest line in w1 for belt-and-suspenders |
| **CH-406** | MINOR | Optional **pin bump** `04bb683` → `81bff16` bundled with promotion | Tracing-only praxia change | **Fixed** — move pin bump to **separate commit after** blocking promotion verified, or drop from M12.4 |
| **CH-407** | MINOR | Job rename `rust-parity-advisory` → `rust-parity` breaks AC-M12-1k literal wording in spec | Job behavior unchanged | **Accepted** — closeout audit maps old→new name; no spec rev required |
| **CH-408** | INFO | Dual-lane model still confusing: `golden_matrix` Python + `rust-parity` Rust | Runbook paragraph in w2 | **Fixed** — already in w2 plan |
| **CH-409** | INFO | Default `validate` flip deferred per design oracle | Correct | **Accepted** |
| **CH-410** | INFO | Epic #2665 backlog item not explicitly `complete` in w3 | closeout audit | **Fixed** — w3: mark epic complete in audit + triage cache |

---

## Scope check

| In M12.4 | Out M12.4 |
|----------|-----------|
| Remove `continue-on-error` | `golden_matrix` digest changes |
| Rename job → `rust-parity` | `rust_parity` goldens for dogfood_praxia / self_manifest |
| Workflow test flip | Default `validate` rust parity |
| Runbook + README | Registry `rust_parity` kwarg |
| Epic #2665 closeout | PyO3 / maturin |

---

## Edge-case matrix (M12.4)

| Condition | Expected after M12.4 |
|-----------|----------------------|
| `rust-parity` job fails on PR | **Whole workflow fails** (was advisory pass) |
| Fork PR without praxia access | `rust-parity` job fails — may block merge |
| `dogfood` pytest on PR | In-process rust parity tests run **without** bin (subprocess tests skip) |
| `rust-parity` job | Full parity suite **with** bin (subprocess + in-process) |
| w1 merged without workflow test update | **`dogfood` pytest red** — forbidden |

---

## Sprint amendments (required before implement)

1. **Merge w1 + w2** into single implement slice or single PR — workflow YAML + `test_workflow_export_dogfood.py` + docstrings/README/runbook together.
2. **Drop optional pin bump** from w1 — defer to post-promotion follow-up.
3. **w3 closeout** — document AC-M12-4 minimal interpretation (CH-401); operator checklist for first green GHA run (CH-404).

---

## Residual risks (accepted)

1. Two blocking export lanes (`golden_matrix` Python vs `rust-parity` Rust) — operators must know which gate applies.
2. Cross-repo pin drift: praxia emitter change without cisterna pin bump breaks blocking CI (intentional tripwire).
3. Fork contributors may need maintainer re-run or monorepo layout.

---

## Gate

**ACCEPT_WITH_NITS** — proceed to **`go m12.4`** with atomic w1+w2 and amendments above.
