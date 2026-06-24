# M12 hash parity spike — cisterna ↔ praxia-agent-assets

**date:** 2026-06-24  
**fixture:** `tests/fixtures/manifest_minimal/manifest.toml`  
**backlog:** #2665  
**task_id:** `260624_m12-hash-spike`

## Executive summary

**Zero digest parity** across all four surfaces on a shared logical bundle. Divergence comes from **two independent axes**:

1. **Hash canonicalization** — cisterna `bundle_sha256` (`path\ncontents\n`) vs praxia `surface_bundle_sha256` (`path\0contents\n`).
2. **Emitter output** — different file sets, JSON formatting, YAML frontmatter, and hook command wrapping.

Even if emitters were byte-identical, digests would still differ until the hash algorithm is unified.

## Method

1. Load `manifest_minimal` via cisterna `load_asset_report` → `AssetBundle`.
2. Python: `emit_surface_files` + `surface_digest` (cisterna goldens).
3. Rust: construct equivalent `PraxiaBundle` (same metadata, bodies, hooks, command) → `surface_bundle_sha256` + adapter emit (temporary spike test in praxia-agent-assets; removed after run).
4. Cross-check: reimplement Rust hash in Python on identical file dicts.

## Digest comparison (`manifest_minimal`)

| Surface | Py files | Cisterna digest (golden) | Rust digest | Match |
|---------|----------|--------------------------|-------------|-------|
| claude | 1 | `9ad19378…` | `f6a1f7c3…` | **No** |
| cursor | 4 | `090bc6b3…` | `ca8d6a3e…` | **No** |
| copilot | 3 | `62379c9d…` | `40524672…` | **No** |
| antigravity | 4 | `894e13c5…` | `63768b08…` | **No** |

Cisterna goldens match in-process `bundle_sha256` (self-consistent).

## Hash algorithm (confirmed)

**Cisterna** (`export/_hash.py`):

```text
payload = join(sorted paths, f"{path}\n{contents}\n")
sha256(payload)
```

**Praxia** (`bundle.rs:surface_bundle_sha256`):

```text
for (path, contents) in btree_order:
    sha256_update(path + \0 + contents + \n)
```

Reproduced: Rust file set from spike → Rust algo = `f6a1f7c3…`; same bytes through Python algo = `36334668…`.

## Emitter divergence (high-signal)

### Claude — largest structural gap

| | Cisterna | Praxia |
|---|----------|--------|
| Files | 1 (`.claude-plugin/plugin.json` only) | 4 (plugin.json + agents + skills + hooks) |
| plugin.json | Pretty (`indent=2`, `sort_keys`); names-only; **no** `agents`/`skills` keys | Compact JSON; includes `agents`, `skills`, `commands` |
| Agent/skill bodies | Not emitted (M3 B1 names-only) | `agents/recon.md`, `skills/.../SKILL.md` emitted |
| Hooks | Not emitted | `hooks/hooks.json` with `env PRAXIA_HOOK_SURFACE=…` wrapper |

### Cursor

| | Cisterna | Praxia |
|---|----------|--------|
| Files | 4 (includes `agents/recon.agent.md`) | 3 (**no** agent `.md` in spike output) |
| plugin.json hooks | Nested `hooks.hooks.beforeShellExecution` | Similar structure, compact JSON |
| Agent FM | `description` omitted in YAML | `description: ''` present |

### Copilot / Antigravity

- Same path counts (3–4) but JSON compaction, hook dialect, and antigravity `gemini-extension.json` field ordering differ.
- Rust antigravity hooks use Praxia env wrapper on hook commands; cisterna uses raw script path.

## Implications for M12

| Option | Effort | Trust gain |
|--------|--------|------------|
| **A. Unify hash only** | Low | Low — digests still differ on emit drift |
| **B. Rust emit+hash via PyO3/subprocess** | High | High — single source of truth |
| **C. Port emitters to match Rust bytes, adopt Rust hash** | Very high | High — no runtime Rust dep |
| **D. Shared conformance vectors (cross-repo pytest + cargo test)** | Medium | Medium — catches drift, dual maintenance |
| **E. Claude-only wedge** | Medium | Partial — addresses worst gap first |

**Recommendation for brainstorm:** Treat **emitter parity** and **hash canonicalization** as separate workstreams. M12 winner likely combines **D (shared vectors)** as near-term gate plus **B or C** as strategic owner decision.

## Artifacts

- Spike run: cisterna `uv run python` (inline) + praxia `cargo test cisterna_manifest_minimal_hash_spike` (temp test, deleted).
- No product code or golden changes in this spike.
