---
title: "Tool-Surface Triage: Cycle 7 Adversarial Audit"
description: "Cycle 7: sequential challenger/defender pass on the post-Cycle-6 draft spec against plugin/config.py, export/claude.py, and shipped .praxia/skills/; identifies and resolves 3 codebase-integration gaps (GAP-39..41)."
status: complete
task_id: 261106_tool-surface-triage
date: '261108'
author: "challenger_c7 / defender_c7"
verdict: OPEN_GAPS_RESOLVED_IN_CYCLE
---
# Cycle 7 Adversarial Audit: Tool-Surface Triage Spec
Claimed by: challenger_c7 (Challenger), defender_c7 (Defender)

- **Target spec**: `.praxia/docs/specs/261106_tool-surface-triage.md` (post-Cycle-6 revision, `status: draft`)
- **Prior audits**: `.praxia/docs/audits/261106_cycle5_audit.md`, `.praxia/docs/audits/261106_cycle6_audit.md`
- **Date**: 2026-11-08

## Epistemic Disclaimer & Scope of Verification
- **Static source and shipped-skill checks only**: During this cycle, no new runtime code, hooks, or tests were executed (`Touch nothing outside .praxia/docs/`). In addition to the files checked in Cycle 6, Challenger 7 inspected:
  - `src/cisternal/plugin/config.py:14–184` (`marketplace_root_source` vs `resolve_marketplace_root` and `write_user_config`);
  - `src/cisternal/plugin/shared.py:143` (`claude_home` and `$CLAUDE_CONFIG_DIR`);
  - `src/cisternal/plugin/app.py:170–253` (`locate_bundle`, `load_bundle`);
  - `src/cisternal/export/claude.py:145–151, 216–229` (`.mcp.json` and `.claude-plugin/plugin.json` emitted payloads);
  - `.praxia/manifest.toml` and all 4 shipped skill files (`.praxia/skills/{export-trust,run-cisternal,customizing-tools,writing-skill-triggers}/SKILL.md` and `references/*.md`).

---

## Part 1: Challenger 7 Findings Against the Post-Cycle-6 Spec

Claimed by: challenger_c7

While verifying `GAP-23` through `GAP-38` against `src/cisternal/plugin/config.py`, `src/cisternal/export/claude.py`, and `.praxia/skills/`, Challenger 7 uncovered 3 genuine codebase-integration gaps:

### GAP-39: C3 cites `resolve_marketplace_root` (`cli.py:623` / `plugin/config.py:162`), which mutates `~/.config/cisternal/config.toml` on disk when unconfigured
- **Code evidence**:
  - `src/cisternal/plugin/config.py:14–21, 162–184`: `resolve_marketplace_root()` calls `write_user_config()` to create or modify `~/.config/cisternal/config.toml` and prints to `stderr` whenever no plugin marketplace is configured yet.
  - `src/cisternal/plugin/config.py:20, 91`: `marketplace_root_source()` is explicitly documented as the read-only resolver (`":func:`marketplace_root_source` is read-only and never generates anything"`), tested by `tests/test_plugin_app.py:379` (`test_info_never_generates`).
  - `src/cisternal/plugin/shared.py:143` and `tests/test_plugin_app.py:38`: cisternal resolves `~/.claude` via `claude_home()` (`$CLAUDE_CONFIG_DIR` or `~/.claude`).
- **Spec flaw**:
  - In C3, the post-Cycle-6 spec wrote: `installed marketplace plugins (--marketplace <path>, default resolved via resolve_marketplace_root, cli.py:623)`. Calling `resolve_marketplace_root` from a read-only analysis command (`cisternal skill-coverage`, `cisternal prune-list`, or C5's `scan_active_registrations`) would silently create `~/.config/cisternal/config.toml` on unconfigured machines or in tests. Additionally, C0/C1/C5 hardcoded `~/.claude/...` instead of `claude_home()`.

### GAP-40: `scan_active_registrations()` cannot build `canonical_key -> registered_raw_name` from `settings.json` / `.claude.json` / `plugin.json` / `.mcp.json` alone, and C5 lacks a bundle loader when `cwd` is outside the `cisternal` checkout
- **Code evidence**:
  - `src/cisternal/export/claude.py:145–151, 216–229`: `.claude-plugin/plugin.json` contains only `{"name", "version", "description"}` ("No `commands`/`mcpServers` keys — the real schema doesn't have them") and `.mcp.json` contains only `{"mcpServers": {<server>: {"command", "args", "env"}}}`. Neither file—nor `~/.claude/settings.json` or `~/.claude.json`—lists individual MCP tool names such as `run_sql`, `get_run`, or `validate_sidecar`.
- **Spec flaw**:
  - C1 and C5 stated that `scan_active_registrations()` reads only `~/.claude/settings.json`, `~/.claude.json`, `.claude-plugin/plugin.json`, and `.mcp.json` and writes `<sessions dir>/active_servers.json` mapping `canonical key → registered raw name` (e.g. `"bathos/run_sql" -> "mcp__plugin_bathos_bathos__run_sql"`), and that C5's `PreToolUse` hook reads `<raw name>` from `active_servers.json` and "never builds the raw name from the canonical key".
  - Because those four registration JSON files contain only plugin and server names (determining the server's wire prefix `mcp__plugin_<plugin>_<server>__` or `mcp__<server>__`), `scan_active_registrations()` cannot produce `"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"` without also reading the known `(server, tool)` canonical keys from `[families]` and `[verbs]`!
  - Furthermore, C5's `PreToolUse` and `PostToolUse` hooks run in the user's active project directory (`cwd`), which is generally not the `cisternal` repository checkout and may be a wheel install; the spec did not state how `scan_active_registrations()` / C5 loads cisternal's `[verbs]` and `[families]` outside a `cisternal` repo checkout (namely via `locate_bundle` / `loads_snapshot` on `src/cisternal/agent_plugin.json` or checkout `.praxia/manifest.toml` in `src/cisternal/plugin/app.py:170`, plus installed plugin `cisternal-source.json` sidecars).

### GAP-41: C4a Check (b) PascalCase regex and inline-backtick extraction bugs on shipped `.praxia/manifest.toml` skills, plus `[plugin.families]` / `[plugin.verbs]` TOML table paths
- **Code & execution evidence**:
  - Executing the post-Cycle-6 C4a Check (b)/Check (c) regexes in Python against `.praxia/manifest.toml` and all 4 shipped skills (`export-trust`, `run-cisternal`, `customizing-tools`, `writing-skill-triggers`) revealed:
    1. **Broken PascalCase regex**: Check (b)'s pattern `\b[A-Z][a-zA-Z0-9]+[a-z][A-Za-z0-9]*\b` does not require an internal lowercase-to-uppercase transition, so it falsely matches every ordinary sentence-initial capitalized word (`Build` in `run-cisternal`, `Decides` and `Also` in `customizing-tools`). The true PascalCase pattern is `\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b`.
    2. **Triple-backtick fence inversion of inline code spans**: Extracting inline `` `...` `` spans without first stripping ` ```...``` ` fenced code blocks causes the odd (3) backtick count of an opening code fence to invert all subsequent inline backtick pairs—causing `` `emit_event()` `` on line 42 of `run-cisternal/SKILL.md` (after the ` ```bash ` block on line 24) to be missed!
    3. **Hyphenated modifier `"agent-asset"` and Check (c) scope headings**: `run-cisternal/SKILL.md` has `"agent-asset"` in `description` (`"the telemetry substrate + agent-asset export CLI/library"`), which does not appear in any `#` heading or code span; all 4 shipped skills currently lack a `## Scope` or `## When to Use` heading (Check (c)), and `export-trust/SKILL.md` has no frontmatter `description`.
    4. **TOML table path**: Existing `.praxia/manifest.toml` sections sit under `[plugin]` (`[plugin.mcp]`, `[plugin.marketplace]`, `[[plugin.skills]]`), whereas C2/C5 examples wrote top-level `[families]` and `[verbs]`.

---

## Part 2: Defender 7 Dispositions

Claimed by: defender_c7

| ID | Disposition | Defender Resolution Applied to Spec |
|---|---|---|
| **GAP-39** | **Conceded & Fixed** | Updated C1, C3, and C5 to resolve the default marketplace directory via read-only `marketplace_root_source` (`src/cisternal/plugin/config.py:91`) instead of mutating `resolve_marketplace_root` (`:162`), skipping the marketplace scan without creating `~/.config/cisternal/config.toml` when `(None, ...)` is returned; anchored `~/.claude` paths in C0, C1, and C5 to `claude_home()` (`$CLAUDE_CONFIG_DIR` or `~/.claude`, `src/cisternal/plugin/shared.py:143`); added a read-only control in C3 asserting `~/.config/cisternal/config.toml` is not created when unconfigured. |
| **GAP-40** | **Conceded & Fixed** | Specified in C1 and C5 that `scan_active_registrations()`: (1) reads active server registrations from `claude_home() / "settings.json"`, `~/.claude.json`, and enabled plugins' `.claude-plugin/plugin.json` + `.mcp.json` to map each active `server` to its wire prefix (`mcp__plugin_<plugin>_<server>__` for plugin-registered servers, `mcp__<server>__` for standalone servers); (2) loads `[families]` and `[verbs]` from cisternal's own bundle (`locate_bundle` / `loads_snapshot` on `src/cisternal/agent_plugin.json` or checkout `.praxia/manifest.toml`, `plugin/app.py:170`) merged with installed plugin `.claude-plugin/cisternal-source.json` sidecar metadata (`families`, `verbs`, `skills_meta`); and (3) expands every known `(server, tool)` from `[families]` and `[verbs]` on an active server into `active_servers.json["tools"]` (`"<server>/<tool>": "<raw_prefix><tool>"`) alongside cached `verbs` and `families`. |
| **GAP-41** | **Conceded & Fixed** | Fixed Check (b)'s PascalCase regex to `\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b` (requiring an internal lowercase-to-uppercase transition), specified stripping ` ```...``` ` fenced code blocks before matching single-line inline `` `[^`\n]+` `` spans in both C2 and C4a, added `"agent-asset"` to the hyphenated-modifier stopword list in C4a Check (b), documented the concrete C4a Check (c) report-mode findings across the 4 shipped skills in `.praxia/manifest.toml`, and specified that `ManifestAssetSource` supports both top-level `[families]`/`[verbs]` and `[plugin.families]`/`[plugin.verbs]`. |

## Verdict
**OPEN_GAPS_RESOLVED_IN_CYCLE**. Cycle 7 identified and resolved 3 codebase-integration gaps (`GAP-39`..`GAP-41`). Because Cycle 7 conceded new genuine gaps, a sequential Cycle 8 Challenger -> Defender pass is required to verify convergence.
