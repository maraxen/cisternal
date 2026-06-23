---
title: Cisterna M3.1 — Agent-Asset Export — Buildable Spec (rev2, adversarially reconciled)
date: 2026-06-23
status: spec
task_id: 260623_autonomous-loop
backlog_id: 2326
brainstorm_session: 477b0d3d
review: spec-challenger (NEEDS_WORK) + spec-defender reconciled rev2
research: .praxia/docs/research/260623_m31-research.md
winner: PHASED-A (M3.1a + M3.1b split)
---

# Cisterna M3.1 — Buildable Spec (rev2)

**Brainstorm winner:** PHASED-A — M3.1a infrastructure, M3.1b Cursor+Copilot.
Antigravity + entry_point plugins → M3.2.

M3 behavior preserved: `ClaudeEmitter()` default = names-only manifest (AC-M31a-4 pins AC-M3-5/6).

---

## Locked decisions

| ID | Decision |
|----|----------|
| L1 | **AssetSource Protocol** — `load() -> LoadReport`; never-raise on load |
| L2 | **CompositeAssetSource** — manifest overrides registry by `(kind, name)`; registry fills gaps only |
| L3 | **Composite conflicts** — incompatible payload → `LoadReport.warnings`; `inspect` prints warnings; `validate` exit 1 |
| L4 | **ManifestAssetSource** — port praxia `.praxia/manifest.toml` (`manifest.rs`); paths relative to manifest root |
| L5 | **Capability** — 14 verbs + `resolve_tools(tokens, surface)` + `resolve_model_hint(hint, surface)` |
| L6 | **`ClaudeEmitter(emit_command_bodies=False)`**; CLI `--emit-command-bodies` on export/validate |
| L6b | **Body precedence:** manifest path → registry-generated template → empty (validate fails if emit bodies on) |
| L7 | **validate** — structural checks + golden hash; optional `--use-native-cli` |
| L8 | **Cursor fail-closed** — omit manifest entries for agents/skills not emitted as files |
| L9 | **Golden storage** — `tests/golden/<surface>/<mode>/` (`names_only` \| `with_command_bodies`) |
| L10 | **Deferred M3.2** — AntigravityEmitter, entry_point plugins |
| L11 | **Claude commands inventory** — `plugin.json` lists **name strings** (praxia/M3 parity); bodies in `commands/<name>.md` when L6 enabled |
| L12 | **Manifest commands** — use `plugin.export_command.claude_code` path list (praxia shape); no `[[plugin.commands]]` invented |
| L13 | **Registry in composite** — commands only from registry; agents/skills/hooks manifest-only in M3.1a |
| L14 | **Workflows/pipelines/snippets** — parsed for validate only; not loaded into `AssetBundle` in M3.1a |

---

## AssetBundle IR extension (M3.1a)

```python
@dataclass(frozen=True, slots=True)
class SkillAsset:
    name: str
    description: str = ""
    body: str = ""

@dataclass(frozen=True, slots=True)
class AgentAsset:
    name: str
    description: str = ""
    tools: tuple[str, ...] = ()   # capability tokens and/or pass-through
    model: str | None = None
    body: str = ""

@dataclass(frozen=True, slots=True)
class HookSpecAsset:
    event: str
    matcher: str
    script: str
    tier: str = ""
    surfaces: tuple[str, ...] = ()  # empty = all surfaces

@dataclass(frozen=True, slots=True)
class LoadReport:
    bundle: AssetBundle
    warnings: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()  # merge conflict messages
```

**Sort invariants:** `skills` by name; `agents` by name; `hook_specs` by `(event, matcher, script)`; commands unchanged.

**Manifest mapping:**

| manifest.rs | IR |
|-------------|-----|
| `[[plugin.skills]]` | `SkillAsset` (read `path`) |
| `[[plugin.agents]]` | `AgentAsset` (`tools` or frontmatter `default_tools`) |
| `[[plugin.hook_specs]]` | `HookSpecAsset` |
| `plugin.mcp` | single `McpAsset(name=plugin.name, ...)` |
| `export_command.claude_code` | command paths → `CommandAsset` |
| workflows/pipelines/snippets | not in IR (inspect note only) |

---

## `registry_bundle()` (N2)

```python
def registry_bundle(registry: str = "default", *, metadata: BundleMetadata | None = None) -> AssetBundle
```

Maps `registry_assets()` → `CommandAsset` (body `""`); empty agents/skills/hooks/mcp; never raises.

---

## Capability resolution

1. Token is `Capability` verb → map via `vendor_tools.toml`; empty map → `ValueError`
2. Pass-through (`mcp__*`, allowed_names) → append verbatim
3. Unknown token → `ValueError`
4. Agent tools: manifest `tools` vec, else YAML `default_tools` from agent file

---

## Composite merge + equality

```
manifest wins by name; registry fills gaps only.
Conflict when same (kind, name) AND payloads differ:
  commands: description or body differ
  mcp_servers: command argv or env differ
  agents: body or tools differ
  skills: body or description differ
  hook_specs: any field differs
manifest payload kept; registry item discarded; conflict recorded.
```

---

## CLI contracts

| Command | Input | Output |
|---------|-------|--------|
| `inspect` | `--manifest PATH`, `--registry NAME`, `--resolve-tools`, `--surface` | JSON `LoadReport` + optional `resolved_tools`; no writes |
| `validate` | same + `--surface`, `--emit-command-bodies`, `--use-native-cli` | exit 0/1; re-emit in-process, compare golden hash |
| `export` | existing flags + `--emit-command-bodies` | unchanged M3 default |

Default source: `CompositeAssetSource(manifest_path, registry)`.

---

## M3.1a acceptance criteria

| AC | Given | When | Then |
|----|-------|------|------|
| AC-M31a-1 | Valid manifest with skills/agents/hook_specs | `ManifestAssetSource.load()` | `LoadReport.bundle` populated; bodies loaded; never raises |
| AC-M31a-2 | Manifest + registry command `foo` different body | load → inspect / validate | Manifest wins; inspect warning; validate exit 1 |
| AC-M31a-3 | `tokens=("read","search")` | `resolve_tools(..., "claude_code")` | Concrete tools; invalid token raises |
| AC-M31a-3b | Agent `tools=[]`, file has `default_tools: [read, search]` | `ManifestAssetSource.load()` | `AgentAsset.tools == ("read", "search")` |
| AC-M31a-4 | default ctor | `ClaudeEmitter().emit(bundle)` | Byte-identical to M3 (AC-M3-5/6) |
| AC-M31a-5 | `emit_command_bodies=True`, body set | `ClaudeEmitter(emit_command_bodies=True).emit()` | `commands/foo.md` + `commands: ["foo"]` in manifest |
| AC-M31a-6 | golden fixture | `validate --surface claude` | exit 0 match / 1 drift |
| AC-M31a-7 | any bundle | `inspect` | JSON stdout, no writes |
| AC-M31a-8 | manifest command path missing | `validate` | exit 1 |
| AC-M31a-9 | registry tools | `registry_bundle()` | sorted commands; empty other kinds |
| AC-M31a-10 | agent tools `("read",)` | `inspect --resolve-tools --surface claude_code` | JSON includes resolved concrete tools |

## M3.1b acceptance criteria

| AC | Given | When | Then |
|----|-------|------|------|
| AC-M31b-1 | bundle agents+hooks | `CursorEmitter.emit()` | `.cursor-plugin/plugin.json`, hooks camelCase; files if emitted |
| AC-M31b-2 | same | `CopilotEmitter.emit()` | `plugin.json`, inline hooks, `agents/*.agent.md` |
| AC-M31b-3 | hook `surfaces=["cursor"]` | export cursor vs copilot | hook only on cursor |
| AC-M31b-4 | golden | `validate --surface cursor\|copilot` | hash pass |
| AC-M31b-5 | M3 export path | pytest | all M3 ACs green |
| AC-M31b-6 | cursor export, no agent files | manifest | agents key **absent** (not empty array) |
| AC-M31b-7 | skill path missing | cursor validate | exit 1 (L8 extended to skills) |

---

## Implementation DAG (rev2)

**M3.1a**
```
N0  IR extension (Skill/Agent/HookSpec/LoadReport) + tests
N1  AssetSource Protocol
N2  ManifestAssetSource (manifest.rs + export_command.claude_code)
N3  registry_bundle + CompositeAssetSource + conflict fixtures
N4  Capability enum + vendor_tools + resolve_tools/model_hint
N5  inspect CLI
N6  validate + golden harness (names_only + with_command_bodies)
N7  ClaudeEmitter command bodies (L6/L11)
N8  integration + docs
```

**M3.1b**
```
N9  CursorEmitter (L8 fail-closed)
N10 CopilotEmitter + HookSpec surface filter (incl. copilot)
N11 CLI --surface cursor|copilot + golden + regression
```

---

## Deferred M3.2

**Shipped in M3.1c (#2559):** AntigravityEmitter — see `.praxia/docs/specs/260623_m31c-buildable-spec-rev1.md`.

**Remaining M3.2:**

entry_point plugins — **shipped M3.2 #2563**.

**Remaining M3.3 (#2581):**

**Shipped M3.3a:** public `registration.snapshot()` + `list_registries()` — see `.praxia/docs/specs/260623_m33a-snapshot-api-rev1.md`.

WriterSink, vendor path-array command mode, L14 workflow/pipeline/snippet validate-only parsing.

---

## Adversarial reconciliation log

| Finding | Resolution |
|---------|------------|
| FATAL: no `[[plugin.commands]]` | L12: `export_command.claude_code` paths |
| MAJOR: IR unspecified | AssetBundle extension locked |
| MAJOR: paths vs names TBD | L11 praxia-parity names |
| MAJOR: conflict semantics | L3 + equality table + AC-M31a-2 |
| MAJOR: validate inputs | CLI contracts section |
| MAJOR: AC-M31a-3 role source | AC-M31a-3b + library unit test |
| MAJOR: Claude agents/skills not emitted M3.1a | L13; M3.1b emits; inspect shows IR |
| MAJOR: Cursor skills fail-closed | AC-M31b-7 |
| MINOR: snippets/workflows | L14 defer |

---

## References

- M3: `.praxia/docs/specs/260618_m3-buildable-spec.md`
- Research: `.praxia/docs/research/260623_m31-research.md`
- Praxia: `manifest.rs`, `bundle_{claude,cursor,copilot}.rs`
