---
title: M12 Export Rust bridge — buildable spec rev1
session_id: a8b30dc1
design: .praxia/docs/designs/260624_m12-export-rust-bridge_design.md
spike: .praxia/docs/research/260624_m12-hash-parity-spike.md
adversarial: .praxia/docs/research/260624_m12-adversarial-review.md
backlog_id: 2665
task_id: 260624_autonomous-loop
verdict: ACCEPT_WITH_NITS
---

# M12 Export Rust bridge — buildable spec (rev1)

> **Epic status (2026-06-23):** **COMPLETE** (#2665, `5e05e87`). All export-dogfood jobs blocking.
> CI job `rust-parity` (was `rust-parity-advisory` in AC-M12-1k). See
> [CI promotion status](260623_ci-promotion-status.md).

**Goal:** Establish cross-repo export digest parity with praxia-agent-assets via subprocess bridge, shared conformance fixtures, and phased emitter alignment — without regressing M11 `golden_matrix` or export-dogfood blocking jobs.

**Epic phasing:** M12.1 (bridge + advisory CI) → M12.2 (claude wedge) → M12.3 (remaining surfaces) → M12.4 (blocking promotion) — **all slices shipped**.

---

## Fixed / out of scope

- Rewrite Rust emitters to match Python
- PyO3 / maturin in cisterna wheel
- Change default `validate` to rust parity in M12.1
- Include `cisterna-provenance.json` in rust hash scope
- Modify `golden_matrix` legacy digests in M12.1

---

## M12.1 acceptance criteria (first sprint)

### Cross-repo prerequisite

**AC-M12-0:** `praxia-agent-assets` ships `bundle-hash` binary invoking `surface_bundle_sha256`. Cisterna M12.1 implementation may proceed in parallel using local `cargo build` path; CI advisory job requires merged praxia bin at pinned rev.

### praxia: `bundle-hash` CLI

**AC-M12-0a:** `bundle-hash --surface <claude|cursor|copilot|antigravity>` reads `PraxiaBundle` JSON from stdin (or `--bundle PATH`), writes lowercase hex digest + newline to stdout.

**AC-M12-0b:** Unknown surface → exit 2; parse/emit error → exit 1 with stderr message.

### Cisterna: bundle bridge

**AC-M12-1a:** `asset_bundle_to_praxia_json(bundle: AssetBundle) -> dict` in `src/cisterna/assets/bridge.py` maps metadata, commands, agents, skills, hook_specs, mcp_servers; sets `workflows` and `pipelines` to empty lists.

**AC-M12-1b:** Defaults: skill/agent `description` → `""` when unset; hook `surfaces` → list from `HookSpecAsset.surfaces`.

**AC-M12-1c:** `tests/test_rust_parity_bridge.py` loads `manifest_minimal`, converts via bridge, asserts JSON keys match conformance fixture `tests/conformance/manifest_minimal.bundle.json`.

### Cisterna: subprocess wrapper

**AC-M12-1d:** `_rust_surface_digest(bundle, surface, *, bin_path: str | None)` runs `bundle-hash`, pipes bridge JSON on stdin, returns hex string; raises `RuntimeError` on nonzero exit.

**AC-M12-1e:** `bin_path` resolves from `CISTERNA_PRAXIA_ASSETS_BIN` env when omitted.

### Cisterna: validate flag

**AC-M12-1f:** `cisterna assets validate --rust-parity` (with existing `--manifest`, `--surface`) computes digest via `_rust_surface_digest`; exit 0 on match with in-process Rust call, exit 1 on mismatch or wrapper failure; does not read `tests/golden/` legacy files.

**AC-M12-1g:** `--rust-parity` without resolvable bin → exit 1, stderr explains `CISTERNA_PRAXIA_ASSETS_BIN`.

### Conformance fixtures

**AC-M12-1h:** `tests/conformance/manifest_minimal.bundle.json` — canonical `PraxiaBundle` JSON (from spike).

**AC-M12-1i:** `tests/conformance/expected/{surface}.sha256` — pinned expected digests for manifest_minimal (documented as Rust truth at pin rev).

**AC-M12-1j:** `tests/test_rust_parity.py` parametrizes 4 surfaces; calls `_rust_surface_digest` on loaded manifest bundle; asserts equals expected file (skip if bin missing — `pytest.importorskip` style env check).

### CI

**AC-M12-1k:** *(M12.1 — shipped advisory)* `export-dogfood.yml` job `rust-parity-advisory` with `continue-on-error: true`: checkout praxia @ `CISTERNA_PRAXIA_ASSETS_REV`, build `bundle-hash`, run `pytest tests/test_rust_parity.py -q`. **Superseded by AC-M12-4** — job is now blocking `rust-parity`.

**AC-M12-1l:** Existing jobs (`dogfood`, `golden_matrix`, `native-validate`, `otlp-collector`) unchanged and blocking.

### Docs

**AC-M12-1m:** `.praxia/docs/runbooks/cisterna-telemetry.md` export section documents dual-lane export trust (`golden_matrix` Python-canonical; `rust-parity` praxia byte parity). Legacy goldens remain Python canonical for default `validate`.

---

## M12.2+ criteria (deferred — design reference)

**AC-M12-2a:** ClaudeEmitter emits Rust-equivalent 4-file set on manifest_minimal; `validate --rust-parity` passes claude without mismatch.

**AC-M12-2b:** `bundle_sha256_rust()` adopted for claude `surface_digest`; `tests/golden/rust_parity/` tree populated for claude.

**AC-M12-3:** cursor, copilot, antigravity emitter ports + rust_parity goldens.

**AC-M12-4:** *(M12.4 — shipped)* Job `rust-parity` is **blocking** (no `continue-on-error`). Renamed from `rust-parity-advisory`. Conformance + `tests/golden/rust_parity/legacy/` green; `golden_matrix` Python tuples unchanged. Commit `5e05e87`.

---

## Adversarial reconciliation

| ID | Resolution |
|----|------------|
| CH-001 | AC-M12-0 cross-repo gate |
| CH-002 | AC-M12-1c bridge round-trip |
| CH-003 | AC-M12-1f live compare vs AC-M12-1i pinned expected |
| CH-004 | AC-M12-1k pin + advisory |
| CH-005 | AC-M12-1k naming + AC-M12-1m docs |
| CH-006 | AC-M12-0a JSON stdin |
| CH-007 | AC-M12-1g fail closed |
| CH-008 | rust_parity ignores emit_command_bodies |

---

## Test plan (M12.1)

```bash
# praxia (after bundle-hash lands)
cd ../praxia/crates/praxia-agent-assets
cargo build --release --bin bundle-hash
echo '<bundle json>' | ./target/release/bundle-hash --surface claude

# cisterna
export CISTERNA_PRAXIA_ASSETS_BIN=../praxia/target/release/bundle-hash
uv run pytest tests/test_rust_parity.py tests/test_rust_parity_bridge.py -q
uv run pytest -m golden_matrix -q   # unchanged
uv run cisterna assets validate --manifest tests/fixtures/manifest_minimal/manifest.toml --surface claude --rust-parity
```

---

## Gate

**ACCEPT_WITH_NITS** — implement **M12.1** after praxia `bundle-hash` is available (or local build for dev).
