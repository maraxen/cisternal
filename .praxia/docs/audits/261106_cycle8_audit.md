---
title: "Tool-Surface Triage: Cycle 8 Adversarial Verification Audit"
description: "Cycle 8: sequential challenger/defender verification pass on the post-Cycle-7 draft spec; all Cycle 5, Cycle 6, and Cycle 7 gaps (GAP-23..41) verified resolved in spec text and aligned with cisternal source code, yielding no new genuine spec gaps while remaining in draft status pending implementation tests."
status: complete
task_id: 261106_tool-surface-triage
date: '261108'
author: "challenger_c8 / defender_c8"
verdict: NO_NEW_GENUINE_GAPS
---
# Cycle 8 Adversarial Verification Audit: Tool-Surface Triage Spec
Claimed by: challenger_c8 (Challenger), defender_c8 (Defender)

- **Target spec**: `.praxia/docs/specs/261106_tool-surface-triage.md` (post-Cycle-7 revision, `status: draft`)
- **Prior audits**: `.praxia/docs/audits/261106_cycle5_audit.md`, `.praxia/docs/audits/261106_cycle6_audit.md`, `.praxia/docs/audits/261106_cycle7_audit.md`
- **Date**: 2026-11-08

## Epistemic Disclaimer & Scope of Verification
- **Static source and shipped-skill checks only**: During this cycle, no runtime code, hooks, or tests for `Pre-0`, `Pre-1`, or `C0`–`C6` were executed (`Touch nothing outside .praxia/docs/`). Every code citation in `.praxia/docs/specs/261106_tool-surface-triage.md` was checked by reading the corresponding file and line range in the worktree (`src/cisternal/cli.py`, `src/cisternal/assets/{bundle,skill_schema,manifest,manifest_extensions,composite,snapshot,inspect_json,validate_golden,bridge}.py`, `src/cisternal/export/{claude,_markdown}.py`, `src/cisternal/plugin/{app,config,shared,repo}.py`, `src/cisternal/adapters/base.py`, `src/cisternal/telemetry/{pipeline,context,record,otlp_exporter}.py`, `.praxia/manifest.toml`, `.praxia/skills/*/SKILL.md`, and `tests/test_{skill_schema,self_manifest,cli_assets_inspect,plugin_app,plugin_repo}.py`).
- **Unverified runtime items**: The following remain explicitly `UNVERIFIED` until the implementation worktree builds the code and executes the test suite and probes:
  - **A5**: Claude Code's 1% shared skill-listing budget and `skillListingMaxDescChars` behaviour;
  - **A6 & RISK-01**: Claude Code transcript record structure on disk (`claude_home() / "projects"`) and `PostToolUse` / `PostToolUseFailure` stdin payload shapes (including `PassthroughAdapter` wire-level error routing);
  - **A7**: Whether `PreToolUse` `additionalContext` nudges change agent tool-selection behaviour (out of scope; requires a matched-session A/B study);
  - **A8 (external repos, RISK-02)**: Exact top-level error keys returned by external `contemplex.errors.err_envelope` and `myxcel` in-band tool errors, pending captured real error fixtures under `tests/fixtures/hooks/post_tool_use/`;
  - **A9**: Whether `subagent_headless` sessions differ in MCP vs CLI usage from `main_interactive` sessions, pending C0's registered run;
  - **All test controls**: POSIX `O_APPEND` multiprocessing test, Pre-0 golden and compound tokenizer tests, C5 150 ms p95 warm/cold latency benchmarks, C3 50-turn precision and 30-session recall evaluations, and C4b paired fire-rate runs.
- Because none of these runtime tests have been executed yet, the spec frontmatter intentionally remains `status: draft`.

---

## Part 1: Challenger 8 Verification of Cycle 5, Cycle 6 & Cycle 7 Gap Resolutions (`GAP-23`..`GAP-41`)

Claimed by: challenger_c8

Challenger 8 audited each of the 19 gaps (`GAP-23` through `GAP-41`) and 2 risks (`RISK-01`, `RISK-02`) against `.praxia/docs/specs/261106_tool-surface-triage.md` and the worktree source files:

| ID | Summary | Spec Location | Challenger 8 Audit Result |
|---|---|---|---|
| **GAP-23** | Ownership of `active_servers.json` rebuilds and `C1 -> C5` graph edge. | C1 (lines 133–137), C5 (lines 245, 291), Graph (lines 328–369) | **Resolved in spec**: `scan_active_registrations()` in `src/cisternal/usage/registrations.py` is shared by C1 and C5; `PreToolUse` lazily creates/rebuilds `<sessions dir>/active_servers.json` via temp-file + `os.replace` on missing or stale mtime; `(Pre-0, C0, C1, C2) -> C5` is in C5 Prerequisites and the ASCII graph; warm and cold cache paths are both covered under the 150 ms p95 benchmark test. |
| **GAP-24** | Definition of quoted tool names in skills for C2 dangling check. | C2 (lines 160–164, 181–183) | **Resolved in spec**: Only backticked tokens (plus `allowed_tools` / `disallowed_tools`) matching raw `mcp__...` or `<server>/<tool>` (where `<server>` is in the hermetic declared-server set) are checked; bare identifiers (`` `run_sql` ``) and relative paths/crate features (`` `references/foo.md` ``, `` `pyo3/extension-module` ``) are excluded with an explicit false-positive control. |
| **GAP-25** | Compound shell command handling in CLI tokenizer (`&&`, `\|\|`, `;`, `\|`). | Pre-0 (lines 84–86, 93), C0 (line 120), C5 (lines 291–303, 309) | **Resolved in spec**: `parse_cli_commands` splits unquoted `&&`, `\|\|`, `;`, `\|`, `&`, `\n` and skips segments with unquoted `$(...)` / backticks before the verb or unclosed quotes fail-open. C0 counts all matched segments; C5 iterates segments left-to-right and nudges on the first non-excluded, active, non-suppressed match. |
| **GAP-26** | Session-dir divergence between `PostToolUse` and `PreToolUse` when `cwd` changes. | Derived-data dirs (line 63), C5 (lines 277, 312) | **Resolved in spec**: Hook subprocesses resolve layer-3 `pyproject.toml` from `$CLAUDE_PROJECT_DIR` when set and skip layer 3 when unset, with a cross-cwd decoy-`pyproject.toml` control test. |
| **GAP-27** | Ambiguity in C3 precision $\ge 0.80$ threshold (point estimate vs lower bound). | C0 (line 123), C3 (line 202) | **Resolved in spec**: Registered threshold is explicitly the point estimate $\hat{p} = \text{TP} / (\text{TP} + \text{FP}) \ge 0.80$ over $n \ge 50$ matched turns (with two-sided Wilson 95% interval reported alongside, and `INCONCLUSIVE` when $n < 50$). |
| **GAP-28** | Hard-coded `mcp__bathos__run_sql` in C5 nudge output. | C5 (lines 298–301) | **Resolved in spec**: Nudge prints `<raw name>` from `active_servers.json["tools"][canonical_key]`. |
| **GAP-29** | Non-recursive transcript glob missing `<slug>/<session-id>/subagents/*.jsonl`. | Pre-0 (line 87), C0 (lines 120, 127) | **Resolved in spec**: `discover_transcript_files` reads both `<slug>/*.jsonl` and `<slug>/<session-id>/subagents/*.jsonl`, with a synthetic multi-stratum directory control. |
| **GAP-30** | Worktree slugs splitting one repository in C1 `enable-per-project` and per-repo $N$. | Pre-0 (line 90), C1 (lines 140–146, 154) | **Resolved in spec**: `resolve_repo_key(session_cwd, slug)` strips `/.claude/worktrees/<name>` (and `/.worktrees/<name>`), resolves `git rev-parse --git-common-dir` parent when on disk, and falls back to stripping `--claude-worktrees-<suffix>` from `slug`, with a worktree-folding control. |
| **GAP-31** | Nonexistent `src/cisternal/assets/skills/` path in C3 migration and C6. | C3 (line 199), C6 (line 319) | **Resolved in spec**: Points to `[[plugin.skills]]` in `.praxia/manifest.toml` (`.praxia/skills/<name>/SKILL.md`). |
| **GAP-32** | Bare `run_sql` planted in C0 synthetic transcript contradicting Shared Definitions. | C0 (line 126) | **Resolved in spec**: Synthetic transcript uses `mcp__plugin_bathos_bathos__run_sql` (×3) + `mcp__bathos__run_sql` (×2) = 5; bare `run_sql` in a transcript is not counted as an MCP call. |
| **GAP-33** | Non-hermetic machine-local registration check in C2 `assets validate`. | C2 (lines 165, 184) | **Resolved in spec**: `assets validate` builds its known-tool set hermetically from `[families]`, `[verbs]`, and `AssetBundle.commands`, with an empty-`HOME` control test. |
| **GAP-34** | Exported `SKILL.md` dropping `covers_families` / `distinctive_strings` and C3 skill sources. | C3 (lines 190–194, 208) | **Resolved in spec**: `format_skill_markdown` stays restricted to documented Claude Code keys; `publish_bundle` writes `skills_meta`, `families`, and `verbs` into `.claude-plugin/cisternal-source.json` and `snapshot.py` round-trips the fields; C3 reads `--manifest` and `--marketplace` plugins and lists skills without metadata under `unmonitored_skills`. |
| **GAP-35** | Fatal `LoadReport.warnings` breaking warn-only C2 (R3) and C4a report mode. | Shared Definitions (line 71), C2 (lines 167–168), C3 (line 198), C4a (line 229) | **Resolved in spec**: `LoadReport` adds `advisories: tuple[str, ...] = ()` logged in `validate_assets` without changing the exit code and ignored by `publish-shared`, `snapshot`, and `plugin install`. |
| **GAP-36** | `CompositeAssetSource.merge_registry`, `snapshot.py` late defaults, and golden digests. | Shared Definitions (lines 72–75), C2 (line 178), C5 (line 251), C6 (line 321) | **Resolved in spec**: `AssetBundle` carries `families` and `verbs` forwarded by `merge_registry` and ignored by `asset_bundle_to_praxia_json`; `dumps_snapshot` omits empty defaults via `_SKILL_LATE_DEFAULTS` and `bundle_from_dict` restores them; `.praxia/manifest.toml` asset changes update `src/cisternal/agent_plugin.json` and `tests/golden/{,rust_parity/}self_manifest/`. |
| **GAP-37** | C4a Check (a)/Check (b) contradiction on `distinctive_strings` / `covers_families` and `--baseline-ref` on new skills. | C4a (lines 216–227, 231–233) | **Resolved in spec**: Check (b) checks only tokens extracted from the listing text (with `distinctive_strings` governed by Check (a) and `covers_families` excluded from prose heading requirements); `--baseline-ref` skips baseline comparison for newly added skill paths and exits 2 on invalid git refs. |
| **GAP-38** | Missing explicit Source of truth / Delivery / Controls on C4a, C4b, and C6. | C4a (lines 214, 230–233), C4b (lines 235–242), C6 (lines 318–327) | **Resolved in spec**: Every component C0–C6 (including C4a, C4b, and C6) has explicit `Source of truth`, `Delivery`, and paired negative/positive `Controls`. |
| **GAP-39** | Read-only `marketplace_root_source` vs mutating `resolve_marketplace_root` and `claude_home()`. | C0 (line 120), C1 (lines 131–133), C3 (lines 190, 207), C5 (line 291) | **Resolved in spec**: Read-only callers (`C1`, `C3`, `C5`) use `marketplace_root_source` (`plugin/config.py:91`) instead of `resolve_marketplace_root` (`:162`), and resolve `~/.claude` via `claude_home()` (`plugin/shared.py:143`), with an explicit read-only control in C3. |
| **GAP-40** | `scan_active_registrations()` tool-name expansion and C5 runtime bundle loading outside checkout. | C1 (lines 133–137), C5 (lines 247, 291–301) | **Resolved in spec**: `scan_active_registrations()` maps active servers from `settings.json` / `.claude.json` / `.mcp.json` to wire prefixes (`mcp__plugin_<plugin>_<server>__` or `mcp__<server>__`) and expands known `(server, tool)` keys from `[families]` and `[verbs]` (loaded via `locate_bundle` / `loads_snapshot` on `src/cisternal/agent_plugin.json` or checkout `.praxia/manifest.toml` plus installed plugin `cisternal-source.json` sidecars) into `active_servers.json["tools"]`. |
| **GAP-41** | C4a Check (b)/Check (c) regex and fence-stripping audit against shipped `.praxia/manifest.toml` skills and `[plugin.families]`/`[plugin.verbs]` aliases. | C2 (lines 159, 170, 178), C4a (lines 222, 226, 229), C5 (line 251) | **Resolved in spec**: PascalCase regex fixed to `\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b`, ` ```...``` ` fenced code blocks stripped before extracting single-line inline `` `[^`\n]+` `` spans, `"agent-asset"` added to Check (b) hyphenated-modifier stopwords, concrete Check (c) report-mode findings on the 4 shipped skills documented, and `ManifestAssetSource` supports both top-level `[families]`/`[verbs]` and `[plugin.families]`/`[plugin.verbs]`. |

---

## Part 2: Challenger 8 Phase 3 Invariant & Stress Verification

1. **Every component C0–C6 has `Source of truth`, `Delivery`, and negative + positive `Controls`**:
   - Verified across C0 (lines 119–128), C1 (lines 131–155), C2 (lines 158–186), C3 (lines 189–208), C4a (lines 214–233), C4b (lines 235–242), C5 (lines 246–315), and C6 (lines 318–327).
2. **Evidence E1–E5 supports the components that cite it and exploratory numbers are never presented as findings**:
   - Verified in Problem (line 17) and Evidence (lines 19–25): E1–E5 are explicitly labelled `(unregistered)` preliminary motivating probes; C0 re-derives them under its pre-registered `benchmarks/usage/c0_usage.bth.toml` sidecar `[outcomes]`.
3. **Build order respects dependencies (`C4` needs `C3`; `C5` needs the E4 error-path fix; `Pre-1` off critical path per R1)**:
   - Verified in Order and Dependency Graph (lines 328–377): `Pre-0 -> C0 -> (C1, C2)`, `C2 -> C3 -> C4a`, `C3 -> C4b` (descriptive), `(C0, C1) -> C6`, `(Pre-0, C0, C1, C2) -> C5` (with client-side `PostToolUse` error ledger and lazy `active_servers.json` cache), and `Pre-1` parallel/independent.
4. **C2's invariant is consistent with E3 (a tool name need not appear in a skill)**:
   - Verified in C2 (line 159): skills declare `covers_families` rather than listing individual tool names; only tool names a skill chooses to quote in backticks (or `allowed_tools` / `disallowed_tools`) are checked against the hermetic known-tool set.
5. **All 16 mechanical fixes (`A1`–`A16`) and 5 resolved decisions (`R1`–`R5`) from `/tmp/claude-1000/spec_revision_brief.md` are preserved**:
   - Verified item-by-item against the spec text and Cycle 5 changelog; `status: draft` is set and all brief-prohibited status/probe terms are absent.

---

## Part 3: Defender 8 Response & Verdict

Claimed by: defender_c8

Defender 8 reviewed Challenger 8's verification table and Phase 3 invariant checks:
- All 19 gaps (`GAP-23`..`GAP-41`) and 2 risks (`RISK-01`, `RISK-02`) from Cycles 5–7 are resolved in `.praxia/docs/specs/261106_tool-surface-triage.md` and aligned with the cisternal source files in the worktree.
- **New genuine specification gaps found in Cycle 8**: **None**.
- The sequential Challenger -> Defender spec-coherence process has converged with no new genuine specification gap. The specification remains `status: draft` pending implementation and execution of the specified probes and test suite.
