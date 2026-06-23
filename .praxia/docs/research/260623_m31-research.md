---
title: M3.1 Agent-Asset Export — Research Synthesis
date: 2026-06-23
status: research
task_id: 260623_m31-research
backlog_id: 2326
sources:
  - librarian subagent (web + praxia reference recon)
  - NLM notebook 62bff89f-bdc4-4310-8283-ce4706575bac (fast deep research + query)
  - .praxia/docs/research/260618_m3-agent-asset-export-research.md (M3 baseline)
nlm_notebook_id: 62bff89f-bdc4-4310-8283-ce4706575bac
---

# M3.1 Research Synthesis — Pre-Brainstorm

Research gathered before contemplex brainstorm for backlog **#2326** (M3.1 epic).
M3 shipped registry-sourced Claude-only export; M3.1 adds file/manifest source,
remaining surfaces, capability mapping, validate/inspect, and per-command bodies.

---

## Executive summary

1. **Four surfaces diverge materially** — manifest location, agent suffix (`.md` vs
   `.agent.md`), hook event vocabulary (PascalCase vs camelCase), MCP file placement
   (inline vs `.mcp.json` vs `mcp.json`), and command representation (paths vs names
   vs TOML). Praxia Rust emitters encode these dialects; cisterna ports behind the
   existing pure-emit `Emitter` ABC.

2. **B1 lesson remains load-bearing** — M3 emits command **names only** in
   `plugin.json` (praxia-parity). Official Claude docs describe `commands` as
   **paths** to `.md` files. M3.1 must either emit validated `commands/<name>.md`
   bodies or document an explicit manifest-only mode with runtime proof.

3. **Capability layer is the portable core** — 14 abstract verbs in praxia
   `capability.rs` + `vendor_tools.toml` maps + `model_hint` → vendor model strings.
   Empty map entries and missing `[export.models.cursor]` are silent-degradation risks.

4. **Validate = two layers** — (a) per-surface structural/schema gates, optionally
   delegating to `claude plugin validate`; (b) deterministic golden drift via sorted
   path→content hashing (praxia `surface_bundle_sha256` pattern).

5. **ManifestAssetSource is specified in praxia** (`.praxia/manifest.toml` →
   `manifest.rs`) but not wired as a unified `AssetSource` protocol in Rust.
   `CompositeAssetSource` + Python entry-point plugins are M3.1 design targets.

---

## Per-surface format matrix

| Surface | Manifest | Agents | Skills | Hooks | MCP | Commands |
|---------|----------|--------|--------|-------|-----|----------|
| **Claude** | `.claude-plugin/plugin.json` | `agents/<n>.md` + YAML FM | `skills/<n>/SKILL.md` | `hooks/hooks.json` PascalCase | `.mcp.json` | Docs: paths to `./commands/*.md`; praxia: name strings |
| **Cursor** | `.cursor-plugin/plugin.json` | `agents/<n>.agent.md` | same | `.cursor/hooks.json` camelCase v1 | `mcp.json` | `commands/*.md` + frontmatter |
| **Copilot** | `plugin.json` | `agents/<n>.agent.md` | same | inline in manifest OR `hooks.json` | `.mcp.json` | `.md` commands |
| **Antigravity** | `gemini-extension.json` | `agents/<n>.md` | same | `hooks/hooks.json` | inline `mcpServers` | TOML in `commands/` (Gemini docs); praxia adds name arrays |

**Official references:** [Claude plugins](https://code.claude.com/docs/en/plugins-reference),
[Cursor plugins](https://cursor.com/docs/reference/plugins),
[Copilot CLI plugins](https://docs.github.com/en/copilot/reference/cli-plugin-reference),
[Gemini extensions](https://geminicli.com/docs/extensions/reference/).

**Antigravity transition risk:** Gemini CLI → Antigravity CLI (2026); extension
format may drift toward `plugin.json`. Track Antigravity docs before locking emitter.

---

## Praxia reference (verified anchors)

| Component | Path | Notes |
|-----------|------|-------|
| Claude emitter | `praxia-agent-assets/src/bundle_claude.rs` | Names-only commands; agents/skills bodies emitted |
| Cursor emitter | `bundle_cursor.rs` | Fail-closed: may list agents in manifest without files when `agents_path_verified=false` |
| Copilot emitter | `bundle_copilot.rs` | Inline camelCase hooks |
| Antigravity emitter | `bundle_antigravity.rs` | Superset `gemini-extension.json` |
| Capabilities | `capability.rs` + `vendor_tools.toml` | 14 verbs; per-vendor maps |
| Manifest parser | `praxia-config/src/manifest.rs` | `[[plugin.skills]]`, `[[plugin.agents]]`, `[[plugin.hook_specs]]`, etc. |
| Hook surface filter | `hooks_emit.rs` | `valid_surfaces = ["claude","cursor","antigravity"]` — **copilot missing** |
| Hash/drift | `bundle.rs:surface_bundle_sha256` | Sorted path→contents map |

---

## M3.1 scope → research findings

| #2326 item | Research conclusion |
|------------|---------------------|
| ManifestAssetSource | Port `manifest.rs` shape; resolve relative paths; validate snippet scope enum |
| AssetSource Protocol + Composite | Design in Python; precedence: manifest > registry (TBD at brainstorm) |
| Cursor/Copilot/Antigravity emitters | Port praxia adapters behind `Emitter` ABC; surface-specific hook/MCP/command dialects |
| Capability enum/map + model_hint | Port `capability.rs` + TOML maps; fail on required verb with empty map |
| validate subcommand | Schema checks + golden hash compare + optional `claude plugin validate` subprocess |
| inspect subcommand | Print `AssetBundle` IR JSON + planned emission tree (dry-run companion) |
| entry_point plugins | `[project.entry-points."cisterna.emitters"]` — no praxia precedent |
| HookSpec surface filter | Add `copilot`; align bundle adapters with `hooks_emit.rs` |
| per-command `.md` | Source body from manifest paths or generated from ToolEntry; **must pass vendor validate** |

---

## NLM synthesis — top design risks

1. **Command format divergence** — Antigravity TOML vs Markdown elsewhere.
2. **MCP placement** — inline (Antigravity) vs dotted file (Claude/Copilot) vs undotted (Cursor).
3. **Cursor frontmatter strictness** — invalid YAML breaks load silently.
4. **Path/layout** — Claude manifest in `.claude-plugin/` but components at plugin root.
5. **Antigravity env vars** — must declare in `settings` array or extension breaks.

**Recommended validation:** golden bundles per surface in CI; `validate` compares
re-emit hash to stored golden; delegate to native CLIs where available.

---

## Gate-passes-while-feature-broken watchlist

| Scenario | Mitigation |
|----------|------------|
| Names-only `commands` in manifest | Require `commands/<n>.md` OR explicit manifest-only mode + smoke test |
| Cursor agents listed, files omitted | Validate file existence or strip manifest entries |
| Empty capability map | Hard error for required verbs |
| Antigravity extra manifest keys | Schema-strict mode + optional smoke test |
| Golden hash only | Pair with structural validator + frontmatter lint |

---

## Open questions for brainstorm

1. Command body source: manifest paths vs registry `__doc__` vs both via Composite?
2. Claude command schema: run `claude plugin validate` on fixtures before locking frontmatter?
3. Manifest inventory: name arrays (praxia) vs path arrays (vendor docs) vs dual-write?
4. Antigravity bet: `gemini-extension.json` vs migrate to Antigravity `plugin.json`?
5. Cursor fail-closed: fail validate when agents listed but files absent?
6. Sprint decomposition: one epic vs phased M3.1a (manifest+validate) / M3.1b (surfaces 2–4)?

---

## Sources

**NLM notebook:** `62bff89f-bdc4-4310-8283-ce4706575bac` ("cisterna M3.1 agent-asset export")

**Official:** Claude, Cursor, Copilot, Gemini extension docs (URLs above); Google Antigravity
transition blog.

**Community validation:** [claudelint](https://github.com/donaldgifford/claudelint),
[claude-plugin-validate](https://crates.io/crates/claude-plugin-validate)

**Internal:** M3 spec `.praxia/docs/specs/260618_m3-buildable-spec.md`; M3 research
`.praxia/docs/research/260618_m3-agent-asset-export-research.md`; praxia
`crates/praxia-agent-assets/`.
