---
title: Cisterna M3 — Agent-Asset Export — Buildable Spec (rev2, adversarially reconciled)
date: 2026-06-18
status: spec
task_id: 260618_cisterna-m3-assets
session_id: d528193d
plan_id: 260618_m3_assets_dag
review: spec-challenger (has_gaps) + spec-defender (needs_revision) reconciled rev2
---

# Cisterna M3 — Agent-Asset Export (Buildable Spec, rev2)

**Winner: Shape A framed by Shape F** — AssetSpec-first, live-M2-registry-sourced,
**Claude-only**, **pure-emit ABC**, provenance sha256, `--dry-run`, frozen
dataclasses, library-API-first, two subpackages. First realization of cisterna's
agent-asset-export pillar on REAL live data (the M2 `@tool` registry).

## Locked decisions
- **ARBITRATION-1 — Emitter = ABC** (matches `cisterna.adapters.AdapterBase`).
- **ARBITRATION-2 — flat layout**: `cisterna/export/{base,claude,write,_hash}.py`;
  IR in `cisterna/assets/{spec,bundle,source}.py`.

## Scope
**In M3:** registry source → `AssetSpec`; Claude surface only; pure-emit `Emitter`
ABC + `ClaudeEmitter`; provenance sha256 sidecar; `write_bundle` + `--dry-run`;
frozen dataclasses; cyclopts `cisterna assets export` CLI; lazy public API.
**Deferred to M3.1:** file/manifest source, unified AssetSource Protocol,
WriterSink ABC, Capability enum/map, model_hint table, validate subcommand +
golden/drift, entry_point plugins, inspect subcommand, HookSpec filter, surfaces
2–4, **per-command markdown files with frontmatter** (needs a body source + a
validated Claude command schema — see B1 resolution).

---

## B1 RESOLUTION (evidence-based) — Claude output = manifest only, names-only
Verified against praxia `crates/praxia-agent-assets/src/bundle_claude.rs`: the
reference ClaudeAdapter emits **only** `.claude-plugin/plugin.json` and lists
command **names** in the `commands` array — it emits **no** `commands/<name>.md`
files. M3 mirrors this exactly. Rationale: inventing a `commands/*.md` frontmatter
shape that is not validated against the real Claude command loader is the exact
"gate-passes-while-feature-broken" risk B1 raised. Names-only is loadable,
reference-faithful, and lowest-risk. AssetSpec.description/params are computed and
carried in the IR for M3.1 (when a body source + validated command schema land)
but are **not emitted** in M3.
> **PI DECISION POINT:** this makes the M3 deliverable a manifest listing tool
> names (loadable Claude plugin, no per-command bodies). Alternative (richer,
> higher-risk) = emit `commands/<name>.md` with an invented frontmatter shape.
> Default baked in here = names-only (Option A). Flagged for sign-off at REGISTER.

---

## 1. Data model (`cisterna/assets/`)
Frozen dataclasses; collections are **tuples** (hashable + deterministic).

```python
# spec.py
@dataclass(frozen=True, slots=True)
class AssetSpec:
    name: str
    kind: str                  # "command" (M3 always); "mcp" reserved (never produced in M3)
    description: str | None    # inspect.cleandoc(__doc__) first paragraph; None if absent
    params: tuple[str, ...]    # signature param names; () on degrade (lossy sentinel — see §1 map)
    source: str                # registry partition name

# bundle.py
@dataclass(frozen=True, slots=True)
class BundleMetadata:
    name: str
    version: str
    description: str = ""

@dataclass(frozen=True, slots=True)
class CommandAsset:
    name: str
    description: str | None
    body: str = ""             # carried for M3.1; NOT emitted in M3 (B1)

@dataclass(frozen=True, slots=True)
class McpAsset:
    name: str
    command: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True, slots=True)
class AssetBundle:
    metadata: BundleMetadata
    commands: tuple[CommandAsset, ...] = ()      # sorted by name at construction (M1)
    mcp_servers: tuple[McpAsset, ...] = ()       # ALWAYS EMPTY in M3 (m1); reserved forward-compat
    # No skills/agents/hooks fields (PREMORTEM-1). Empty tuples flow through emit, no raise.
```

### `registry_assets` — lives in `assets/source.py` (G1/M5)
`registry_assets(registry: str = "default") -> tuple[AssetSpec, ...]`:
- Calls `cisterna.registration.registry._snapshot(registry)`. **Deliberate, tested
  coupling** to a `_`-private (M5): AC-M3-2 pins it; if `_snapshot` changes, that AC
  fails loudly. (A public `registration.snapshot()` accessor is an optional M3.1 cleanup.)
- Returns `()` for empty/unknown registry — never raises (PM-1/2). `_snapshot` returns
  `dict(_registry(name))`; unknown name → `{}` → `()`.
- **Sorted by `AssetSpec.name`** (M1) so output is canonical regardless of registration
  /import order.

For each `ToolEntry` (`registry.py:27-39` = `{name, fn, registry}`):
- `name = entry.name`; `kind = "command"`; `source = registry`.
- `description`: `d = inspect.cleandoc(entry.fn.__doc__ or "")`; first paragraph
  `d.split("\n\n", 1)[0].strip() or None` (M2 — dedented, not first-physical-line).
- `params`: `tuple(inspect.signature(entry.fn).parameters)` wrapped in
  `try/except Exception` (M3 — never-raise is absolute, broader than ValueError/TypeError);
  on failure → `params = ()` + `logging.getLogger("cisterna.export").warning(...)` naming
  the tool (PM-4; logging per `wired.py` precedent, not `print`). `()` is an intentionally
  lossy sentinel (no-args and introspection-failure collapse; WARNING is the only signal).

## 2. Pure-emit contract (`cisterna/export/`)
```python
# base.py
class Emitter(ABC):
    @abstractmethod
    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        """Render bundle → {forward-slash relative path: contents}. PURE: zero I/O,
        zero filesystem access, no side effects. Identical bundle → identical dict
        (Rust-seam: a praxia-Rust backend slots in as a concrete subclass)."""
```

### ClaudeEmitter (`claude.py`) — mirrors praxia bundle_claude.rs
`emit(bundle)` returns exactly these keys:
- `.claude-plugin/plugin.json` — `json.dumps(obj, sort_keys=True, indent=2)` of:
  - always: `"name"`, `"version"`, `"description"` (`meta.description or ""`, m3).
  - `"commands": [<sorted command names>]` **only if** commands non-empty (praxia parity).
  - `"mcpServers": {name: {"command": [...], "env": {...}}}` **only if** mcp_servers
    non-empty (always omitted in M3 per m1). `env` tuple-of-pairs → dict (last-wins on dup key).
- `.claude-plugin/cisterna-provenance.json` — see §2-provenance (sidecar, not stamped-in-manifest,
  so Claude's plugin.json schema is never polluted).
- Empty bundle → valid manifest with `name/version/description` only; never raises (PM-1).

### Provenance (`_hash.py`) — B2 resolution
Two distinct hashes, **distinctly named** (B2):
- `bundle_sha256(files: dict[str,str]) -> str` (= **provenance digest**): canonical hash
  over `sorted(files.items())`, input = `"".join(f"{path}\n{contents}\n" ...)` (fixed
  separators, NOT repr — PM-5). Computed over the **non-provenance file set** (i.e. just
  `plugin.json` in M3 — the sidecar is excluded to avoid self-reference).
- The emitter writes the digest into the sidecar: `{"sha256": "<digest>"}` (canonical JSON).
- `WriteResult.content_sha256` (§3) is a **different** value: the post-write content hash of
  each file on disk. The provenance digest and the per-file content hash are NOT the same number.
- Determinism: emit twice on an identical bundle → byte-identical dict **including** the
  sidecar (AC-M3-6).

## 3. write_bundle + dry-run (`write.py`)
```python
@dataclass(frozen=True, slots=True)
class WriteResult:
    files: tuple[tuple[str, str], ...]   # (path, content_sha256) per file
    dry_run: bool

def write_bundle(files: dict[str, str], out: Path, *, dry_run: bool = False) -> WriteResult
```
- `dry_run=True`: compute each file's content_sha256, write NOTHING, return WriteResult.
- `dry_run=False`: mkdir parents, write each file, return WriteResult.
- Empty `files` → empty WriteResult, no error (PM-1/3). **Emitter-independent** (takes a dict).

## 4. CLI (`cli.py`) — B3 + M4
`cyclopts.App`; `cisterna assets export [--dry-run] [--registry NAME] [--out DIR] [--import MODULE]... [--name NAME] [--version VER]`.
- **Imports `registry_assets` from a fastmcp-free path**: `from cisterna.assets.source import
  registry_assets` (NOT via `cisterna.__init__` if that would chain fastmcp). Coexists with the
  unrelated `cisterna/adapters/cli.py` (telemetry `CliAdapter`) — do not merge (M4).
- `--import MODULE` (repeatable): `importlib.import_module(m)` to run the target's `@tool`
  side-effects (decorator registers at import time). **`sys.modules` caching caveat (B3):** if the
  module is already imported in this process, no re-registration occurs. The contract is therefore
  *"the import target's `@tool` calls must have executed in this process by export time"* —
  documented as an in-process-only limitation (PM-2).
- **Empty-registry detection keyed on `len(snapshot)==0` at snapshot time** (B3), NOT on import
  success → non-raising WARNING to stderr; emit empty bundle.
- `BundleMetadata` source (G3/m2): `name = --name or "cisterna"`; `version = --version or
  importlib.metadata.version("cisterna")` (fallback `"0.0.0"` on `PackageNotFoundError`);
  `description = ""`.
- Builds AssetBundle → `ClaudeEmitter().emit` → `write_bundle(..., dry_run=...)`. `--dry-run`
  prints `f"{path}  {content_sha256}"` lines, writes nothing.
- Export **always returns exit code 0** (never-raise; warnings only).
- `pyproject.toml`: `[project.scripts]` `cisterna = "cisterna.cli:app"`.

## 5. Public API (`cisterna/__init__.py`)
Add 6 names: `AssetSpec`, `AssetBundle`, `registry_assets`, `Emitter`, `ClaudeEmitter`,
`write_bundle`. assets/export pull no heavy deps → eager import is fine; mirror the M2 lazy
`__getattr__` only if an optional dep later appears. No `cisterna.adapters` collision; append all
6 to `__all__` under `# M3 (assets export)`. Smoke: `python -c "import cisterna.cli"` must succeed
with `fastmcp` uninstalled (M4) — covered by the public-API test.

## Test infrastructure (B3 — hard precondition)
`tests/conftest.py` MUST gain an **autouse fixture clearing ALL registry partitions**
(`clear_registry()` for default + any used names) before/after each test, so the new
`tests/test_assets_*.py`, `test_export_*.py`, `test_cli_assets.py` are order-independent.
Without it AC-M3-1 (empty→()) and AC-M3-8 (populate) are mutually order-dependent in a shared
interpreter. This fixture is node N0 (Wave 1).

## Acceptance criteria (8, INVEST-Small; each maps to premortems)
- **AC-M3-1** — `registry_assets` on empty/unknown registry → `()`, never raises (PM-1/2). `test_assets_spec.py`.
- **AC-M3-2** — `ToolEntry`→`AssetSpec`: name; `inspect.cleandoc` first-paragraph description (assert a multiline docstring); `inspect.signature` param names; verifies the `_snapshot` coupling (M1/M2/M5). `test_assets_spec.py`.
- **AC-M3-3** — a tool whose `inspect.signature` raises (any Exception) → `params=()` + WARNING, **and a second well-formed tool in the same bundle still exports** (PM-4/M3). `test_assets_spec.py`.
- **AC-M3-4** — `Emitter` cannot be instantiated (abstract); `ClaudeEmitter.emit` does zero I/O (filesystem-spy: monkeypatch `open`/`Path.write_text`, assert not called) (PM-3). `test_export_claude.py`.
- **AC-M3-5** — `emit` produces `.claude-plugin/plugin.json` with `name/version/description` always; `commands` (sorted) present iff non-empty, omitted iff empty; `mcpServers` omitted when empty; empty bundle → valid manifest, no error (PM-1, B1). Schema-validate the JSON shape, not the emitter's echo. `test_export_claude.py`.
- **AC-M3-6** — `emit` is deterministic (two runs → byte-identical dict incl. sidecar); provenance sidecar `sha256` == `bundle_sha256` of the non-provenance file set (PM-5, B2). `test_export_claude.py`.
- **AC-M3-7** — `write_bundle(dry_run=True)` writes nothing and returns per-file `content_sha256` (distinct from the provenance digest); `dry_run=False` writes all; empty input safe (PM-1/3, B2). `test_export_write.py`.
- **AC-M3-8** — CLI `export --import <mod>` populates registry (in-process) and emits files; empty registry → WARNING + exit 0; `--dry-run` prints `path  sha256`, writes nothing; `import cisterna.cli` works without fastmcp (PM-2, B3, M4). `test_cli_assets.py` + `test_assets_public_api.py`.

## Task DAG (epic + children) — M6-reconciled
| Node | Title | Files | depends_on | Wave |
|---|---|---|---|---|
| N0 | autouse clear-all-registries fixture | tests/conftest.py | — | 1 |
| N1 | AssetSpec/AssetBundle IR (frozen, sorted ctor) | assets/spec.py, assets/bundle.py | — | 1 |
| N3 | Emitter ABC pure-emit | export/base.py | — | 1 |
| N3b | bundle_sha256 provenance helper | export/_hash.py | — | 1 |
| N2 | registry→AssetSpec source (never-raise, sorted) | assets/source.py | N1 | 2 |
| N4 | ClaudeEmitter + provenance sidecar | export/claude.py | N1, N3, N3b | 2 |
| N5 | write_bundle + dry-run | export/write.py | N3b | 2 |
| N6 | cyclopts CLI + [project.scripts] | cli.py, pyproject.toml | N2, N4, N5 | 3 |
| N7 | public API + __all__ | __init__.py | N1, N3, N4, N5 | 3 |
| N8a | spec/emitter/write tests (AC-1..7) | tests/test_assets_spec.py, test_export_claude.py, test_export_write.py | N0, N1, N2, N3b, N4, N5 | 3 |
| N8b | CLI + public-API tests (AC-8) | tests/test_cli_assets.py, test_assets_public_api.py | N0, N6, N7 | 4 |

Fixes folded: `_hash.py` is its own node N3b (was double-written by N4+N5 → merge hazard);
N5 depends on **N3b only** (write_bundle is Emitter-independent — dropped the spurious N5→N3 edge);
N8 split into N8a/N8b with concrete edges (was an unresolvable `(per-AC nodes)` placeholder).
Waves: **W1** [N0, N1, N3, N3b] → **W2** [N2, N4, N5] → **W3** [N6, N7, N8a] → **W4** [N8b].

## Reconciliation log (adversarial review → resolution)
- **B1** (plugin.json/command shape invented) → RESOLVED: mirror praxia names-only, no command .md files; PI decision flagged.
- **B2** (hash conflation) → RESOLVED: `provenance digest` (bundle_sha256, sidecar) vs `content_sha256` (WriteResult) distinctly named; sidecar excluded from digest; twice-run AC.
- **B3** (--import caching + missing fixture) → RESOLVED: N0 autouse clear-all fixture; empty-registry keyed on snapshot length; in-process/cached-import limitation documented.
- **M1** sort determinism → registry_assets + AssetBundle.commands sorted by name.
- **M2** lossy description → inspect.cleandoc first paragraph.
- **M3** narrow except → `except Exception`; `()` documented lossy.
- **M4** CLI import chain → fastmcp-free import + no-fastmcp smoke; coexist note with adapters/cli.py.
- **M5** layering + filename → registry_assets in assets/source.py; _snapshot coupling documented + AC-pinned.
- **M6** DAG → N3b node, N5→N3b, N8a/N8b split.
- **G1/G3** → source.py named; BundleMetadata name/version source specified.
- **m1** mcp_servers always empty in M3 (documented). **m3** description `or ""` coercion.
