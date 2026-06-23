---
session_id: f2cf0c74
topic: HMW: select Cisterna M4 milestone after M3.3 close — what is the highest-value next epic when export stack is feature-complete for rev2?
task_type: architectural
winner: FACTION-G HYBRID-AB: M4 Export Trust — self-manifest dogfood CI + optional native validate lane + third-party emitter example
created_at: 2026-06-23T21:08:43.961725+00:00
---

# Brainstorm: HMW: select Cisterna M4 milestone after M3.3 close — what is the highest-value next epic when export stack is feature-complete for rev2?

## Problem Frame
Fixed: M3 export pillar rev2 complete; 296 tests; four surfaces + validate golden; no breaking Emitter ABC. Negotiable: M4 scope (hardening vs new pillar vs ecosystem adoption). Frame: pick ONE M4 epic that maximizes user trust in exported plugins (loadable in real IDEs) without reopening emitter surface multiplication.

## Idea Pool
- [ai] FACTION-A M4-VALIDATE-NATIVE: Harden validate with vendor CLI parity — CI job running claude/cursor plugin validators via --use-native-cli; golden + native dual gate; closes 'pure-Python validate passes but IDE rejects' risk.
- [ai] FACTION-B M4-DOGFOOD: Cisterna ships its own .praxia/manifest.toml + self-export in CI; dogfood export→validate→dry-run on every PR; documentation + example third-party emitter wheel.
- [ai] FACTION-C M4-TELEMETRY-RETURN: Pivot to original roadmap pillar 1 — bathos-compatible telemetry adoption across contemplex/bathos MCP servers; M1/M2 incomplete vs export over-investment.
- [ai] FACTION-D M4-IR-EXTENSIONS: Load workflows/pipelines/snippets into AssetBundle IR (beyond L14 validate-only); enables praxia-parity manifest round-trip.
- [ai] FACTION-E M4-HARDENING-SPRINT: Small epic: fix debt #238, inspect JSON schema version, list_emitter_surfaces CLI, composite conflict severity — hygiene before big bet.
- [ai] FACTION-F M4-RUST-BRIDGE: Spike praxia-Rust emitter backend behind Emitter ABC; evaluate byte-identical output vs Python emitters (original M5).
- [user] Competing approaches listed. Trade-off probe: A maximizes external validator trust but needs vendor CLIs in CI. B maximizes internal confidence cheaply. C rebalances pillars but abandons export momentum. D expands IR surface area. E is low risk low reward. F is high cost uncertain payoff.
- [ai] FACTION-G HYBRID-AB (recommended): M4 = Export Trust — (1) cisterna self-manifest + CI dogfood export/validate all surfaces; (2) optional native validator CI lane for claude (--use-native-cli) behind advisory/non-default until stable; (3) example third-party emitter package in examples/. Defer telemetry pivot (C) to M5.
- [user] Converge on FACTION-G HYBRID-AB: M4 Export Trust epic. Runner-up FACTION-C telemetry deferred M5. Pre-mortem: native CLI validators flaky in CI without pinned vendor versions.

## Decision Log
- [DEFER] FACTION-C M4-TELEMETRY-RETURN: Deferred to M5; export trust gap is immediate post-M3.3 user risk
- [DEFER] FACTION-D M4-IR-EXTENSIONS: L14 validate-only sufficient until dogfood proves load path
- [ACCEPT] FACTION-G HYBRID-AB: Balances internal dogfood + external validator trust without IR expansion

## Assumptions

- **A1:** `--use-native-cli` today means **subprocess `cisterna assets export`** parity (see `cli._native_cli_surface_digest`), not vendor IDE plugin CLIs. M4.3 hardens that path; real vendor validators are **TBD-M4+**.
- **A2:** CI target is **GitHub Actions** (no workflow exists yet on `main`).
- **A3:** Dogfood uses **in-process validate** (golden digest) as the **required** PR gate; subprocess/native lane is **advisory** (`continue-on-error: true` or separate workflow) until stable.
- **A4:** Registered surfaces remain exactly **`antigravity`, `claude`, `copilot`, `cursor`** — no fifth built-in surface in M4.
- **A5:** `Emitter` ABC and existing golden digests under `tests/golden/` remain stable unless a deliberate golden refresh is documented in the epic closeout memo.

## TBDs

| ID | Item | Default if unresolved |
|----|------|------------------------|
| TBD-1 | Vendor IDE validator integration (e.g. Claude Code `plugin validate`) | Defer post-M4; subprocess parity only |
| TBD-2 | Source for praxia-scale fixture | Vendored tree under `tests/fixtures/manifest_dogfood_praxia/` (no live praxia repo dependency in CI) |
| TBD-3 | Self-manifest content | Minimal exportable plugin listing cisterna registry commands + doc pointer; grows with repo assets |

## Out of scope (M4)

- New emitter surfaces in core `cisterna` package
- L14 workflows/pipelines/snippets **load** into `AssetBundle` (validate-only stays as shipped M3.3d)
- Telemetry / bathos pillar (deferred M5 per brainstorm)
- Rust emitter backend seam (M5)
- Public `register_emitter()` runtime API

## Child work packages

| ID | Deliverable | Module / path ownership |
|----|-------------|-------------------------|
| **M4.1a** | Repo self-manifest | `.praxia/manifest.toml` + referenced asset paths |
| **M4.1b** | Praxia-scale dogfood fixture | `tests/fixtures/manifest_dogfood_praxia/` |
| **M4.2** | Dogfood CI workflow | `.github/workflows/export-dogfood.yml` |
| **M4.3** | Subprocess validate lane | `tests/test_cli_native_validate.py`, CI advisory job |
| **M4.4** | Third-party emitter example | `examples/minimal_emitter/` |

---

## Epic definition of done

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-0** | M4 children merged on `main` | `uv run pytest` + `uv run ruff check .` | All tests green; ruff clean; test count ≥ baseline at epic start (296) |
| **AC-M4-0b** | Any M4 export/validate change | Compare `tests/golden/*/names_only/digest.sha256` (+ claude `with_command_bodies`) | Unchanged unless epic memo records intentional golden refresh |

---

## M4.1 — Manifests

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-1a** | `.praxia/manifest.toml` committed with relative paths | `ManifestAssetSource(manifest).load()` | `LoadReport.conflicts == ()`; `LoadReport.warnings == ()`; bundle non-empty (≥1 command **or** ≥1 skill/agent) |
| **AC-M4-1b** | Self-manifest | `cisterna assets inspect --manifest .praxia/manifest.toml` | Exit 0; JSON stdout includes `bundle` with `metadata.name` matching `[plugin].name` |
| **AC-M4-1c** | `tests/fixtures/manifest_dogfood_praxia/` fixture | `load_asset_report(manifest=fixture)` | Loads without raise; ≥2 `[[plugin.skills]]`, ≥1 `[[plugin.agents]]`, ≥1 `[[plugin.hook_specs]]`, `export_command` keys for ≥2 vendors, ≥1 L14 workflow/pipeline/snippet path entry (validate-only) |
| **AC-M4-1d** | Dogfood praxia fixture with intentional missing workflow file | `cisterna assets validate --manifest <fixture> --surface claude` | Exit 1 (structural warning gate per M3.1 validate) |

---

## M4.2 — Dogfood CI (required PR gate)

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-2a** | PR or push to `main` | GitHub Actions `export-dogfood` job | Runs on `ubuntu-latest` with `uv sync` + `uv run` |
| **AC-M4-2b** | Self-manifest | For each `surface` in `list_emitter_surfaces()`: `cisterna assets validate --manifest .praxia/manifest.toml --surface <surface>` | Exit 0 for all four surfaces (`names_only` mode) |
| **AC-M4-2c** | Self-manifest, claude only | `cisterna assets validate --manifest .praxia/manifest.toml --surface claude --emit-command-bodies` | Exit 0 |
| **AC-M4-2d** | Praxia-scale fixture | Same surface loop as AC-M4-2b on `tests/fixtures/manifest_dogfood_praxia/manifest.toml` | Exit 0 all four surfaces |
| **AC-M4-2e** | Self-manifest | `cisterna assets export --manifest .praxia/manifest.toml --surface claude --dry-run` | Exit 0; stdout lists ≥1 emitted path |
| **AC-M4-2f** | Dogfood job failure | Any AC-M4-2b–e step | Workflow fails; PR cannot merge (required check) |

---

## M4.3 — Subprocess export parity (advisory CI + unit tests)

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-3a** | Golden fixture (`manifest_minimal` or dogfood fixture) | `cisterna assets validate --use-native-cli --surface claude` | Exit 0; digest matches golden |
| **AC-M4-3b** | Same fixture | `validate` with and without `--use-native-cli` | Both exit 0; digests equal |
| **AC-M4-3c** | `tests/test_cli_native_validate.py` | `uv run pytest tests/test_cli_native_validate.py` | ≥2 tests: claude `names_only` + `with_command_bodies` subprocess paths |
| **AC-M4-3d** | CI advisory job | `validate --use-native-cli` matrix (claude `names_only` + `with_command_bodies` on self-manifest) | Job present; **non-blocking** (`continue-on-error: true` or `workflow_dispatch` only) until TBD-1 resolved |
| **AC-M4-3e** | Subprocess export emits zero files | `validate --use-native-cli` | Exit 1 (no silent pass) |

---

## M4.4 — Third-party emitter example

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-4a** | `examples/minimal_emitter/` with own `pyproject.toml` declaring `[project.entry-points."cisterna.emitters"]` | `uv pip install -e examples/minimal_emitter` in CI venv | Install succeeds |
| **AC-M4-4b** | Example package installed | `list_emitter_surfaces()` | Contains example surface name (e.g. `minimal`) **in addition to** four built-ins |
| **AC-M4-4c** | Example emitter + registry bundle | `get_emitter("<example>")` then `emit(bundle)` | Returns `dict[str, str]` with ≥1 file; no exception |
| **AC-M4-4d** | Dogfood CI matrix | Example install + `pytest examples/minimal_emitter/tests/` (or root test invoking example) | Runs in same workflow as AC-M4-2; fails workflow on regression |
| **AC-M4-4e** | `examples/minimal_emitter/README.md` | Human review | Documents entry-point group, factory signature, and `uv pip install -e` steps |

---

## Pre-mortem mitigations (traceability)

| Risk | Mitigation AC |
|------|----------------|
| Self-manifest too small | **AC-M4-1c**, **AC-M4-2d** |
| Native lane skipped/flaky | **AC-M4-3c** (unit tests required); **AC-M4-3d** (advisory, not silently omitted) |
| Example emitter bit-rots | **AC-M4-4d** in required dogfood workflow |

---

## Acceptance Criteria (summary)

**Given** M3 export rev2 complete (296+ tests, four surfaces, golden validate, stable `Emitter` ABC).

**When** M4 Export Trust ships (M4.1–M4.4).

**Then** all of **AC-M4-0** through **AC-M4-4e** pass; brainstorm deferrals (telemetry, IR load, Rust) remain out of scope.
