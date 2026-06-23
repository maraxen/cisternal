# M3.1b scope research — Antigravity emitter timing

**task_id:** `260623_m31b-brainstorm`  
**date:** 2026-06-23  
**context:** PI asked whether Antigravity CLI emitters are planned; if not, fold into M3.1b research/brainstorm.

## Current plan (locked in rev2 spec)

| Artifact | Antigravity stance |
|----------|-------------------|
| `260623_m31-buildable-spec.md` rev2 | **Deferred M3.2** (L10): AntigravityEmitter, entry_point plugins |
| Backlog #2487 | Title: **Cursor + Copilot emitters only** |
| M3.1 brainstorm winner PHASED-A | M3.1b = Cursor/Copilot; Antigravity → M3.2 |
| User decision `ANTIGRAVITY-DEFER` | Ship three surfaces; wait for format stabilization |

**M3.1b DAG in spec (N9–N11):** CursorEmitter, CopilotEmitter, HookSpec surface filter, golden cursor\|copilot — **no Antigravity node**.

## What already exists in cisterna

| Asset | Status | Evidence |
|-------|--------|----------|
| `vendor_tools.toml` `[antigravity_cli]` | Stub present | `src/cisterna/assets/data/vendor_tools.toml:19-21` |
| `resolve_tools(..., "antigravity_cli")` | Callable (untested in ACs) | Same TOML; capability.py loads all surfaces |
| `AntigravityEmitter` | **Not implemented** | No `src/cisterna/export/antigravity.py` |
| Golden `tests/golden/antigravity/` | **Missing** | Only `claude/` harness exists |
| Praxia reference | **Complete** | `praxia/crates/praxia-agent-assets/src/bundle_antigravity.rs` |

## Praxia Antigravity shape (port target)

Emits `gemini-extension.json` with:

- `name`, `version`, `agents[]`, `skills[]`, `commands[]` (name strings)
- `contextFileName: "GEMINI.md"`
- Inline `mcpServers` (not separate `.mcp.json` in top-level map — praxia also emits `.mcp.json` when non-empty)
- `settings` object (env vars must be declared per research risk #5)
- `agents/<n>.md` with YAML frontmatter (`name`, `description`, `tools`, optional `model`)
- `skills/<n>/SKILL.md`, `hooks/hooks.json` (PascalCase, shared with Claude dialect in praxia)

**Command format risk (research Q4):** Gemini docs mention TOML in `commands/`; praxia uses name arrays like Claude. Cisterna should follow **praxia parity** unless Antigravity CLI docs mandate TOML (UNVERIFIED without fresh doc fetch).

## Antigravity format drift risk

From `260623_m31-research.md`:

- Gemini CLI → Antigravity CLI transition (2026) may move toward `plugin.json`
- Research open Q4: `gemini-extension.json` vs Antigravity `plugin.json`
- **UNVERIFIED** as of this memo — needs librarian/doc check before locking emitter schema

## Options for brainstorm

| Option | Scope | Pros | Cons |
|--------|-------|------|------|
| **A — Spec-locked** | M3.1b = Cursor + Copilot only (#2487) | Matches approved rev2; smallest blast radius | Parent #2326 needs M3.2 child for Antigravity |
| **B — Expand M3.1b** | M3.1b = Cursor + Copilot + Antigravity | One epic closes four-surface parity | Format drift risk; +1 emitter + golden + ACs; slips M3.1b |
| **C — M3.1b + M3.1c split** | M3.1b Cursor/Copilot; new #M3.1c Antigravity after doc gate | De-risks format bet; keeps Cursor/Copilot on schedule | Extra backlog item; #2326 stays open longer |
| **D — Antigravity stub** | M3.1b ships `AntigravityEmitter` behind feature flag / `--surface antigravity` with `gemini-extension.json` frozen to praxia | Early integration test; inspect/validate harness reused | May churn if Google changes schema |

## Recommendation for brainstorm forcing beat

1. **Default:** Keep **Option A** unless PI explicitly expands scope — rev2 spec and #2487 backlog are aligned.
2. If PI wants Antigravity in this cycle: prefer **Option C** (separate M3.1c after doc verification) over bolting into M3.1b mid-sprint.
3. Regardless: add **research gate** — one librarian pass on Antigravity extension schema before any emitter code.

## Dependencies on M3.1a (shipped)

- IR + Composite + capability maps ✅
- `validate --surface` + golden harness ✅ (claude only; pattern extends to cursor/copilot/antigravity)
- HookSpec `surfaces` filter — **M3.1b deliverable** (praxia `valid_surfaces` includes antigravity, not copilot — reconcile in design)

## Sources

- `.praxia/docs/specs/260623_m31-buildable-spec.md` § Deferred M3.2, § M3.1b ACs
- `.praxia/docs/research/260623_m31-research.md` § surface matrix, open Q4
- `praxia/crates/praxia-agent-assets/src/bundle_antigravity.rs`
- `src/cisterna/assets/data/vendor_tools.toml`
