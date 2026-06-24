# Adversarial review — M12.3 emitter ports (#2665)

**date:** 2026-06-23  
**sprint:** `.praxia/sprint_plans/260623_m12-3-emitter-ports.toml`  
**recon:** `.praxia/docs/research/260623_m12-3-recon.md`  
**spec:** `.praxia/docs/specs/260624_m12-export-rust-bridge-buildable-spec-rev1.md` (AC-M12-3)  
**design:** `.praxia/docs/designs/260624_m12-export-rust-bridge_design.md`  
**predecessor:** M12.2 `093a54d`  
**verdict:** **ACCEPT_WITH_NITS**

## Summary

M12.3 is shippable as a cisterna-only mechanical port of three emitter wedges using the proven M12.2 pattern. Prototype digests already match conformance for all three surfaces. Blast radius is bounded: new `*_rust.py` modules, `rust_parity=True` on three emitters, `validate_golden` dispatch extension, advisory CI pytest expansion — **no** `golden_matrix` or default `validate` changes.

Main risks are **semantic divergence** (cursor agent omission, hook surface filter) and **test gaps** (CLI `--rust-parity` does not prove in-process emit; only pytest does). No blockers if nits land in sprint w4/w5.

---

## Findings → reconciliation

| ID | Sev | Challenger | Defender | Synthesis |
|----|-----|------------|----------|-----------|
| **CH-301** | MAJOR | Design §phasing says M12.3 surfaces **sequentially** (merge conflict); sprint runs w1∥w2∥w3 | Disjoint `FILES OWNED` per surface (`cursor.py` vs `copilot.py` vs `antigravity.py`) | **Fixed** — parallel OK **after** w0shared; each track must not touch other emitters or `validate_golden.py` until w4wire |
| **CH-302** | MAJOR | `validate --rust-parity` only exercises **subprocess** digest (see `cli.py:431–469`); does not call `surface_digest_rust_parity` | Subprocess is cross-repo oracle; in-process covered by pytest | **Fixed** — AC-M12-3f: **in-process** = `test_*_rust_parity.py`; **CLI** = subprocess self-consistency + conformance expected (unchanged from M12.1). Document in closeout audit |
| **CH-303** | MAJOR | Rust-parity **skips** `hooks_for_surface()`; legacy respects L15 (`test_export_hooks_surface.py`) | Locked recon decision; matches bridge→`bundle-hash` | **Fixed** — add `test_rust_parity_ignores_hook_surface_filter` in w4 (one surface sufficient); README note in w4wire |
| **CH-304** | MAJOR | Cursor rust-parity **omits** `agents/*.agent.md` while legacy emits them on `manifest_minimal` | Matches praxia `emit()` default (`agents_path_verified=false`) | **Accepted** — explicit legacy vs rust test in each surface file; README callout; residual operator confusion until M12.4 docs |
| **CH-305** | MAJOR | `test_rust_parity.py` already green for all 4 surfaces via subprocess — advisory CI could pass **without** Python emit ports | M12.3 value is in-process parity + `rust_parity` golden tree | **Fixed** — w4wire **must** add `test_*_rust_parity.py` to advisory job (already planned); closeout verifies advisory would **fail** if in-process tests removed |
| **CH-306** | MINOR | w4wire marks `get_emitter(rust_parity=…)` as **optional**; registry today ignores `rust_parity` (`registry.py:24–33`) | Direct `CursorEmitter(rust_parity=True)` works without registry | **Fixed** — w4: **require** explicit dispatch in `surface_digest_rust_parity` (mirror claude); registry extension deferred to M12.4 unless needed |
| **CH-307** | MINOR | `test_cli_rust_parity.py` only parametrizes **claude** | M12.1 scope was subprocess smoke | **Fixed** — w4wire: add parametrized CLI test for cursor/copilot/antigravity on `manifest_minimal` |
| **CH-308** | MINOR | w0shared refactor could silently change claude bytes | `test_claude_rust_parity.py` gates w0 | **Accepted** — w0 reviewer must run full claude rust parity suite; consider one snapshot assert on file keys if digest-only is too coarse |
| **CH-309** | MINOR | Cursor builds hooks doc twice (plugin + `.cursor/hooks.json`) — risk of drift if built separately | Legacy `cursor.py` already shares one `_build_cursor_hooks` call | **Fixed** — w1cursor: **single** `hooks_doc` object, serialize twice (same as legacy pattern) |
| **CH-310** | MINOR | Copilot `build_copilot_hooks` does not merge duplicate matchers N:1 (unlike Claude PreToolUse bucket) | manifest_minimal has one hook; Rust matches one-entry-per-spec | **Accepted** — document; add merge test only if conformance fixture gains duplicate matchers later |
| **CH-311** | INFO | Spec AC-M12-3 is one bullet; sprint defines AC-M12-3a..f | Sprint is finer-grained | **Accepted** — map a..f in M12.3 closeout audit; optional spec appendix in w5 |
| **CH-312** | INFO | M12.4 mentions `matrix rust_parity tuples`; M12.3 only covers `legacy` slug | Phased per design | **Accepted** — dogfood_praxia `rust_parity` goldens deferred to M12.4 or follow-up |
| **CH-313** | INFO | Antigravity hooks use `PRAXIA_HOOK_SURFACE=claude` — surprising surface name | Matches praxia `build_claude_hooks` in bundle adapter | **Accepted** — document in README; do not "fix" to antigravity without praxia change |

---

## Scope check

| In M12.3 | Out M12.3 |
|----------|-----------|
| `_rust_emit.py` shared helpers | M12.4 blocking CI promotion |
| `cursor_rust` / `copilot_rust` / `antigravity_rust` | `golden_matrix` digest changes |
| `rust_parity=True` on 3 emitters | Default `validate` algorithm flip |
| `surface_digest_rust_parity` all surfaces | praxia `agents_path_verified` exposure |
| `tests/golden/rust_parity/legacy/{cursor,copilot,antigravity}` | dogfood_praxia rust_parity slugs |
| Advisory CI pytest expansion | Registry `rust_parity` kwarg (unless w4 needs it) |

---

## Edge-case matrix (M12.3)

| Condition | Expected behavior |
|-----------|-------------------|
| `rust_parity=True` on cursor | No agent files; agents listed in plugin.json |
| Hook `surfaces=("claude",)` only | Legacy copilot omits; rust-parity copilot **includes** (matches subprocess) |
| Agent `body=""` | Legacy may omit file; rust-parity copilot/antigravity still emit agent file (Rust always emits) |
| `CISTERNA_PRAXIA_ASSETS_BIN` unset | `test_*_rust_parity` subprocess tests skip; CLI `--rust-parity` exit 1 |
| w1∥w2∥w3 before w0 completes | **Forbidden** — orchestration must gate on w0shared green |
| Parallel merge on same emitter file | **Forbidden** — one track per emitter `.py` |

---

## Residual risks (accepted)

1. **Dual semantics** — legacy export and rust-parity export diverge on cursor agents and hook filtering; operators must not assume `cisterna export` bytes match `validate --rust-parity` in-process tests until they use `rust_parity=True` explicitly.
2. **Subprocess-only CLI** — green `validate --rust-parity` does not prove Python emitters are ported; rely on `test_*_rust_parity.py` in CI.
3. **Praxia pin frozen at `04bb683`** — emitter drift in praxia without pin bump could desync conformance; acceptable until intentional pin bump.
4. **Parallel tracks** — human/process risk if two agents edit `validate_golden.py` early; w4wire is sole owner of that file.

---

## Sprint amendments (apply before implement)

1. **w4wire** — add: parametrized `test_cli_rust_parity.py` for cursor/copilot/antigravity; `test_rust_parity_ignores_hook_surface_filter`; require (not optional) `surface_digest_rust_parity` dispatch table.
2. **w1cursor** — add: single `hooks_doc` shared between plugin.json and `.cursor/hooks.json`.
3. **w5audit** — AC-M12-3a..f matrix; note AC-M12-3f CLI vs pytest split (CH-302).

---

## Gate

**ACCEPT_WITH_NITS** — proceed to **implement M12.3** with sprint amendments above. No spec rev required; closeout audit carries AC a..f mapping.
