---
title: M4 Export Trust — buildable spec rev1
parent_brainstorm: .praxia/docs/specs/260623_hmw-select-cisterna-m4-milestone-after-m.md
design: .praxia/docs/designs/260623_m4-export-trust_design.md
depends_on_epic: 2581
task_id: 260623_m4-export-trust
adversarial_verdict: ACCEPT_WITH_NITS
---

# M4 Export Trust — buildable spec (rev1)

**Goal:** Maximize trust that exported plugins are loadable in real IDEs via dogfood CI, manifest-scoped goldens, subprocess export parity tests, and a third-party emitter example — without new built-in surfaces or IR load expansion.

**Built-in surfaces (fixed set):** `antigravity`, `claude`, `copilot`, `cursor`

## Out of scope

Telemetry (M5), L14 IR load, Rust emitter, fifth built-in surface, public `register_emitter()`, vendor IDE plugin CLIs (TBD-1 post-M4).

## Child work packages

| ID | Deliverable | depends_on |
|----|-------------|------------|
| **M4.1a** | Repo self-manifest | — |
| **M4.1b** | Praxia-scale dogfood fixture | — |
| **M4.4** | Third-party emitter example | — |
| **M4-GOLDEN** | Manifest-scoped golden digests + resolver | M4.1a, M4.1b |
| **M4.2** | Dogfood CI workflow | M4-GOLDEN, M4.1a, M4.4 |
| **M4.3** | Subprocess validate lane | M4-GOLDEN |

## Golden resolver (M4-GOLDEN)

Extend `golden_digest_path` to accept manifest path:

| Manifest | Digest root |
|----------|-------------|
| `tests/fixtures/manifest_minimal/manifest.toml` | `tests/golden/<surface>/<mode>/` (legacy) |
| `.praxia/manifest.toml` | `tests/golden/self_manifest/<surface>/<mode>/` |
| `tests/fixtures/manifest_dogfood_praxia/manifest.toml` | `tests/golden/dogfood_praxia/<surface>/<mode>/` |
| Any other path | **fail closed** (exit 1, log unknown manifest for golden) |

`cli.validate_assets` passes manifest into resolver.

---

## Epic DoD

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-0** | M4 merged | `uv run pytest` + `uv run ruff check .` | Green; test count ≥ 296 |
| **AC-M4-0b** | Legacy goldens | Compare `tests/golden/{claude,cursor,copilot,antigravity}/names_only/` (+ claude `with_command_bodies`) | Unchanged unless epic closeout memo records refresh |
| **AC-M4-0c** | New golden trees (`self_manifest`, `dogfood_praxia`) | Digest change on `main` | PR description or epic memo states intentional refresh reason |

---

## M4.1 Manifests

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-1a** | `.praxia/manifest.toml` | `ManifestAssetSource.load()` | `conflicts==()`; `warnings==()`; bundle has ≥1 skill or agent |
| **AC-M4-1b** | Self-manifest | `cisterna assets inspect --manifest .praxia/manifest.toml` | Exit 0; JSON `bundle.metadata.name` == `[plugin].name` |
| **AC-M4-1c** | `tests/fixtures/manifest_dogfood_praxia/` | `load_asset_report(manifest)` | ≥2 skills, ≥1 agent, ≥1 hook_spec, export_command ≥2 vendors, ≥1 L14 workflows/pipelines/snippets entry |
| **AC-M4-1d** | Dogfood fixture copy with missing workflow path (pytest `tmp_path` **or** `manifest_dogfood_praxia_broken/`) | `validate --manifest <broken> --surface claude` | Exit 1. **Not** the same manifest path as AC-M4-2d |

---

## M4.2 Dogfood CI (required)

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-2a** | PR/push `main` | `export-dogfood` workflow | `ubuntu-latest`; `uv sync`; `uv run` |
| **AC-M4-2b** | Self-manifest; **before** example install | For each built-in surface `s ∈ {antigravity, claude, copilot, cursor}`: `validate --manifest .praxia/manifest.toml --surface s` | Exit 0 (names_only) |
| **AC-M4-2c** | Self-manifest | `validate --manifest .praxia/manifest.toml --surface claude --emit-command-bodies` | Exit 0 |
| **AC-M4-2d** | `manifest_dogfood_praxia/manifest.toml` (good fixture) | Same built-in surface loop as AC-M4-2b | Exit 0 all four |
| **AC-M4-2e** | Self-manifest | `export --manifest .praxia/manifest.toml --surface claude --dry-run` | Exit 0; stdout ≥1 path |
| **AC-M4-2f** | Any AC-M4-2b–e failure | Workflow | Fails (required check) |
| **AC-M4-2g** | Dogfood workflow | Step order | Built-in validate (AC-M4-2b–e) completes **before** `uv pip install -e examples/minimal_emitter` |

---

## M4.3 Subprocess parity

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-3a** | `tests/fixtures/manifest_minimal/manifest.toml` | `validate --manifest <path> --surface claude --use-native-cli` | Exit 0; matches golden |
| **AC-M4-3b** | Same manifest | validate with/without `--use-native-cli` | Both exit 0; digests equal |
| **AC-M4-3c** | `tests/test_cli_native_validate.py` | pytest | ≥2 tests: claude names_only + with_command_bodies |
| **AC-M4-3d** | Advisory CI job | `validate --manifest .praxia/manifest.toml --surface claude --use-native-cli` (+ bodies variant) | Job present; `continue-on-error: true` |
| **AC-M4-3e** | Subprocess emits zero files | `validate --use-native-cli` | Exit 1 |

---

## M4.4 Example emitter

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M4-4a** | `examples/minimal_emitter/` | `uv pip install -e examples/minimal_emitter` | Success |
| **AC-M4-4b** | Example installed | `list_emitter_surfaces()` | Contains `minimal` plus four built-ins |
| **AC-M4-4c** | Example + bundle | `get_emitter("minimal").emit(bundle)` | ≥1 file; no exception |
| **AC-M4-4d** | After AC-M4-2g | `pytest examples/minimal_emitter/tests/` in dogfood workflow | Fails workflow on regression |
| **AC-M4-4e** | README | Human review | Documents entry-point group, factory, install steps |

---

## Adversarial reconciliation (rev1)

| Challenger ID | Resolution |
|---------------|------------|
| C1 | M4-GOLDEN added as child + golden resolver section |
| C2/C3 | AC-M4-2b/d use fixed built-in set; AC-M4-2g ordering |
| C4/C5 | AC-M4-3a pins `manifest_minimal` + explicit `--manifest` |
| C6 | AC-M4-1d broken fixture ≠ AC-M4-2d good fixture |
| C7 | AC-M4-0c new-tree refresh policy |
| C8 | Unknown manifest → fail closed |
