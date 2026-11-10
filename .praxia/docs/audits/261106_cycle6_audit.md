---
title: "Tool-Surface Triage: Cycle 6 Adversarial Audit"
description: "Cycle 6: resolves open Cycle 5 gaps (GAP-23..27, 29, 30, 33, 34) and risks (RISK-01, RISK-02); sequential challenger/defender pass against cisternal source identifies and resolves 4 codebase-integration gaps (GAP-35..38)."
status: complete
task_id: 261106_tool-surface-triage
date: '261108'
author: "challenger_c6 / defender_c6"
verdict: OPEN_GAPS_RESOLVED_IN_CYCLE
---
# Cycle 6 Adversarial Audit: Tool-Surface Triage Spec
Claimed by: challenger_c6 (Challenger), defender_c6 (Defender)

- **Target spec**: `.praxia/docs/specs/261106_tool-surface-triage.md` (`status: draft`)
- **Prior audit**: `.praxia/docs/audits/261106_cycle5_audit.md` (`OPEN_GAPS`: `GAP-23`..`GAP-27`, `GAP-29`, `GAP-30`, `GAP-33`, `GAP-34`, plus `RISK-01`, `RISK-02`)
- **Date**: 2026-11-08

## Limits and epistemic scope of this audit
- **What was checked by reading source code in this worktree**:
  - `src/cisternal/cli.py:509–1217` (`publish_shared`, `update_all`, `snapshot`, `inspect_assets`, `skillmod_assets`, `validate_assets`, `_native_cli_surface_digest`);
  - `src/cisternal/assets/bundle.py:59–273` (`SkillAsset`, `AssetBundle`, `LoadReport`);
  - `src/cisternal/assets/skill_schema.py:21–159` (`FIELD_KINDS`, `dropped_keys`, `check_skill`, `listing_advisory`);
  - `src/cisternal/assets/manifest.py:29–386` (`ManifestAssetSource.load`, `_load_skills`, `_split_frontmatter`);
  - `src/cisternal/assets/composite.py:17–99` (`CompositeAssetSource`, `merge_registry`);
  - `src/cisternal/assets/snapshot.py:31–138` (`dumps_snapshot`, `_MCP_LATE_DEFAULTS`, `loads_snapshot`, `bundle_from_dict`);
  - `src/cisternal/assets/inspect_json.py:12–51` (`_serialize_bundle`, `report_to_dict`);
  - `src/cisternal/assets/validate_golden.py:21–199` (`resolve_golden_slug`, `golden_digest_path`, `surface_digest`);
  - `src/cisternal/assets/bridge.py:21–140` (`asset_bundle_to_praxia_json`, `rust_surface_digest`);
  - `src/cisternal/export/_markdown.py:77–116` (`format_skill_markdown`);
  - `src/cisternal/plugin/shared.py:28–141` (`SOURCE_SIDECAR`, `publish_bundle`);
  - `src/cisternal/adapters/base.py:133–388` (`AdapterBase`, `BathosAdapter`, `PassthroughAdapter`, `ContemplexAdapter`, `XpeririAdapter`, `MyxcelAdapter`);
  - `tests/test_skill_schema.py`, `tests/test_self_manifest.py`, `tests/test_plugin_app.py`, `tests/test_plugin_repo.py`.
- **What was NOT executed**: No new runtime code, hooks, transcript parsers, or evaluation harnesses were executed (`Touch nothing outside .praxia/docs/`). All runtime claims (A5, A6, A7, A9, atomic-append concurrency, latency budget, C3 precision/recall, C4b fire rates) remain unverified test/probe requirements until implementation.

---

## Part 1: Resolution of Cycle 5 Open Gaps (`GAP-23`..`GAP-27`, `GAP-29`, `GAP-30`, `GAP-33`, `GAP-34`) and Risks (`RISK-01`, `RISK-02`)

Before running the Cycle 6 Challenger pass, all 9 open gaps and 2 unverified risks from `.praxia/docs/audits/261106_cycle5_audit.md` were resolved in `.praxia/docs/specs/261106_tool-surface-triage.md`:

| ID | Cycle 5 Open Issue | Spec Resolution Applied |
|---|---|---|
| **GAP-23** | C5 depends on C1's registration scanner, and nobody owns `active_servers.json` rebuilds. | Extracted `scan_active_registrations()` in `src/cisternal/usage/registrations.py` (shared by C1 and C5) and added `C1` to C5's prerequisites and dependency graph (`(Pre-0, C0, C1, C2) -> C5`). C5's `PreToolUse` hook lazily creates/rebuilds `<sessions dir>/active_servers.json` via atomic temp-file + `os.replace` when missing or older than the mtime of `~/.claude/settings.json`, `~/.claude.json`, or installed plugin `.claude-plugin/plugin.json` / `.mcp.json` files (reading only local JSON files, no `claude` subprocess). Both warm-cache lookup and cold-cache rebuild are tested under the 150 ms p95 budget. |
| **GAP-24** | Dangling-name check fails `assets validate` (R3), but "a tool name a skill quotes" is undefined. | Defined quoted tool tokens in `SKILL.md` / `references/*.md` (and `allowed_tools` / `disallowed_tools`) as backticked tokens matching either (1) raw MCP form `^mcp__(?:plugin_[a-zA-Z0-9_-]+_)?([a-zA-Z0-9_-]+)__([a-zA-Z0-9_-]+)$` or (2) canonical `<server>/<tool>` form `^([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)$` where `<server>` is in the hermetic declared-server set. Bare single-word identifiers (`` `run_sql` ``) and file paths whose prefix is not a declared server (`` `references/foo.md` ``) are never checked. |
| **GAP-25** | CLI tokenizer (`parse_cli_command`) does not handle compound shell commands (`&&`, `\|`, `;`). | Defined `parse_cli_commands(cmd: str, verbs: VerbTable) -> list[tuple[str, str]]` (with `parse_cli_command` returning the first match or `None`). Splits on unquoted `&&`, `\|\|`, `;`, `\|`, `&`, and `\n` (tracking quotes and backslash escapes; skipping segments with unquoted `$(...)` or backticks before the verb, or unclosed quotes, fail-open). C0 counts all matched segments; C5 checks segments in order and nudges on the first non-excluded, active, non-suppressed match. |
| **GAP-26** | `PostToolUse` writer and `PreToolUse` reader can resolve different `<sessions dir>` via `pyproject.toml` if `cwd` changes. | Specified that for hook subprocesses, layer 3 (`[tool.cisternal]` in `pyproject.toml`) walks up from `$CLAUDE_PROJECT_DIR` when set and non-empty, and is skipped when `$CLAUDE_PROJECT_DIR` is unset (falling straight from `CISTERNAL_SESSIONS_DIR` to the XDG default). Added a control running writer and reader from different working directories (one with a decoy `pyproject.toml`). |
| **GAP-27** | C3 precision $\ge 0.80$ threshold is ambiguous between point estimate and Wilson lower bound. | Fixed the pre-registered gate criterion to **point estimate** $\hat{p} = \text{TP} / (\text{TP} + \text{FP}) \ge 0.80$ over $n \ge 50$ hand-labelled matched turns (at $n = 50$, $\text{TP} \ge 40$), with the two-sided Wilson 95% confidence interval reported alongside to keep sampling width visible; if $< 50$ matched turns are evaluated, status is `INCONCLUSIVE`. |
| **GAP-29** | C0 transcript glob `~/.claude/projects/<slug>/*.jsonl` is non-recursive and misses `<slug>/<session-id>/subagents/agent-*.jsonl`. | Updated C0 and Pre-0 to discover both `<slug>/*.jsonl` (main sessions) and `<slug>/<session-id>/subagents/*.jsonl` (subagent sessions), with a synthetic directory fixture testing both levels. |
| **GAP-30** | C1 does not define "repository" for `enable-per-project` or per-repo $N$; worktree slugs split one repo. | Added `resolve_repo_key(session_cwd: str \| None, slug: str) -> str` in Pre-0/C1: strips `/.claude/worktrees/<name>(/.*)?$` (and `/.worktrees/<name>(/.*)?$`) from `cwd`, resolves `git rev-parse --path-format=absolute --git-common-dir` parent when on disk, and falls back to stripping `--claude-worktrees-<suffix>` from `<slug>`. Added worktree-folding control in C1. |
| **GAP-33** | C2 dangling-name check against machine-local registrations is non-hermetic in CI/sandboxes. | Defined the hermetic reference tool inventory for `assets validate`: union of canonical keys in `[families]` and `[verbs]` of the validated manifest(s) (`--manifest`) plus `AssetBundle.commands` (as `<plugin.name>/<cmd.name>`). `assets validate` never reads `~/.claude.json` or `~/.claude/settings.json`. |
| **GAP-34** | `format_skill_markdown` drops `covers_families` and `distinctive_strings` on export; C3's skill source for installed plugins is unspecified. | Kept `format_skill_markdown` (`export/_markdown.py:77`) emitting only documented Claude Code keys (preserving stricter-consumer compatibility and golden digests). Updated `publish_bundle` (`plugin/shared.py:119`) to record `skills_meta` (`covers_families`, `distinctive_strings`) in `.claude-plugin/cisternal-source.json` and `snapshot.py` to round-trip both fields. C3 reads `--manifest` (workspace) and `--marketplace` plugins (via `cisternal-source.json` manifest path, then `skills_meta`, then `SKILL.md` frontmatter), listing any third-party skill without `distinctive_strings` under `unmonitored_skills`. |
| **RISK-01** | Protocol-level MCP errors or crashes may be routed to `PostToolUseFailure` instead of `PostToolUse`. | Documented under A6 and C5: cisternal adapters (except `PassthroughAdapter`) return errors in-band so they reach `PostToolUse`; for `PassthroughAdapter` / wire-level `isError: true`, the C5 fixture capture checks whether Claude Code fires `PostToolUse` or `PostToolUseFailure`, registering the ledger writer on both events if needed. |
| **RISK-02** | `contemplex` and `myxcel` error envelope rules are unchecked against those external repositories. | Relaxed C5's `myxcel` rule from exact key set `{"error", "message"}` to top-level object where `"error"` is a non-empty string, `"message"` is a string, and `"ok"` is not `True`; for `contemplex`, check `ok is False` or (`"error_code"` non-empty string and `"ok"` not `True`). Marked both UNVERIFIED until checked against captured real error fixtures (`tests/fixtures/hooks/post_tool_use/`). |

---

## Part 2: Cycle 6 Challenger Findings (Sequential Pass Against Revised Spec & Codebase)

Claimed by: challenger_c6

Acting as Challenger 6 after Part 1 was applied, I audited the updated spec against the actual `src/cisternal/` and `tests/` files in the worktree. Four genuine codebase-integration and spec-coherence gaps were found:

### GAP-35: `LoadReport.warnings` is fatal across cisternal CLIs, breaking R3 (C2 warn-only) and C4a report mode
- **Code evidence**:
  - In `src/cisternal/cli.py:1035–1037` (`validate_assets`), `if report.warnings: raise SystemExit(1)`.
  - In `src/cisternal/cli.py:650–652` (`_publish_shared_core`), `if report.warnings: raise SystemExit(1)`.
  - In `src/cisternal/cli.py:838–840` (`snapshot`), `if report.warnings: raise SystemExit(1)`.
  - In `src/cisternal/assets/skill_schema.py:148–150`, the docstring of `listing_advisory` explicitly notes: *"Deliberately not part of `check_skill`: its warnings are fatal in validate, publish, snapshot and plugin install."*
- **Spec flaw**:
  - C2 (under R3) states that family coverage is **warn-only** in `assets validate`, while dangling tool names **fail** `assets validate` now.
  - C4a states that before C4a is enabled as a failure, it runs in **report mode** against every shipped skill.
  - However, C2 says `ManifestAssetSource` loads `[families]` during manifest ingestion, and does not distinguish where warn-only vs. fatal diagnostics are stored on `LoadReport` (`bundle.py:268`). If an implementer appends C2 family-coverage warnings or C4a report-mode findings to `warnings` in `ManifestAssetSource.load()` or `check_skill()`, `validate`, `publish-shared`, `snapshot`, and `plugin install` will all exit 1—violating R3 and breaking C4a's report-mode rollout.

### GAP-36: `CompositeAssetSource.merge_registry`, `snapshot.py`, and golden digests drop or fail on the new fields and assets
- **Code evidence**:
  - `CompositeAssetSource.merge_registry` (`src/cisternal/assets/composite.py:65–73`) reconstructs `AssetBundle` by explicitly passing 7 positional/keyword fields (`metadata`, `commands`, `mcp_servers`, `skills`, `agents`, `hook_specs`, `marketplace`). Any new field on `AssetBundle` (or `LoadReport`) not copied in `merge_registry` is silently lost whenever `load_asset_report(manifest=...)` is called (`cli.py:1029`).
  - `dumps_snapshot` (`src/cisternal/assets/snapshot.py:36–51`) serializes `AssetBundle` via `dataclasses.asdict` (`inspect_json.py:14`) and strips `_MCP_LATE_DEFAULTS` so pre-existing snapshots stay valid under `assets snapshot --check` (`tests/test_plugin_app.py:166`, `tests/test_plugin_repo.py:120`). Meanwhile `bundle_from_dict` (`snapshot.py:88–112`) constructs `SkillAsset` with explicit keyword arguments (not `**s`). If `SkillAsset` gains `covers_families: tuple[str, ...] = ()` and `distinctive_strings: tuple[str, ...] = ()` without adding them to `bundle_from_dict` and stripping empty-tuple defaults in `dumps_snapshot` (`_SKILL_LATE_DEFAULTS`), then:
    1. `tests/test_skill_schema.py:81` (`test_snapshot_round_trip_keeps_every_field`) will fail because `bundle_from_dict` ignores the two new fields; and
    2. `tests/test_plugin_app.py:166` (`test_cisternal_packaged_snapshot_matches_its_manifest`) will immediately fail on `src/cisternal/agent_plugin.json` even before any skill adds `distinctive_strings`.
  - Furthermore, `resolve_golden_slug` (`src/cisternal/assets/validate_golden.py:55–56`) maps `.praxia/manifest.toml` to `self_manifest` and compares emitted files against `tests/golden/self_manifest/` (and `tests/golden/rust_parity/self_manifest/`). Adding C5 `hook_specs` or C6 `triage-tool` to `.praxia/manifest.toml` changes the emitted bundle, which fails `assets validate --manifest .praxia/manifest.toml` unless `src/cisternal/agent_plugin.json` and `tests/golden/{,rust_parity/}self_manifest/` are updated in the same change.

### GAP-37: C4a Check (b) item 4 contradicts Check (a), and Check (a) `--baseline-ref` is undefined for newly added skills
- **Spec flaw 1 (Check (a) vs Check (b) contradiction)**:
  - C4a Check (a) (line 181) states that every string in `distinctive_strings` must appear in the listing text (`description` / `when_to_use`) **or in the `SKILL.md` body** (prose, code, or heading).
  - C4a Check (b) (lines 184–190) lists "4. tokens declared in `distinctive_strings` or `covers_families`" under the token grammar, and then states: *"a backticked token passes if it appears anywhere in the `SKILL.md` body or a `references/` file ... Other tokens pass if they appear, case-insensitively, in a section heading (`#`, `##`, `###`) or code-block identifier in `SKILL.md` or `references/`."*
  - Because `distinctive_strings` and `covers_families` are frontmatter YAML list items (not backticked in the listing text), Check (b) would require every `distinctive_strings` entry and every `covers_families` identifier (e.g. `bathos_query`) to appear in a Markdown section heading (`#`, `##`, `###`) or code-block fence info string! That directly contradicts Check (a) (which allows `distinctive_strings` in body prose) and forces internal family keys like `bathos_query` into prose headings.
  - Additionally, "code-block identifier" is ambiguous between the fenced code block's language tag (`python`, `bash`) and identifiers inside fenced code blocks / inline code spans.
- **Spec flaw 2 (`--baseline-ref` on new skills vs invalid refs)**:
  - Check (a) mandates `--baseline-ref origin/main` in pull-request CI, but does not specify what happens when a PR adds a *new* skill file (such as C6's `.praxia/skills/triage-tool/SKILL.md`, which does not exist at `origin/main`) versus when the git ref `origin/main` itself is missing/unresolvable (e.g. shallow clone).

### GAP-38: C6 (`triage-tool` skill) and C4b lack explicit Source of Truth / Delivery / Controls structure
- **Spec flaw**:
  - The Phase 3 review rule requires: *"every component C0-C6 has source of truth, delivery mechanism and negative control."*
  - In `.praxia/docs/specs/261106_tool-surface-triage.md`, C0, C1, C2, C3, C4a, and C5 have explicit `Controls` sections with negative and positive controls, but C6 (`triage-tool` skill) only has `Path`, `Trigger`, `Architecture`, `Dependencies`, and `Safety` bullets (no explicit `Source of truth`, `Delivery`, or `Controls` bullet with a testable negative control), and C4b has a single positive sensitivity control without an explicit `Source of truth`, `Delivery`, or negative/null control.

---

## Part 3: Cycle 6 Defender Dispositions

Claimed by: defender_c6

| ID | Disposition | Defender Resolution Applied to Spec |
|---|---|---|
| **GAP-35** | **Conceded & Fixed** | Added explicit diagnostic-channel routing in C2, C3, and C4a: `LoadReport` gains `advisories: tuple[str, ...] = ()` (forwarded by `CompositeAssetSource.merge_registry` and logged as warnings in `validate_assets` at `cli.py:1043` without changing the exit code, while `publish-shared`, `snapshot`, and `plugin install` ignore `advisories`). Warn-only checks (C2 family coverage under R3, C3 pre-migration missing `distinctive_strings`, C4a report mode) emit to `LoadReport.advisories`; fatal checks (C2 dangling tool names, C3 invalid `distinctive_strings` length/empty strings and post-migration missing `distinctive_strings`, C4a once enabled) emit to `LoadReport.warnings`. |
| **GAP-36** | **Conceded & Fixed** | Specified in C2, C3, C5, and C6: (1) `AssetBundle` carries `families: tuple[tuple[str, tuple[str, ...]], ...] = ()` and `verbs: tuple[VerbSpec, ...] = ()` (sorted tuples for frozen hashability), forwarded in `CompositeAssetSource.merge_registry` (`composite.py:65`) and ignored by `asset_bundle_to_praxia_json` (`bridge.py:21`); (2) `dumps_snapshot` (`snapshot.py:36`) strips default empty values (`_SKILL_LATE_DEFAULTS = {"covers_families": [], "distinctive_strings": []}` and bundle-level `"families": []`, `"verbs": []`) so existing snapshots stay byte-identical under `assets snapshot --check`, while `bundle_from_dict` (`snapshot.py:88`) restores `covers_families` and `distinctive_strings` on `SkillAsset` and `families`/`verbs` on `AssetBundle`; (3) any change to `.praxia/manifest.toml` that alters emitted files or skills (C3 migration, C5 `hook_specs`, C6 `triage-tool`) updates `src/cisternal/agent_plugin.json` (`assets snapshot`) and `tests/golden/{,rust_parity/}self_manifest/` (`validate_golden.py`). |
| **GAP-37** | **Conceded & Fixed** | In C4a Check (a): if a skill path does not exist at `--baseline-ref <ref>` (newly added skill), baseline comparison is skipped for that skill and only current-file Check (a) runs; if `<ref>` itself is not a valid commit (`git rev-parse --verify <ref>^{commit}` fails), `assets validate` exits 2. In C4a Check (b): removed `distinctive_strings` and `covers_families` from Check (b)'s heading rule (Check (a) already governs `distinctive_strings` containment, and `covers_families` are internal manifest keys not required in prose). Check (b) extracts candidate tokens from the listing text (`description` + `effective_when_to_use`): (1) backticked literals pass if they appear anywhere in `SKILL.md` body or `references/`; (2) non-backticked PascalCase/camelCase or hyphenated/underscored identifiers (excluding case-insensitive stopwords and tokens already matched by `distinctive_strings`) pass if they appear case-insensitively in a section heading (`#`–`####`), fenced code block, or inline code span in `SKILL.md` or `references/`. |
| **GAP-38** | **Conceded & Fixed** | Added explicit **Source of truth**, **Delivery**, and **Controls** (both negative and positive controls) to C4a, C4b, and C6. For C4b: negative/null control runs two identical descriptions and asserts 0 discordant pairs; positive sensitivity control runs a degraded description. For C6: negative control asserts `SKILL.md` and `references/` contain no shell commands or code blocks that write to `~/.claude/settings.json` or `~/.claude.json`, and that `assets validate` fails if C6's trigger exceeds 150 chars; positive control asserts `triage-tool` loads cleanly via `ManifestAssetSource( Path(".praxia/manifest.toml") )` and passes C2, C3, and C4a checks. |

## Verdict
**OPEN_GAPS_RESOLVED_IN_CYCLE**. All 9 open gaps and 2 risks from Cycle 5 were resolved, and the sequential Cycle 6 Challenger/Defender pass identified and resolved 4 additional codebase-integration gaps (`GAP-35`..`GAP-38`). Because Cycle 6 conceded new genuine gaps (`GAP-35`..`GAP-38`), a sequential Cycle 7 Challenger/Defender pass is required to verify termination.
