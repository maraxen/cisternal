---
title: M3 Agent-Asset Export — Research Synthesis
date: 2026-06-18
status: research
task_id: 260618_cisterna-m3-assets-research
---

# M3 Agent-Asset Export — Research Note

Synthesis of two parallel recon passes: (1) cisterna's existing foundation, and
(2) the praxia Rust export engine (`crates/praxia-agent-assets/`) whose *shape*
M3 ports to native Python. M3 is cisterna's second mission pillar:
**one canonical agent asset → many surfaces** (Claude Code, Cursor, Copilot,
Antigravity/Gemini), native-Python, behind a `Writer`/backend abstraction.

> Numbering: the roadmap's original "M3 = Cyclopts/CLI" was absorbed into the
> shipped M2 registration surface. This "M3" = roadmap M4/M5 content.

## 1. Praxia engine shape (the blueprint)

### Canonical IR — `PraxiaBundle` (bundle.rs:80-96)
8 asset types; only 5 are **Emittable** (have a surface representation):

| Asset | Emittable | Key fields |
|---|---|---|
| `SkillAsset` | yes | name, description, body (md) |
| `AgentAsset` | yes | name, description, tools[], model?, body |
| `McpAsset` | yes | name, command[], env{} |
| `CommandAsset` | yes | name, body |
| `HookSpecAsset` | yes | event (PascalCase), matcher, script, tier, surfaces[] |
| `WorkflowAsset` | **no** (inbound-only) | name, template_path |
| `PipelineAsset` | **no** (inbound-only) | name, phases[] |
| `BundleMetadata` | — | name, version, description |

On-disk IR format = TOML (serde). Deterministic hash: `surface_bundle_sha256()`
over a sorted `{path: contents}` map (bundle.rs:190-213).

Source representation before IR = role markdown + YAML frontmatter
(`RoleFrontmatter`, frontmatter.rs:11-41): name, description, model_hint
(fast|balanced|deep), default_tools (abstract capability tokens), skills[],
snippets[], output_schema, capabilities[]. **14 abstract capability verbs**
(capability.rs): read, search, edit, write, execute, web, web_search, delegate,
transduction_log, transduction_query, lesson, knowledge, recon_workspace,
code_index_workspace. Unknown token = hard parse error.

### Pipeline: discover → parse → build IR → per-surface adapt → write
- **Discover:** list role `.md` files; filter by portability stems (20 portable /
  5 specialist / 17 praxia-operational; disjoint).
- **Parse:** split `---` frontmatter, deserialize YAML, assemble snippets.
- **Build IR:** abstract capability tokens → concrete tool names via
  `vendor_tools.toml [<vendor>.capability_map]`; model_hint → concrete model;
  resolve+validate skills against registry.
- **Adapt:** `BundleAdapter::emit(&Bundle) -> {rel_path: contents}` — **PURE, no
  I/O.** Four adapters: Claude, Cursor, Copilot, Antigravity.
- **Write:** caller does all I/O (`write_bundle`). No abstract Writer/sink in Rust
  — pure map + thin writer. Hash-stamp each agent file with a provenance comment.

### Per-surface output spec
| Surface | Manifest | Agent file | Skill path | Hooks | Events |
|---|---|---|---|---|---|
| claude | `.claude-plugin/plugin.json` | `agents/<n>.md` | `skills/<n>/SKILL.md` | `hooks/hooks.json` | PascalCase |
| cursor | `.cursor-plugin/plugin.json` | `agents/<n>.agent.md` (fail-closed gate) | same | `.cursor/hooks.json` | camelCase (PreToolUse→beforeShellExecution) |
| copilot | `plugin.json` | `agents/<n>.agent.md` | same | inlined in plugin.json | camelCase |
| antigravity | `gemini-extension.json` (contextFileName=GEMINI.md) | `agents/<n>.md` | same | `hooks/hooks.json` | PascalCase |

Workflows/Pipelines never emitted (Emittable boundary; negative-tested).

### N:1 hook aggregation (hooks_emit.rs)
Group HookSpec by event. For Pre/PostToolUse: matcher-bucket — append command to
existing `{matcher, hooks:[...]}` bucket or create new. Other events: one entry
per spec. Merge dedups on `(event, matcher, script)` triple; idempotent.

### Registry/discovery
- Per-plugin self-declaration: `.praxia/manifest.toml` (`[plugin]`, `[[plugin.skills]]`,
  `[[plugin.agents]]`, `[[plugin.hook_specs]]`, etc.; asset paths relative to plugin root).
- Global registry: `~/.praxia/plugins.toml` — `[plugins.<name>]` path, enabled,
  hashes.<target> (staleness), exported_files.<target> (inventory).
- `praxia plugin install <path>` writes entry + runs export; `export` re-runs.

### Test contracts → candidate Python ACs
Manifest/path conformance per surface; Emittable negative boundary; Cursor
fail-closed agent gate; capability map completeness (all 14 verbs per surface);
empty-string capability = hard error; sha256 determinism + drift golden tests;
30-day attestation gate for flipping `*_verified`; portable-role lint
(7 required sections, no praxia-internal substrings, ≤2000 tokens, positive framing).

## 2. Cisterna foundation (what M3 attaches to)

- **Namespace:** `cisterna.adapters` is RESERVED for telemetry-shaping
  (`AdapterBase.shape_ok/error`). M3 must NOT reuse "adapter" there. Clean empty
  slots: `cisterna/assets/` (IR) + `cisterna/export/` or `cisterna/writers/`
  (the backend ABC + per-surface writers).
- **Live asset source seam:** `registry._snapshot(name) -> dict[str, ToolEntry]`.
  `ToolEntry = {name, fn, registry}` only — description on `fn.__doc__`, schema on
  `inspect.signature(fn)`, marker `fn.__cisterna_tool__`. No description/tags/
  surface fields yet → M3 likely needs a richer `AssetSpec` wrapping ToolEntry.
- **No CLI today:** zero `[project.scripts]`; cyclopts already core dep. Surface
  path = add `cisterna = "cisterna.cli:app"` + an `assets export` sub-app.
- **No in-repo assets:** cisterna ships none; `.claude/` only has worktrees, `.agent/` empty.
- **Conventions:** Python 3.13, never-raise, `py.typed`, lazy `__getattr__` for
  optional-dep imports, flat `tests/test_*.py` + autouse registry-clean fixtures, uv.

## 3. Open design forks (for BRAINSTORM)

1. **M3 vertical slice:** full IR + all 4 surfaces, or a thin slice (IR + Claude
   adapter + validate) with other surfaces as M3.x follow-on? (Mission roadmap
   splits M4=bundle+claude+validate, M5=remaining adapters+registry.)
2. **Asset source:** on-disk manifest model (praxia parity, file-driven) vs the
   live M2 `ToolEntry` registry (cisterna-unique) vs both. Determines the whole shape.
3. **Writer abstraction:** adopt praxia's pure `Bundle -> {path: contents}` +
   thin caller-writes-I/O model (recommended — clean, testable), vs stateful Writer.
4. **Determinism/attestation:** port sha256 bundle hashing + drift golden tests
   for `validate`? (Strong fit for a "validate" subcommand.)
5. **Capability translation:** port the abstract-verb → per-vendor tool-name map
   (`vendor_tools.toml` equivalent), or start with literal tool names?
