---
title: Cisterna M3.1c — Antigravity CLI emitter — Buildable Spec (rev1)
backlog_id: 2559
parent_backlog_id: 2326
depends_on: 2487
prior_research: 260623_m31b-antigravity-scope.md
created_at: 2026-06-23
---

# Cisterna M3.1c — Buildable Spec (rev1)

**Scope:** Backlog **#2559** — `AntigravityEmitter`, `export --surface antigravity`, golden validate, hook filter for `antigravity` token.  
**Closes:** Parent epic **#2326** when VERIFY PASS.

**Schema bet (L22):** Port praxia `bundle_antigravity.rs` — `gemini-extension.json` + companion files. No `plugin.json` migration until doc gate proves otherwise.

---

## Locked decisions

| ID | Decision |
|----|----------|
| L22 | **Antigravity schema** — `gemini-extension.json` per praxia; `contextFileName: "GEMINI.md"`; `commands` = name strings only (L19 extension); no command body files |
| L23 | **Emit surface token** — `antigravity` for export/validate; capability surface remains `antigravity_cli` |
| L24 | **Hook filter** — extend `hooks_for_surface` with `antigravity`; empty `surfaces` includes antigravity (alongside claude/cursor/copilot per L15) |
| L25 | **Agent paths** — `agents/<n>.md` (plain `.md`, not `.agent.md`) |
| L26 | **Hooks output** — `hooks/hooks.json` with Claude-shaped nested structure (praxia `build_claude_hooks` dialect) |
| L27 | **Provenance** — no `cisterna-provenance.json` on antigravity export (L18 extension) |
| L28 | **Listing rules** — emit agent/skill/command name arrays in `gemini-extension.json` only when corresponding bodies exist (non-empty); omit empty arrays |

---

## Emitter contract (`src/cisterna/export/antigravity.py`)

| Path | Content |
|------|---------|
| `gemini-extension.json` | `name`, `version`, `agents[]`, `skills[]`, `commands[]`, `contextFileName`, `settings`, optional inline `mcpServers` |
| `agents/<n>.md` | YAML frontmatter + body when body non-empty |
| `skills/<n>/SKILL.md` | when body non-empty |
| `hooks/hooks.json` | filtered hook_specs, PascalCase events |
| `.mcp.json` | when `mcp_servers` non-empty (praxia parity) |

---

## CLI delta

| Subcommand | Change |
|------------|--------|
| `export` | `--surface antigravity` |
| `validate` | `--surface antigravity` + golden `tests/golden/antigravity/names_only/` |

---

## Acceptance criteria

| AC | Given | When | Then |
|----|-------|------|------|
| AC-M31c-1 | manifest_minimal bundle | `AntigravityEmitter.emit()` | `gemini-extension.json` + agents/skills/hooks files |
| AC-M31c-2 | hook `surfaces=["antigravity"]` | antigravity vs cursor emit | hook only on antigravity |
| AC-M31c-3 | golden fixture | `validate --surface antigravity` | exit 0 |
| AC-M31c-4 | M3.1a/b paths | full pytest | all prior ACs green |
| AC-M31c-5 | any bundle | `export --surface antigravity` | writes gemini-extension layout |
| AC-M31c-6 | `resolve_tools(..., "antigravity_cli")` | unit test | maps read+search per vendor_tools.toml |

---

## Implementation DAG

```
N13 AntigravityEmitter + tests (AC-M31c-1)
N14 hooks_for_surface antigravity + AC-M31c-2
N15 CLI --surface antigravity + golden + AC-M31c-3/5
N16 regression AC-M31c-4 + capability test AC-M31c-6
```

---

## References

- `.praxia/docs/research/260623_m31b-antigravity-scope.md`
- `praxia/crates/praxia-agent-assets/src/bundle_antigravity.rs`
- M3.1b rev3: `.praxia/docs/specs/260623_m31b-buildable-spec-rev3.md`
