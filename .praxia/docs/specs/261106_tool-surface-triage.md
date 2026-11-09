---
title: 'Tool-surface triage: usage counter, prune list, guidance coverage, progressive-disclosure check, nudge hook, triage-tool skill'
description: Specification for cisternal tooling that measures MCP/skill use and coverage, prunes dead surface, checks short-description accuracy, and nudges CLI-to-MCP at the moment of the wrong action.
status: draft
task_id: 261106_tool-surface-triage
date: '261106'
author: 'cycle5_reviser (applies spec_revision_brief A1-A16, R1-R5); challenger_c6 / defender_c6; challenger_c7 / defender_c7; challenger_c8 / defender_c8; prior cycles challenger_c1..c4 / defender_c1..c4'
backlog_ids: ''
adversarial_review: '.praxia/docs/audits/261106_cycle8_audit.md'
---
# Tool-surface triage: usage counter, prune list, guidance coverage, progressive-disclosure check, nudge hook, triage-tool skill

Claimed by: cycle5_reviser (Cycle 5 reconciliation revision), cycle5_rereviewer (Cycle 5 re-review corrections), challenger_c6 / defender_c6 (Cycle 6 gap resolution), challenger_c7 / defender_c7 (Cycle 7 gap resolution), challenger_c8 / defender_c8 (Cycle 8 verification), previously defender_c4, worker_docs_indexer
task_id: 261106_tool-surface-triage · status: draft (post-cycle-8; runtime claims remain unverified until implementation tests and probes execute) · home: cisternal · origin: bathos background job, 2026-11-06

## Problem
Agents under-use MCP tools and skills they already have. They often fall back to CLI calls or work without the relevant skill loaded. Goal: cisternal ships tooling that measures tool and skill usage and coverage, prunes unused surface safely, checks guidance quality, and nudges agents from CLI to MCP when they make the CLI call. Every number in the preliminary probes is exploratory and unregistered (see Evidence). C0 re-derives the metrics under conditions registered in a committed sidecar before its first run.

## Evidence (Preliminary Motivating Probes — UNREGISTERED)
*All five items below are unregistered, exploratory findings from untracked scripts over 145 main-session transcripts (subagents excluded). They motivate design choices and are not benchmarks. C0 re-derives the corresponding metrics under its registered `[outcomes]`.*
- **E1 (unregistered) MCP vs CLI for bathos**: 943 MCP calls vs 7,948 `bth` Bash calls, so MCP is 943 / 8,891 = 10.6% of bathos calls, across 145 sessions. 45 sessions used MCP, 94 used CLI; 0 MCP-only sessions. Motivates C0 and C5.
- **E2 (unregistered) ToolSearch behaviour**: 2,524 of 2,537 ToolSearch calls were `select:<exact name>`; 13 were free-text keyword queries. Agents rarely search by keyword, which motivates situation-matched skill triggers and verb nudges over generic "search more" guidance.
- **E3 (unregistered) Provenance of tool loads**: of 225 bathos `select:` loads, 113 had the tool name in the deferred listing only; 112 had a prior hook, user, tool-result or assistant mention. Motivates the C2 rule that a tool name need not appear in a skill for the tool to be found from bare stubs.
- **E4 (unregistered) Error precedes fallback**: a same-verb `bth` CLI call followed within 3 calls in 13/57 = 22.8% (Wilson 95% interval 13.8%–35.2%) of instances after an MCP error, vs 15/664 = 2.3% (Wilson 95% interval 1.4%–3.7%) after success. The intervals do not overlap, but the 57 error instances come from an unregistered script and are not independent (several per session). Motivates C5's rule: suppress the nudge after an MCP error for that tool.
- **E5 (unregistered) Current registration vs history**: current registrations (`~/.claude/settings.json`, `~/.claude.json`) list 27 enabled plugins. Transcripts contain ~35 historical servers with zero use and duplicate names no longer active. Motivates C1: prune lists intersect transcript usage with active registrations, not transcript text alone.

## Assumptions
| id | assumption | tag |
|---|---|---|
| A1 | cisternal-exported plugins can ship PreToolUse hooks | verified: `assets/manifest.py:232` (`_load_hook_specs`), `export/claude.py:30` (`hooks/hooks.json`) |
| A2 | cisternal telemetry is server-side: `mcp.call_start/call_end/tool_error`; it sees no CLI substitution and no unmet need. Records carry a `session_id` field, but `session_id_var` (`telemetry/context.py:27`) is never set anywhere in `src/`, so that field is always `None` today | verified: `telemetry/record.py`, `otlp_exporter.py:37`, `grep session_id_var.set src/` → no hits; log dir `CISTERNAL_LOG_DIR` > `BTH_LOG_DIR` > `CTXP_LOG_DIR` > `~/.cisternal/logs` (`telemetry/pipeline.py:222`) |
| A3 | `assets validate` already reports a listing-length advisory at 250 chars | verified: `skill_schema.py:26` (`LISTING_TARGET_CHARS`), `skill_schema.py:153` (`listing_advisory` threshold) |
| A4 | praxia `session_context_audit.py` already tallies `other_mcp_by_server`, `skills_by_plugin` | verified by name (`:447`); C0 re-implements natively in `src/cisternal/usage/transcript.py` (Pre-0) with attribution |
| A5 | Claude Code skill-listing budget is a shared pool (~1% of context) with per-entry cap 1,536 chars | UNVERIFIED: cisternal's `LISTING_CAP_CHARS = 1536` (`skill_schema.py:23`) restates a secondhand reading of the Claude Code binary, not an independent check; the cap is configurable in Claude Code via `skillListingMaxDescChars` |
| A6 | Transcript record types separate listing, hook, skill, user and tool-result text; the PostToolUse stdin payload carries `session_id`, `tool_name` and the tool response | UNVERIFIED by any reviewer: exploratory probe only (`deferred_tools_*`, `hook_*`, `skill_listing`, `invoked_skills`). Pre-0's golden fixture (redacted real transcript) and C5's captured hook payload fixtures verify it, including whether wire-level MCP failures (`PassthroughAdapter` re-raise or server crash) fire `PostToolUse` or `PostToolUseFailure` (RISK-01) |
| A7 | A hook's additional context changes behaviour | UNVERIFIED: needs a matched-session A/B evaluation; out of scope here |
| A8 | Error shapes are consistent across servers | **REFUTED**: adapters in `src/cisternal/adapters/base.py:278–388` return different shapes: `BathosAdapter` dict with `error_code` (:280–285); `PassthroughAdapter` re-raises (:318); `ContemplexAdapter` returns `err_envelope` (:343–346); `XpeririAdapter` returns a JSON string (:364–368); `MyxcelAdapter` returns `{"error": type(exc).__name__, "message": str(exc)}` with no `ok` or `error_code` (:386–388). Furthermore, `contemplex.errors.err_envelope` and `myxcel` in-band tool error dicts (`MyxcelAdapter.shape_ok` at :381) live in external repos and are UNVERIFIED from this worktree (RISK-02). C5 classifies errors client-side per server and validates rules against captured real error fixtures (see C5); Pre-1 normalizes server-side for later enrichment |
| A9 | Subagents do not change the picture | UNVERIFIED: subagents run with ~26k fewer standing context tokens and without interactive steering. C0 stratifies by session type and reports both strata; A9 is verified or refuted by C0's registered output |

## Shared Definitions

### Canonical tool key
All components key tools on one canonical key, `(server, tool)`, written `server/tool` in manifests and reports. Raw names are normalized before any lookup:

| raw form | example | canonical key |
|---|---|---|
| `mcp__plugin_<plugin>_<server>__<tool>` | `mcp__plugin_bathos_bathos__run_sql` | `bathos/run_sql` |
| `mcp__<server>__<tool>` | `mcp__bathos__run_sql` | `bathos/run_sql` |
| bare `<tool>` (manifest written inside one server's context) | `run_sql` in `[families]` of the bathos plugin manifest | `bathos/run_sql` |

- Split on the double underscore `__`. In the plugin form, the middle segment `plugin_<plugin>_<server>` is ambiguous when names contain `_`; resolve `<server>` by longest-suffix match against the server names declared in that plugin's manifest (active registration scan in C1/C5, or hermetic manifest server set in C2). If no declared server matches, keep the whole segment as the server and report the name as `unresolved`.
- A bare name with no server context (e.g. in a workspace `.praxia/manifest.toml`) is an error in `[families]`/`[verbs]`; workspace manifests write `server/tool`.
- `[families]`, `[verbs]`, C0 counts, C1 buckets and the C2 dangling-name check all use the canonical key.
- Test: `tests/test_canonical_tool_key.py` with live-style names in all three forms (taken from a captured transcript and a captured `~/.claude.json`), including a plugin and server whose names contain `_`, and an unresolved case.

### Derived-data directories (sessions, transcripts index, logs)
Every directory cisternal writes derived data to resolves through one resolver, generalized from `resolve_log_dir_from_env` (`telemetry/pipeline.py:222`):
1. explicit argument (`--data-dir` / function arg) >
2. environment variable (`CISTERNAL_SESSIONS_DIR`, `CISTERNAL_LOG_DIR` > `BTH_LOG_DIR` > `CTXP_LOG_DIR` as today for logs) >
3. `[tool.cisternal]` in the project `pyproject.toml` >
4. XDG default (`$XDG_STATE_HOME/cisternal/<kind>`, falling back to `~/.local/state/cisternal/<kind>`) >
5. off.
- **Project-root anchoring for layer 3 (`pyproject.toml`)**: CLI commands (`cisternal usage`, `cisternal prune-list`) walk up from `--project-root` or `Path.cwd()`. Hook subprocesses (`PreToolUse`, `PostToolUse`) walk up from `$CLAUDE_PROJECT_DIR` when set and non-empty in the hook environment, and **skip layer 3 (`pyproject.toml`) when `$CLAUDE_PROJECT_DIR` is unset**, falling directly from layer 2 (`CISTERNAL_SESSIONS_DIR`) to layer 4 (XDG default). This guarantees `PostToolUse` (writer) and `PreToolUse` (reader) always resolve the same `<sessions dir>` even when an agent changes working directories between calls.
- Layer reporting: `cisternal usage --show-paths` and the doctor output print the resolved path and which layer chose it.
- Off switch: the value `off` at any layer (e.g. `CISTERNAL_SESSIONS_DIR=off`) disables writes for that kind; readers treat it as "no data".
- Atomic append: each record is one `write()` of one line to a file opened `O_APPEND`, with the record capped at 4,096 bytes (message truncated). A concurrency test (N processes appending to one file, then parse every line) gates this; the claim is not taken from argument.
- Size cap: a per-file cap (default 1 MiB for `errors.jsonl`); over the cap the writer stops appending and fails open.
- Back-compat: the existing log default `~/.cisternal/logs` remains the layer-4 default for `logs` only, so current deployments do not move.

### Diagnostic channels (`LoadReport.warnings` vs `LoadReport.advisories`) and bundle/snapshot invariants
- **Fatal warnings vs non-fatal advisories**: In cisternal, `LoadReport.warnings` (`assets/bundle.py:272`) is fatal in `cisternal assets validate` (`cli.py:1035`), `publish-shared` (`cli.py:650`), `snapshot` (`cli.py:838`), and `plugin install` (`skill_schema.py:148`). To support warn-only and report-mode checks without breaking builds or installs, `LoadReport` adds `advisories: tuple[str, ...] = ()` (forwarded by `CompositeAssetSource.merge_registry` at `assets/composite.py:74`). `validate_assets` (`cli.py:1043`) logs `report.advisories` alongside `listing_advisory` without changing the exit code; `publish-shared`, `snapshot`, and `plugin install` ignore `advisories`.
- **Bundle and snapshot preservation**:
  - `AssetBundle` (`assets/bundle.py:223`) adds `families: tuple[tuple[str, tuple[str, ...]], ...] = ()` and `verbs: tuple[VerbSpec, ...] = ()` (sorted tuples for frozen hashability), forwarded by `CompositeAssetSource.merge_registry` (`assets/composite.py:65`) and ignored by `asset_bundle_to_praxia_json` (`assets/bridge.py:21`) so `--rust-parity` digests are unaffected.
  - `dumps_snapshot` (`assets/snapshot.py:36`) omits default empty values on skills (`_SKILL_LATE_DEFAULTS = {"covers_families": [], "distinctive_strings": []}`) and on the bundle (`"families": []`, `"verbs": []`), matching `_MCP_LATE_DEFAULTS` (`snapshot.py:51`) so existing committed snapshots remain byte-identical under `assets snapshot --check` (`tests/test_plugin_app.py:166`, `tests/test_plugin_repo.py:120`) until a skill or manifest sets those fields. `bundle_from_dict` (`snapshot.py:88`) restores `covers_families` and `distinctive_strings` on `SkillAsset` and `families` / `verbs` on `AssetBundle`.
  - Any change to `.praxia/manifest.toml` or its referenced skill/hook files (C3 migration, C4a skill fixes, C5 `hook_specs`, C6 `triage-tool` skill) must update `src/cisternal/agent_plugin.json` via `cisternal assets snapshot` and, when emitted surface files change, update `tests/golden/self_manifest/` and `tests/golden/rust_parity/self_manifest/` (`assets/validate_golden.py:55–75, 172–199`).

## Build Prerequisites

### Pre-0: Native Transcript Parsing Core (`src/cisternal/usage/transcript.py`)
- **Action**: Implement a native, self-contained transcript parsing core in `src/cisternal/usage/transcript.py`. Praxia is an external sibling repository outside cisternal's package boundary and is not mounted in sandboxed and CI environments, so cisternal imports nothing from it.
- **Attribution**: the module docstring attributes the parser design to Praxia `session_context_audit.py` (2026).
- **Interfaces**:
  - `canonical_tool_key(raw: str, declared_servers: Collection[str] = ()) -> ToolKey` (see Shared Definitions).
  - `parse_cli_commands(cmd: str, verbs: VerbTable) -> list[tuple[str, str]]` and `parse_cli_command(cmd: str, verbs: VerbTable) -> tuple[str, str] | None` (returning the first match from `parse_cli_commands`, or `None`).
    1. **Compound command splitting**: splits `cmd` into segments on unquoted shell operators `&&`, `||`, `;`, `|`, `&`, and `\n` (tracking single quotes `'...'`, double quotes `"..."`, and backslash escapes `\.`). Subshells and command substitutions (`$(...)`, `` `...` ``) are not recursively expanded: any segment containing unquoted `$(` or backticks before the verb, or unclosed quotes, is skipped fail-open. Redirects (`2>&1`, `>/dev/null`) after the subcommand are ignored.
    2. **Per-segment tokenization**: strips prefix wrappers (`rtk`, `just`, `env` with `VAR=value` assignments, bare leading `VAR=value`, `timeout <duration>`, `nohup`), skips global flags before the subcommand using the per-binary `global_flags_with_value` list from `[verbs]` (a flag in that list consumes the next token), and skips the segment when an unknown flag precedes the subcommand.
  - `discover_transcript_files(projects_root: Path) -> Iterator[tuple[str, Path]]`, yielding `(slug, jsonl_path)` for both top-level main-session transcripts (`<projects_root>/<slug>/*.jsonl`) and nested subagent transcripts (`<projects_root>/<slug>/<session_id>/subagents/*.jsonl`).
  - `stream_transcript_events(path: Path) -> Iterator[TranscriptEvent]`, a streaming JSONL reader covering `deferred_tools_*`, `tool_use`, `tool_result`, `skill_listing`, `invoked_skills` and `Skill` tool_use records.
  - `stratify_session_type(events: Iterable[TranscriptEvent], path: Path) -> Literal["main_interactive", "subagent_headless"]`. Takes an iterable, not a list. The deciding signal (the record field `isSidechain`, or the transcript's file location such as `<session_id>/subagents/agent-*.jsonl`) is chosen by a probe over real transcripts done as the first Pre-0 task; the chosen signal is written into this spec and the C0 sidecar before C0's first run.
  - `resolve_repo_key(session_cwd: str | None, slug: str) -> str`: normalizes worktree sessions to their parent repository so C1's per-repo counts and floors do not split one repository across its worktrees. Strips `/.claude/worktrees/<name>(/.*)?$` and `/.worktrees/<name>(/.*)?$` from `session_cwd`; if the path exists on disk, runs `git -C <path> rev-parse --path-format=absolute --git-common-dir` (cached per unique path) and takes its parent directory; falls back to stripping `--claude-worktrees-<suffix>` from `slug` when `session_cwd` is absent or no longer on disk.
- **Controls**:
  - Golden fixture `tests/fixtures/usage/golden_transcript.jsonl`: a redacted real transcript (user text and tool payloads replaced, record structure kept), with expected counts committed alongside.
  - Tokenizer cases: `bth sql`, `rtk bth sql`, `env X=1 bth sql`, `X=1 bth sql`, `bth --flag sql` (flag declared value-less), `bth --db x sql` (flag declared value-taking), `bth --unknown sql` (→ `[]` / `None`), `cd /tmp && bth sql "SELECT 1"` (→ `[("bth", "sql")]`), `bth sql "SELECT 1" | head -n 5` (→ `[("bth", "sql")]`), `echo hi; rtk bth show 42` (→ `[("bth", "show")]`), `bth run foo && bth sql "SELECT 1"` (→ `[("bth", "run"), ("bth", "sql")]`), `"bth && sql"` inside quotes (not split), `$(bth sql)` (skipped → `[]`), and unclosed quote `bth sql "unterminated` (fail-open → `[]`).

### Pre-1: Adapter Error Normalization (`src/cisternal/adapters/base.py`) — independent, off the C0/C1 critical path
- **Placement (R1)**: Pre-1 is independent of Pre-0 and of C0–C6. No downstream component consumes its output: C0 reads client transcripts, and C5's hook classifies errors itself. Pre-1 feeds only a later server-side enrichment (joining server logs to C0 output) and may be built in parallel or later.
- **Contract**:
  ```python
  @dataclass(frozen=True, slots=True)
  class NormalizedError:
      is_error: bool
      error_code: str
      error_message: str
      resolution_hint: str | None = None
  ```
  - `AdapterBase.normalize_error(self, raw_result: Any) -> NormalizedError`: a concrete, non-abstract default on `AdapterBase` that checks the common shapes (`ok is False`, top-level `error_code`), so existing and third-party adapters need no change. Adapters override it only where their shape differs.
  - `AdapterBase.normalize_exception(self, exc: BaseException) -> NormalizedError`: separate method for raised exceptions; default `NormalizedError(True, type(exc).__name__, str(exc))`.
  - Adapters write no files. Normalization is a pure function of its input; any persistence belongs to the telemetry pipeline.
- **Overrides**:
  - `BathosAdapter`: reads `ok`, `error_code`, `error`.
  - `ContemplexAdapter`: unpacks `err_envelope` fields.
  - `XpeririAdapter`: decodes the JSON string, then applies the default checks.
  - `MyxcelAdapter`: maps `{"error": ..., "message": ...}` (where `"error"` is non-empty and `"ok"` is not `True`) to `is_error=True`, `error_code="MYXCEL_ERROR"`.
  - `PassthroughAdapter`: re-raises the original exception (current behaviour at :318, unchanged); the caller that catches it uses `normalize_exception`. `PassthroughAdapter` does not catch exceptions itself.

## Components (Source of Truth / Delivery / Controls)

### C0: Tracked Usage Counter (First Deliverable)
- **Source of truth**:
  - **Primary (client transcripts)**: Claude Code JSONL transcripts discovered via `discover_transcript_files` under `claude_home() / "projects"` (`$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects/`, matching `src/cisternal/plugin/shared.py:143`; covering both `<slug>/*.jsonl` main sessions and `<slug>/<session_id>/subagents/*.jsonl` subagent sessions), or a directory given by argument. MCP call tallies (canonical key), CLI invocations via `parse_cli_commands`, `ToolSearch` provenance (`select:<name>`), per-skill invocation counts (`Skill` tool_use records plus `invoked_skills` records, needed by C1, R4), error-to-fallback sequences, canonical repository keys (`resolve_repo_key`), and session stratification all come from transcripts alone.
  - **Secondary (optional server logs)**: cisternal server JSONL logs (resolved log dir) may add `duration_ms`. The join is heuristic (`canonical key, timestamp ± 5 s`) and non-blocking; unmatched rows get `duration_ms: null`. Normalized server errors (Pre-1) are a later enrichment and are not required.
- **Session-type stratification**: every session gets `session_type` from `stratify_session_type`; every metric is reported per stratum. A9 is decided by comparing strata in the registered output.
- **Pre-registration**: a committed sidecar `benchmarks/usage/c0_usage.bth.toml` with `[outcomes]` exists before C0's first run on real data. It names the derivation script paths (`scripts/usage/c0_derive.py`, `scripts/usage/c3_coverage.py`), the conditions (transcript root, date window, session-type signal from Pre-0, cisternal commit), and the registered outcomes: E1–E5 re-derivations, per-skill invocation counts, C3 precision point-estimate threshold 0.80 (over $n \ge 50$ matched turns) with Wilson 95% interval, C3 recall (descriptive, with interval), and C4b paired fire rates (descriptive, with intervals).
- **Delivery**: `cisternal usage`; JSON plus summary tables.
- **Controls**:
  - Synthetic fixture `tests/fixtures/usage/synthetic_transcript.jsonl` with planted calls: `bathos/run_sql` written in both transcript forms (`mcp__plugin_bathos_bathos__run_sql` ×3, `mcp__bathos__run_sql` ×2) totals exactly 5; a bare `run_sql` tool_use is not an MCP call and is not counted under `bathos/run_sql` (bare names resolve only inside a manifest, see Shared Definitions; that form is tested in `tests/test_canonical_tool_key.py`); planted never-called `bathos/planted_uncalled` counts exactly 0; `len(counts) >= 2` (guards against an empty parse passing).
  - Subagent discovery fixture: a directory layout with `<slug>/<session_id>.jsonl` and `<slug>/<session_id>/subagents/agent-1.jsonl` populates both `main_interactive` and `subagent_headless` strata without double-counting.
  - Golden fixture (Pre-0) counts match the committed expected values.

### C1: Prune List
- **Source of truth**: active registrations (`claude_home() / "settings.json"`, `~/.claude.json`, installed plugin manifests in the read-only `marketplace_root_source()` directory at `plugin/config.py:91` and `claude_home() / "plugins"`, scanned via `scan_active_registrations()` in `src/cisternal/usage/registrations.py`) INTERSECT C0 counts, by canonical key.
- **Asset handling (R4) and registration cache schema**:
  - `scan_active_registrations()` is read-only with respect to user configuration (uses `marketplace_root_source()` at `plugin/config.py:91`, never `resolve_marketplace_root()` which writes `~/.config/cisternal/config.toml`). It:
    1. reads active MCP server registrations from `claude_home() / "settings.json"`, `~/.claude.json` (`mcpServers`), and enabled plugins' `.claude-plugin/plugin.json` + `.mcp.json` (`src/cisternal/export/claude.py:145–151`), recording each active server's wire prefix (`mcp__plugin_<plugin>_<server>__` for plugin-registered servers, `mcp__<server>__` for standalone servers) and each plugin's non-MCP assets (`hook_specs`, `commands`, `skills`);
    2. loads `[families]` and `[verbs]` from cisternal's own bundle (`locate_bundle` / `loads_snapshot` on `src/cisternal/agent_plugin.json` or checkout `.praxia/manifest.toml`, `plugin/app.py:170`) merged with any installed plugin `.claude-plugin/cisternal-source.json` sidecar metadata (`families`, `verbs`, `skills_meta`);
    3. expands every known `(server, tool)` canonical key from `[families]` and `[verbs]` whose `server` is active into `tools: {"<server>/<tool>": "<raw_prefix><tool>"}` (e.g. `"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"`), and writes `<sessions dir>/active_servers.json` (containing `servers`, `tools`, `verbs`, `families`, and plugin asset lists) atomically (`os.replace`) when invoked by C1 or C5.
  - Plugins with active hooks or commands are whitelisted from `drop`, whatever their MCP call volume.
  - Skill-bearing plugins are **not** whitelisted. A plugin's skills count as unused when every one of its skills has 0 invocations (C0 per-skill counts) over the floor below. A plugin with 0 MCP calls, no hooks, no commands and only unused skills is eligible for `drop`.
- **Repository normalization**: each session's repository is keyed by `resolve_repo_key(session_cwd, slug)` (Pre-0), folding git worktrees (e.g. `<repo>/.claude/worktrees/<branch>`) into their parent repository before computing per-repo session counts $N_{\text{repo}}$, calendar span, and the 80% concentration share.
- **Floor (both conditions)**: $N \ge 20$ sessions AND a lookback of $\ge 14$ calendar days. Below the floor, C1 prints counts and suppresses all `drop` and `enable-per-project` recommendations with the reason (`"N=<n> sessions over <d> days; floor is N>=20 AND >=14 days"`). For `enable-per-project`, the floor applies to the normalized per-repo $N_{\text{repo}}$.
- **What a drop means (rule of three)**: 0 uses in N sessions bounds the per-session use rate at about $3/N$ with 95% confidence (≈15% at N = 20). `drop` therefore means "rarely used in this window", not "never needed"; the report prints the bound next to each `drop`.
- **Delivery**: `cisternal prune-list`; three buckets:
  - `keep`;
  - `drop`: 0 MCP calls, no hooks or commands, skills (if any) all with 0 invocations, over the floor;
  - `enable-per-project`: a server where $\ge 80\%$ of the sessions that call it belong to one normalized repository (`resolve_repo_key`), and that repository meets the floor on its own sessions ($N_{\text{repo}} \ge 20$ AND $\ge 14$ days).
  The user applies changes; cisternal never writes settings files.
- **Controls**:
  - A server present in historical transcripts but absent from active registration does not appear in any bucket.
  - A plugin with active hooks or commands is never `drop`.
  - A plugin with calls in transcripts is never `drop`.
  - Positive: an active plugin with 0 calls and no assets over the floor appears in `drop`; a skill-only plugin whose skills have 0 invocations over the floor appears in `drop`; the same plugin with one skill invocation does not.
  - Floor: 25 sessions over 10 days → suppressed; 15 sessions over 30 days → suppressed.
  - Worktree folding: 12 sessions in `-home-user-repo` and 10 sessions in `-home-user-repo--claude-worktrees-feat` over 15 days fold into one repository with $N_{\text{repo}} = 22 \ge 20$, clearing the floor.
  - Names: the same server called under `mcp__plugin_<p>_<s>__x` and `mcp__<s>__x` is counted once.

### C2: Guidance-Coverage Lint
- **Source of truth**: declarative `[families]` and `[verbs]` tables in `.praxia/manifest.toml` (or plugin `manifest.toml` / `plugin.json`), `SkillAsset.covers_families` frontmatter, `SkillAsset.body` / `references/`, and `AssetBundle.commands`.
- **Invariant**: every declared tool family has a skill that declares it in `covers_families`, and every tool name a skill quotes exists in the hermetic known-tool set (dangling-name check). E3 holds: individual tool names need not appear in skills.
- **Quoted tool token & hermetic reference definitions**:
  - **Which tokens count as quoted tool names**: only inline backticked tokens `` `[^`\n]+` `` in `SKILL.md` or `references/*.md` extracted after stripping fenced code blocks ` ```...``` ` (plus `allowed_tools` / `disallowed_tools` frontmatter entries) matching either:
    1. raw MCP wire form `^mcp__(?:plugin_[a-zA-Z0-9_-]+_)?([a-zA-Z0-9_-]+)__([a-zA-Z0-9_-]+)$` (normalized via `canonical_tool_key`), or
    2. canonical `server/tool` form `^([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)$` where `<server>` is in the hermetic declared-server set below.
    Bare single-word identifiers (e.g. `` `run_sql` ``) and relative file paths or crate features whose first segment is not a declared server (e.g. `` `references/guide.md` ``, `` `src/cisternal` ``, `` `pyo3/extension-module` ``) are never treated as quoted tool names.
  - **Hermetic known-tool and declared-server sets**: `cisternal assets validate` never reads machine-local `~/.claude.json` or `~/.claude/settings.json`. The known-tool set is the union of canonical keys declared in `[families]` and `[verbs]` of the manifest(s) loaded via `--manifest` plus `AssetBundle.commands` (as `<plugin.name>/<command.name>`). The declared-server set is the set of server prefixes in that known-tool set plus `AssetBundle.mcp_servers` names.
- **Enforcement and diagnostic routing (R3)**:
  - Family coverage is **warn-only** until C3 shows that `covers_families` coverage relates to tool use (registered C3 analysis); only then is it promoted to a failure, by a spec change. Uncovered families are appended to `LoadReport.advisories` (logged in `assets validate` without failing `validate`, `publish-shared`, `snapshot`, or `plugin install`).
  - The dangling-name check (a skill quotes a tool matching (1) or (2) above whose canonical key is absent from the hermetic known-tool set) appends to `LoadReport.warnings` and fails `assets validate` now.
- **Schema and discovery**:
  - `[families]` (and `[plugin.families]` as a supported alias) declared in `.praxia/manifest.toml` and plugin manifests (`manifest.toml` / `plugin.json`), matching cisternal's CLI discovery defaults (`src/cisternal/cli.py:517, 809`). Members are canonical keys (bare tool names inside a single-server plugin manifest are prefixed with `<plugin.name>/`; bare names in a workspace manifest with no server prefix fail validation):
    ```toml
    [families]
    bathos_query = ["bathos/run_sql", "bathos/get_run", "bathos/find_runs"]
    bathos_lineage = ["bathos/lineage_prov", "bathos/cite_run"]
    contemplex_brainstorm = ["contemplex/brainstorm_start", "contemplex/brainstorm_reply", "contemplex/brainstorm_finalize"]
    ```
  - `SkillAsset` is `@dataclass(frozen=True, slots=True)` (`assets/bundle.py:98`), not pydantic. Add `covers_families: tuple[str, ...] = ()` to `SkillAsset`, a `"covers_families": "list"` entry to `FIELD_KINDS` (`skill_schema.py:29`), and parse it from frontmatter as a tuple. No `Field(...)`.
  - `ManifestAssetSource` loads `[families]` (or `[plugin.families]`) into `AssetBundle.families` during manifest ingestion (forwarded by `CompositeAssetSource.merge_registry`); CLI `--manifest` takes a custom path, with fallback to `cisternal.toml` only when given explicitly.
- **Delivery**: part of `cisternal assets validate`.
- **Controls**:
  - Negative (family coverage): removing a declared family from every skill's `covers_families` produces a `LoadReport.advisories` warning (exit 0 in `validate`, `publish-shared`, and `snapshot`, per R3).
  - Negative (dangling name): renaming a tool in `[families]`/`[verbs]` while a skill still quotes the old `mcp__...` or `<server>/<tool>` name produces a `LoadReport.warnings` failure (exit 1).
  - Negative (false-positive guard): backticked bare identifiers (`` `run_sql` ``) and relative file paths or crate features (`` `references/foo.md` ``, `` `src/cisternal` ``, `` `pyo3/extension-module` ``) where the prefix is not a declared server emit no warning or failure.
  - Hermeticity control: running `assets validate` with `HOME` pointed at an empty temporary directory produces identical results to running on a configured developer machine.
  - Positive: with every family covered and every quoted name present, validate emits no C2 advisory or failure.
  - Live-style names: a skill quoting `mcp__plugin_bathos_bathos__run_sql` resolves to `bathos/run_sql` and is not dangling.

### C3: Skill Coverage Tooling
- **Source of truth**:
  - **Skills**: loaded from workspace manifests (`--manifest <path>`, repeatable, default `.praxia/manifest.toml`) and installed marketplace plugins (`--marketplace <path>`, default resolved read-only via `marketplace_root_source(marketplace)[0]` in `src/cisternal/plugin/config.py:91`—never `resolve_marketplace_root`, which writes `~/.config/cisternal/config.toml` when unconfigured; if `(None, ...)` is returned, the marketplace scan is skipped without creating config files). For each marketplace plugin directory, C3 resolves skill metadata in order:
    1. `.claude-plugin/cisternal-source.json` (`SOURCE_SIDECAR`, `plugin/shared.py:30`) → `source["manifest"]` loaded via `ManifestAssetSource` if the source checkout file exists on disk;
    2. `.claude-plugin/cisternal-source.json` inline `"skills_meta"` (`{skill_name: {"covers_families": [...], "distinctive_strings": [...]}}`, plus `"families"` and `"verbs"` for bundle-level tables), written by `publish_bundle` (`plugin/shared.py:119`) from `AssetBundle` on every `publish-shared` and `<tool> plugin install claude` (and preserved in `snapshot.py` for wheel installs);
    3. direct frontmatter parse of `<plugin_dir>/skills/<skill>/SKILL.md` if present.
    `format_skill_markdown` (`export/_markdown.py:77`) continues to write only documented Claude Code frontmatter keys into exported `SKILL.md` files (preserving stricter-consumer compatibility in `261017_skill-frontmatter-schema.md` item 7 and existing golden digests). Any third-party installed skill with empty `distinctive_strings` after (1)–(3) is reported in `unmonitored_skills` (with reason `"missing distinctive_strings"`), never counted as 0 missed opportunities.
  - **Transcripts**: C0 client transcripts (`discover_transcript_files`).
- **Schema**:
  - Add `distinctive_strings: tuple[str, ...] = ()` to `SkillAsset` (`bundle.py:98`) and `"distinctive_strings": "list"` to `FIELD_KINDS` (`skill_schema.py:29`).
  - Manual length check (1 to 5 entries, each non-empty) in `skill_schema.py`. Because `check_skill` warnings (`LoadReport.warnings`) are fatal in validate, publish, snapshot and plugin install (`listing_advisory` docstring), a missing field (`len == 0`) is reported through the non-fatal `LoadReport.advisories` path until the migration below lands; more than 5 entries, or empty strings (`""`), are a fatal `check_skill` warning from the start.
  - **Migration**: a one-off pass adds `distinctive_strings` (and `covers_families` where a family applies) to every shipped skill, i.e. every `[[plugin.skills]]` entry in `.praxia/manifest.toml` (today `.praxia/skills/{export-trust,run-cisternal,customizing-tools,writing-skill-triggers}/SKILL.md`), regenerates `src/cisternal/agent_plugin.json` (`assets snapshot`), and lists skills it could not fill. After the migration lands, a missing `distinctive_strings` moves to `check_skill`.
- **Opportunity definition**: a user turn or CLI command containing any of the skill's `distinctive_strings` (case-insensitive, whole-token).
- **Metrics per skill**: opportunity count, loaded-before-action rate, missed-opportunity list, tool calls after load, plus `unmonitored_skills` for plugins lacking `distinctive_strings`.
- **Precision (registered threshold)**: opportunity matching must reach a **point estimate** $\hat{p} = \text{TP} / (\text{TP} + \text{FP}) \ge 0.80$ over $n \ge 50$ hand-labelled matched turns (at $n = 50$, $\text{TP} \ge 40$), reported alongside its two-sided Wilson 95% confidence interval (e.g. `[0.670, 0.888]` at 40/50) so sampling uncertainty is visible, before opportunity counts are reported as certified. If fewer than 50 matched turns are evaluated, the gate status is `INCONCLUSIVE`. Registered in the C0/C3 sidecar `[outcomes]`.
- **Recall (R5, descriptive)**: about 30 hand-labelled sessions are marked "should have loaded skill X"; recall of the opportunity matcher against these labels is reported with its Wilson 95% interval and labelled descriptive (no threshold). Registered in the same sidecar.
- **Situation set**: `cisternal skill-coverage` writes the opportunity set used by C4b. Sets mined from real transcripts are untracked (git-ignored) or committed only redacted with a SHA-256 of the unredacted source recorded; CI uses a committed synthetic set `tests/fixtures/eval/synthetic_situations.jsonl`.
- **Delivery**: `cisternal skill-coverage`.
- **Controls**:
  - Negative: synthetic transcripts with known opportunities where the skill was invoked, not invoked, or invoked late, plus transcripts with 0 opportunities; unrelated tokens produce no opportunity; a skill with no `distinctive_strings` metadata appears in `unmonitored_skills`, not with 0 opportunities; running `skill-coverage` with an unconfigured marketplace does not create `~/.config/cisternal/config.toml` (`marketplace_root_source` read-only control).
  - Positive: a planted opportunity with no later invocation appears in the missed list; the same opportunity followed by a `Skill` tool_use does not; a marketplace plugin installed from a wheel snapshot (with `skills_meta` in `cisternal-source.json` and no source repo checkout) resolves its `distinctive_strings` and detects planted opportunities.

### C4: Progressive-Disclosure Honesty
Split into C4a (static lint, gating) and C4b (behavioural, descriptive only).

#### C4a: Static Honesty Lint (in `assets validate`; depends on C3's `distinctive_strings`)
- **Source of truth**: `SkillAsset` (`description`, `effective_when_to_use`, `distinctive_strings`, `body`, `resources` for `references/*.md`), plus baseline git tree at `--baseline-ref <ref>` when provided.
- **Tiers**: listing text (`description` + `effective_when_to_use`, target $\le 250$ chars) → `SKILL.md` body → `references/`.
1. **Check (a), no loss, with CI baseline**:
   - Every string in frontmatter `distinctive_strings` appears (case-insensitively) in the listing text (`description` / `effective_when_to_use`) or in the `SKILL.md` body.
   - In pull-request CI, `--baseline-ref origin/main` (or `HEAD~1`) is mandatory: every distinctive string present in the baseline skill's frontmatter must remain in the current listing text, body or `references/`. Removing one without keeping it elsewhere fails with `CAPABILITY_EROSION_DETECTED`.
   - **Edge cases for `--baseline-ref <ref>`**: if `<ref>` itself cannot be resolved to a commit by `git rev-parse --verify <ref>^{commit}`, `assets validate` fails immediately (exit 2). If `<ref>` is valid but a skill's file path did not exist at `<ref>` (e.g. a newly added skill such as C6 `triage-tool`), the baseline comparison is skipped for that skill and only current-file Check (a) runs.
2. **Check (b), no overclaim**:
   - Extracts candidate topic tokens that appear in the listing text (`description` + `effective_when_to_use`):
     1. backticked literals `` `([a-zA-Z0-9_\-\.:/]+)` ``;
     2. PascalCase / camelCase terms `\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b` or `\b[a-z0-9]+[A-Z][A-Za-z0-9]*\b` (requiring an internal lowercase-to-uppercase transition so ordinary sentence-initial capitalized words such as `Build`, `Decides`, `Also`, `When` are not matched);
     3. hyphenated or underscored terms `\b[a-z0-9]+(?:[-_][a-z0-9]+)+\b`.
     (`distinctive_strings` containment is governed by Check (a), and `covers_families` are internal manifest keys not required to appear in prose headings.)
   - Stopwords and common English hyphenated modifiers are excluded case-insensitively (the list includes `"for"`, `"with"`, `"when"`, `"use"`, `"audit"`, `"tools"`, `"support"`, `"handling"`, `"session"`, `"manage"`, `"agent-asset"`, `"read-only"`, `"non-empty"`, `"case-insensitive"`, `"single-repo"`, `"fail-open"`, `"warn-only"`, `"in-band"`, `"client-side"`, `"server-side"`, `"per-session"`, `"per-repo"`, `"short-description"`, `"tool-surface"`, `"cli-to-mcp"`; `When` and `when` are both excluded, as is any token already matched by Check (a)'s `distinctive_strings`).
   - Matching: a backticked token passes if it appears anywhere in the `SKILL.md` body or a `references/` file (prose, code or heading); it does not need to be a heading. Other candidate tokens pass if they appear, case-insensitively, in a section heading (`#`, `##`, `###`, `####`), fenced code block (` ```...``` `, extracted first), or inline code span (`` `[^`\n]+` ``, extracted after stripping fenced code blocks so triple-backtick fences do not invert inline backtick pairs) in `SKILL.md` or `references/`.
3. **Check (c), scope header**: `SKILL.md` has a `## Scope` or `## When to Use` heading (case-insensitive) within the first 50 body lines after frontmatter (`_split_frontmatter`, `assets/manifest.py:320`) and within 2,000 body characters.
- **Rollout and diagnostic routing**: before C4a is enabled as a fatal failure (`LoadReport.warnings`), it runs in report mode (`LoadReport.advisories`) against every shipped skill in `.praxia/manifest.toml` (`export-trust`, `run-cisternal`, `customizing-tools`, `writing-skill-triggers`—all 4 currently lack a `## Scope` or `## When to Use` heading under Check (c), and `export-trust` has an empty `description`); those findings are fixed or recorded (updating `src/cisternal/agent_plugin.json` and `tests/golden/{,rust_parity/}self_manifest/` where skill files change), and the run output is attached to the enabling change.
- **Delivery**: part of `cisternal assets validate` (with optional `--baseline-ref <ref>`).
- **Controls**:
  - Negative: a non-stopword listing token absent from headings/code/references fails (b); a baseline distinctive string removed from listing, body, and references fails (a) with `CAPABILITY_EROSION_DETECTED`; an unresolvable `--baseline-ref` exits 2; a missing scope heading in the first 50 body lines fails (c).
  - Positive: a skill whose backticked listing token appears only in body prose passes (b); a `distinctive_strings` entry in body prose passes both (a) and (b) without needing a `#` heading; a newly added skill absent from `--baseline-ref` passes baseline Check (a); `When to use` with capital W raises no stopword token; a compliant skill passes (a), (b) and (c).

#### C4b: Behavioural Fire-Rate Comparison (DESCRIPTIVE ONLY — R2)
- **Source of truth**: paired evaluation runs of each skill's short description ($\le 250$ chars) vs its long baseline description over the C3 situation set (`tests/fixtures/eval/synthetic_situations.jsonl` in CI, or the untracked/redacted real situation set).
- **Metrics**: reports paired fire rates $P(\text{fire} \mid \text{short})$ and $P(\text{fire} \mid \text{long})$, each with a two-sided Wilson 95% interval, plus the paired discordant counts ($b$: short fires & long misses; $c$: short misses & long fires).
- **Descriptive status (R2)**: no pass/fail and no threshold. The available $n$ cannot resolve a 0.05 difference, so no non-inferiority margin is set. Runs off the critical path and blocks nothing; C4a remains the only gating check on descriptions. The reported quantities are registered (descriptive) in the C0/C3 sidecar.
- **Delivery**: `scripts/usage/c4b_fire_rate.py` (or `cisternal skill-coverage --compare-descriptions`), emitting JSON and summary tables for the C0/C3 sidecar.
- **Controls**:
  - Negative (null-difference control): running two identical descriptions over the synthetic situation set under deterministic mock/replay yields $P(\text{fire} \mid \text{short}) = P(\text{fire} \mid \text{long})$ with $b = c = 0$ discordant pairs.
  - Positive (sensitivity control): a deliberately degraded description (all domain nouns stripped) is run once to show the harness detects a drop in fire rate; the result is reported descriptively, not gated.

### C5: Verb-to-Tool Nudge Hook
- **Prerequisites**: Pre-0 (`parse_cli_commands`, `canonical_tool_key`), C0 (transcript parsing used to check the E4 re-derivation), C1 (`scan_active_registrations` in `src/cisternal/usage/registrations.py`), and C2 (`[families]`). Not Pre-1: the PostToolUse hook classifies errors itself. Independent of C6.
- **Source of truth**:
  - Declarative `[verbs]` and `[families]` tables (`AssetBundle.verbs`, `AssetBundle.families`), loaded by `scan_active_registrations()` from cisternal's own bundle (`locate_bundle` / `loads_snapshot` on `src/cisternal/agent_plugin.json` or checkout `.praxia/manifest.toml`, `plugin/app.py:170`) plus any installed plugin `.claude-plugin/cisternal-source.json` sidecars, so hooks work in any working directory and under wheel installs without requiring `cwd` to be the `cisternal` repo;
  - Active registration cache `<sessions dir>/active_servers.json` written and refreshed by `scan_active_registrations()`;
  - Session error ledger `<sessions dir>/<session_id>/errors.jsonl` written solely by the client-side `PostToolUse` hook.
- **Delivery**: cisternal `hook_specs` (A1): a `PreToolUse` hook with matcher `Bash`, and a `PostToolUse` hook with matcher `mcp__.*` (plus `PostToolUseFailure` with matcher `mcp__.*` if the A6/RISK-01 fixture probe shows Claude Code routes wire-level MCP failures there). Adding `hook_specs` to `.praxia/manifest.toml` updates `src/cisternal/agent_plugin.json` and `tests/golden/{,rust_parity/}self_manifest/`.
- **`[verbs]` manifest** (`[verbs]` or `[plugin.verbs]` in `.praxia/manifest.toml` for workspace assets, `manifest.toml` for plugins; loaded by `ManifestAssetSource` into `AssetBundle.verbs` and forwarded by `CompositeAssetSource.merge_registry`); targets are canonical keys:
  ```toml
  [verbs.bathos]
  binary = "bth"
  subcommands = { sql = "bathos/run_sql", show = "bathos/get_run", validate-sidecar = "bathos/validate_sidecar" }
  tool_family = "bathos_query"
  global_flags_with_value = []   # filled from `bth --help` when implemented
  exclude = ["run"]

  # UNVERIFIED: ctxp and myxcel subcommand names and tool names below are not checked against either CLI.
  [verbs.contemplex]
  binary = "ctxp"
  subcommands = { start = "contemplex/brainstorm_start", reply = "contemplex/brainstorm_reply", finalize = "contemplex/brainstorm_finalize" }
  tool_family = "contemplex_brainstorm"
  global_flags_with_value = []
  exclude = []

  [verbs.myxcel]
  binary = "myxcel"
  subcommands = { status = "myxcel/job_status", list = "myxcel/list_jobs", logs = "myxcel/job_logs" }
  tool_family = "myxcel_slurm"
  global_flags_with_value = []
  exclude = ["submit", "cancel"]
  ```
- **Session error ledger (single author)**:
  - The client-side `PostToolUse` hook is the only writer. There is no server-side writer and no cross-session `default` ledger: `session_id_var` is never set in `src/` (A2), so a server tier could not key records by session.
  - Ledger path: `<sessions dir>/<session_id>/errors.jsonl`, with `<sessions dir>` from the derived-data resolver (project-root anchoring via `$CLAUDE_PROJECT_DIR` or skipping `pyproject.toml` when unset, atomic append, size cap, and off switch all apply).
  - **Which calls count**: only a `tool_name` starting with `mcp__` is considered. Bash and other tools are never logged as MCP errors, and no prose regex is used.
  - **Error classification** for an `mcp__` call, by canonical key's server:
    1. protocol error flag set in the hook payload's tool response (or delivered via `PostToolUseFailure`, RISK-01) → error;
    2. else, if the response text decodes as a JSON object, apply the server's top-level envelope rule:
       - `bathos`, `xperiri`: top-level `ok is False`;
       - `contemplex` (*UNVERIFIED against external `contemplex.errors.err_envelope`, RISK-02*): top-level `ok is False` or (`error_code` is a non-empty string and `ok` is not `True`);
       - `myxcel` (*UNVERIFIED against external `myxcel` in-band errors, RISK-02*): top-level object where `"error"` is a non-empty string, `"message"` is a string, and `"ok"` is not `True`;
       - servers with no rule: top-level `ok is False` only;
    3. otherwise → not an error.
    Keys inside nested data (e.g. a result row with an `error` column) are never inspected.
  - **Record**: `timestamp`, `session_id`, `tool` (canonical key), `family` (from `[families]`, may be null), `error_code` (if present), `message` (truncated), `source = "post_tool_use"`.
  - **Fixtures**: for each adapter (bathos, contemplex, xperiri, myxcel, passthrough), a captured real success response and a captured real error response, as delivered to the hook on stdin, under `tests/fixtures/hooks/post_tool_use/`. These fixtures verify A6, RISK-01 (`PassthroughAdapter` wire error event routing), and RISK-02 (`contemplex` and `myxcel` envelope keys) before C5 is enabled.
- **PreToolUse protocol**:
  1. Load `active_servers.json` from `<sessions dir>/active_servers.json` (rebuilding via `scan_active_registrations()` using atomic temp-file + `os.replace` if the cache file is missing or if the mtime of `claude_home() / "settings.json"`, `~/.claude.json`, or any installed plugin's `.claude-plugin/plugin.json` / `.mcp.json` / `.claude-plugin/cisternal-source.json` is newer than the cache's mtime; reads only local JSON/snapshot/manifest files, never spawning a `claude` CLI subprocess).
  2. Call `parse_cli_commands(command, verbs)` using the cached `verbs` table; if the returned list is empty → exit 0, no output.
  3. Iterate over each `(binary, subcommand)` in left-to-right order:
     a. If `subcommand in verbs[binary].exclude` → continue to the next segment.
     b. Map `(binary, subcommand)` to its canonical key `server/tool` and `tool_family`.
     c. **MCP active check**: look up the target's canonical key in `active_servers.json["tools"]` (which maps each active `server/tool` from `[families]`/`[verbs]` to `<raw_prefix><tool>` using the active server's wire prefix `mcp__plugin_<plugin>_<server>__` or `mcp__<server>__`). If the target canonical key is not in `active_servers.json["tools"]` (or if config files are unreadable) → continue to the next segment.
     d. If `<sessions dir>/<session_id>/errors.jsonl` has a record whose `tool` or `family` matches → suppress for this segment and continue to the next segment. No ledger file → not suppressed.
     e. For the first segment that is not excluded, is active, and is not suppressed, print exactly and exit 0:
        ```json
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "An equivalent MCP tool is available: <raw name> (bathos/run_sql)."}}
        ```
        `<raw name>` is the name the tool is registered under in this session, read from `active_servers.json["tools"][canonical_key]` (canonical key → registered raw name): e.g. `mcp__plugin_bathos_bathos__run_sql` when bathos is installed as a plugin, `mcp__bathos__run_sql` when it is a standalone server. The hook never guesses the raw name from the canonical key alone without the active server's registration prefix. The text names the tool and makes no claim about speed or telemetry.
  4. If no segment triggers a nudge → exit 0, no output.
- **Shell safety and limits**:
  - Fail-open: any exception or missing/corrupt file → exit 0 with no output.
  - Payloads are read from stdin, never passed as arguments (avoids Linux's 128 KiB `MAX_ARG_STRLEN`).
  - Latency budget: PreToolUse p95 ≤ 150 ms per Bash call, measured by a benchmark test over 100 invocations on the golden payload for both warm-cache lookup and cold-cache rebuild (`scan_active_registrations`); a regression above budget fails that test. No sub-millisecond claim is made.
- **Controls**:
  - Golden output test: the PreToolUse stdout is compared to a captured real Claude Code hook run's expected JSON shape.
  - Nudge fires on `bth sql`, `rtk bth sql`, `env X=1 bth sql`, and compound commands `cd /tmp && bth sql "SELECT 1"`, `bth run foo && bth sql "SELECT 1"` (skipping the excluded `bth run` segment and nudging on `bth sql`).
  - No nudge on `bth run` (excluded), `bth --unknown sql` (unparsed), or when the target server is not active.
  - No nudge on `bth sql` when the session ledger has a record for `bathos/run_sql` or `bathos_query`.
  - Cross-cwd ledger resolution control (GAP-26): invoking `PostToolUse` (logging a `bathos/run_sql` error) with `cwd=/tmp/dir_a` and `PreToolUse` (on `bth sql`) with `cwd=/tmp/dir_b` (where `/tmp/dir_b` contains a decoy `pyproject.toml` with a different `[tool.cisternal]` path and `$CLAUDE_PROJECT_DIR` is unset or fixed) resolves the same `<sessions dir>` and suppresses the nudge.
  - Cold-cache rebuild control (GAP-23): with `active_servers.json` absent and fake `~/.claude/settings.json` + plugin manifest present in `tmp_path`, `PreToolUse` rebuilds `active_servers.json` atomically and emits the nudge within the 150 ms p95 budget.
  - Exit 0, no output, when the ledger or config files are missing or corrupt.
  - Positive controls for classification: a CLI (`Bash`) call whose output contains `Error:` writes no ledger record and therefore does not suppress a later nudge; a bathos `run_sql` success payload whose rows contain an `error` column writes no record; each adapter's captured error fixture writes exactly one record.

### C6: `triage-tool` Skill
- **Source of truth**: JSON and summary output from `cisternal usage` (C0, client transcripts with optional server `duration_ms` enrichment) and `cisternal prune-list` (C1, active registrations intersected with C0 usage).
- **Path and schema**: `.praxia/skills/triage-tool/SKILL.md` (with component walkthroughs in `.praxia/skills/triage-tool/references/`), declared as a `[[plugin.skills]]` entry in `.praxia/manifest.toml` like the other shipped skills, with `distinctive_strings` (C3) and `## When to Use` / `## Scope` in the first 50 body lines (C4a).
- **Trigger**: listing text (`description` + `effective_when_to_use`) $\le 150$ characters (e.g. `"Use when auditing agent MCP/skill use or pruning unused tool servers before changing project settings."`).
- **Dependencies**: C0 and C1 only, as in the graph. It does not depend on C4a or C4b; like every shipped skill it is checked by C2, C3, and C4a once enabled. Adding `triage-tool` to `.praxia/manifest.toml` updates `src/cisternal/agent_plugin.json` (`assets snapshot`) and `tests/golden/{,rust_parity/}self_manifest/`.
- **Safety**: non-destructive. It produces recommendations for manual review and contains no instructions or commands that modify `~/.claude/settings.json` or `~/.claude.json`.
- **Delivery**: shipped in cisternal's plugin bundle via `.praxia/manifest.toml` (`cisternal assets export` / `publish-shared` / `snapshot`).
- **Controls**:
  - Negative: static test asserts `.praxia/skills/triage-tool/SKILL.md` and `references/*.md` contain no shell commands or code blocks writing to `settings.json` or `.claude.json`, and asserts `skill.listing_chars <= 150` (failing if the trigger exceeds 150 chars).
  - Positive: `ManifestAssetSource(Path(".praxia/manifest.toml")).load()` loads `triage-tool` with zero `warnings` and zero `conflicts`, passes C2 dangling-name check and C4a static honesty lint, and `cisternal assets snapshot --check` + `cisternal assets validate --manifest .praxia/manifest.toml` exit 0.

## Order and Dependency Graph

```
 +---------------------------------+        +----------------------------------------+
 | Pre-0: transcript parsing core  |        | Pre-1: adapter error normalization     |
 | (canonical key, CLI tokenizer,  |        | (independent; parallel or later)       |
 |  subagent glob, repo key)       |        +----------------------------------------+
 +---------------------------------+                         │
                 │                                           ▼
                 ▼                          [later server-side enrichment of C0 output;
 +---------------------------------+         not on any critical path in this spec]
 | C0: usage counter (+ sidecar)   |
 +---------------------------------+
        │              │              │
        ▼              ▼              │
 +-------------+  +-------------------+│
 | C1: prune   |  | C2: coverage lint ││
 | list & reg. |  | (advisory warn;   ││
 | scanner     |  |  dangling fails)  ││
 +-------------+  +-------------------+│
    │   │              │  (shared schema + LoadReport.advisories + snapshot late defaults)
    │   │              ▼              │
    │   │         +-------------------+
    │   │         | C3: skill coverage|
    │   │         +-------------------+
    │   │              │         │
    │   │              ▼         ▼
    │   │     +-------------+  +------------------------------+
    │   │     | C4a: static |  | C4b: fire-rate comparison    |
    │   │     | lint (gate) |  | (descriptive only, blocks    |
    │   │     +-------------+  |  nothing)                    |
    │   ▼                      +------------------------------+
    │  +---------------------------------+
    │  | C6: triage-tool skill (C0, C1)  |
    │  +---------------------------------+
    │
    └───► (Pre-0, C0, C1, C2) ──► +---------------------------------+
                                  | C5: nudge hook                  |
                                  | (PostToolUse sole ledger author;|
                                  |  lazy active_servers.json cache)|
                                  +---------------------------------+
```

**Build sequence**:
- Mainline: `Pre-0 -> C0 -> (C1, C2)`; `C2 -> C3 -> C4a`; `(C0, C1) -> C6`.
- Hook track: `(Pre-0, C0, C1, C2) -> C5` (C5 uses Pre-0's compound CLI tokenizer, C0's E4 re-derivation, C1's `scan_active_registrations` cache writer, and C2's `[families]`).
- Descriptive track: `C3 -> C4b` (blocks nothing).
- Independent: `Pre-1` (parallel; feeds only a later server-side enrichment).
- C2 promotion from `LoadReport.advisories` (warn) to `LoadReport.warnings` (fail) waits on a registered C3 result (R3).

## Not in Scope
- Global `CLAUDE.md` additions such as "search more" rules (E2: agents rarely keyword-search, and such rules add standing context).
- Consolidating bathos tools into action-dispatch families.
- Automatic changes to `~/.claude/settings.json` or `~/.claude.json` by any tool or skill.
- Measuring whether the nudge changes behaviour (A7); that needs a separate matched-session study.

## Build Constraints
Implementation runs in a cisternal session in its own worktree. Every dispatch names its model explicitly:
- spec revision and adversarial review (challenger, defender): Claude Opus;
- implementation of Pre-0, Pre-1, C0–C5: Claude Opus;
- test and fixture authoring (redaction, golden fixtures, controls): Claude Sonnet;
- mechanical edits (docs index, migration pass over shipped skills): Claude Haiku.
Claim every file created or changed. Touch nothing outside `.praxia/docs/` during spec and audit revisions.

---

## Changelog

### Cycle 1 Revisions (Phase 3 Adversarial Challenge & Defense) — 2026-11-06
- **A8 Refutation & Pre-1 Insertion**: Updated Assumption A8 from `UNVERIFIED` to **REFUTED** with code citations to `src/cisternal/adapters/base.py:278–388` (demonstrating heterogeneous error envelopes across `BathosAdapter`, `PassthroughAdapter`, `ContemplexAdapter`, `XpeririAdapter`, and `MyxcelAdapter`). Inserted **Pre-1: Adapter Error Shape Normalization Pass** into `base.py` before C0 error tracking and C5 error suppression (GAP-02).
- **Pre-0 Vendoring**: Resolved cross-repository boundary blocker by defining **Pre-0: Vendored Transcript Parsing Core** from `praxia` into `src/cisternal/usage/transcript.py` with attribution, eliminating praxia-specific `CLI_RE` regex (GAP-01).
- **C0 Controls & Stratification**: Upgraded C0 negative control to paired positive and negative controls ($N=5$ planted calls, $N=0$ uncalled tools, length check) to guard against silent masking parser bugs. Mandated session-type stratification (`main_interactive` vs `subagent_headless`) to account for subagent context and execution differences (GAP-04, GAP-13).
- **C1 Safety & Lookback**: Added active asset whitelisting to C1's registration scanner to protect hook-only and skill-only plugins from destructive pruning. Established lookback sample window of $N \ge 20$ sessions (or 14 days) before generating prune recommendations (GAP-08, GAP-09).
- **C2 Declarative Family Schema**: Defined declarative `[families]` manifest schema in `cisternal.toml` and `covers_families` attribute in `SkillAsset`. Retained E3 consistency: individual tool names are not required to appear in skills (GAP-07).
- **C3 Distinctive Strings & Precision**: Specified storage of `distinctive_strings: list[str]` in skill frontmatter. Established $\ge 0.80$ precision threshold on a frozen hand-labelled evaluation sample. Defined serialized frozen situation set output feeding C4b (GAP-07, GAP-12).
- **C4 Decomposition**: Split C4 into **C4a (Static Honesty Lint)**—executable immediately in `assets validate` with deterministic AST rules for containment, overclaim, and scope header—and **C4b (Behavioral Non-Inferiority Gate)**—pre-registering non-inferiority margin $\delta \le 0.05$ at 95% confidence on the frozen opportunity set (GAP-05, GAP-06, GAP-12).
- **C5 Session Error State & Streaming**: Specified on-disk session error ledger (`~/.cisternal/sessions/<session_id>/errors.jsonl`) emitted by telemetry and read by hook subshells to bridge subprocess statelessness. Specified Claude Code output JSON schema (`{"additionalContext": "..."}`), fail-open semantics, and temp-file streaming to prevent 128 KiB shell argument clipping (GAP-03, GAP-11).
- **Order and Dependency Realignment**: Updated build order and dependency graph to `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C4b -> C6 -> C5` (GAP-01, GAP-02).
- **Epistemic Reframing**: Consistently reframed exploratory evidence E1–E5 as Preliminary Motivating Probes; rephrased "E3 falsifies", "the 57 errors", and "discovery is not the bottleneck" into parametric design rationales (GAP-10).

### Cycle 2 Revisions (Phase 3 Adversarial Challenge & Defense) — 2026-11-06
- **GAP-14: Two-Tier Ephemeral Error State Ledger**: Resolved stdio MCP session ID disconnect where `session_id_var` was unset on server. Assigned primary error ledger authorship to client-side `PostToolUse` hook (`~/.cisternal/sessions/<session_id>/errors.jsonl`) using Claude Code stdin payload `INPUT.session_id`. Added server fallback to `~/.cisternal/sessions/default/errors.jsonl` in `AdapterBase.normalize_error` (safely handling `session_id_var.get() or "default"`). C5 PreToolUse hook performs dual lookup (session-exact ledger + recent 15-minute default ledger). *(Server tier and default ledger deleted in Cycle 5.)*
- **GAP-15: Native Transcript Parsing Core (Pre-0)**: Replaced external vendoring directive from unmounted path `/home/marielle/projects/praxia` with a clean native cisternal implementation in `src/cisternal/usage/transcript.py`. Added formal header attribution to Praxia `session_context_audit.py`, eliminating all cross-repository filesystem build dependencies.
- **GAP-16: Uncoupled Build Order & Non-Blocking C4b**: Uncoupled C6 (`triage-tool` skill) and C5 (nudge hook) from C4b (behavioral non-inferiority gate). Operational delivery sequence updated to `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C6 -> C5`, allowing deterministic tools and static lints to ship in hermetic CI while branching C4b into an asynchronous, non-blocking evaluation track.
- **GAP-17: Deterministic AST Grammar & Mandatory CI Baseline (C4a)**: Defined formal candidate topic token extraction grammar for Check (b) (backticked terms, PascalCase/camelCase identifiers, hyphenated/underscored verb-noun expressions, declared keywords; excluding standard English stopwords). Mandated `--baseline-ref origin/main` in CI pull-request validation for Check (a) to catch silent deletion of distinctive capabilities during description compression.
- **GAP-18: Client Transcripts as Self-Contained Primary Truth (C0)**: Established Claude Code client JSONL transcripts as the self-sufficient primary source of truth for all tool counters, CLI invocations, ToolSearch query provenance (`select:<name>`), and error-to-fallback transitions. Relegated server JSONL logs to optional, non-blocking duration enrichment (`duration_ms`).
- **GAP-19: Standardized Family Schemas in `.praxia/manifest.toml` (C2)**: Anchored declarative `[families]` table in `.praxia/manifest.toml` (and plugin manifests) matching cisternal's CLI discovery defaults (`src/cisternal/cli.py:517, 809`).

### Cycle 3 Revisions (Phase 3 Adversarial Challenge & Defense) — 2026-11-06
- **GAP-20: Dependency Ordering Realignment (`C3 -> C4a`) & Error-Path Mainline Link**: Re-routed dependency graph so that `C2` leads to `C3` and `C3` leads to `C4a` (`C2 -> C3 -> C4a`), ensuring `C4a` static AST containment and overclaim lints can access `distinctive_strings` declared in `SkillAsset`. Realigned mainline build sequence to `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> C3 -> C4a -> C6`, and decoupled `C5` from `C6` by explicitly routing `(Pre-1, C0, C2) -> C5`.
- **GAP-21: In-Band Error Envelope Parsing in `PostToolUse` Hook & Declarative `[verbs]` Manifest Schema**: Updated client-side `PostToolUse` hook specification to parse JSON tool result text for canonical error keys, preventing blindness to adapter-wrapped errors where wire-protocol `is_error` is `false`. Defined declarative `[verbs]` manifest schema mapping CLI commands `(binary, subcommand)` to `(tool_name, tool_family)` with an explicit `exclude` list (e.g. `bth run`).
- **GAP-22: Package Boundary Separation & Sandbox Mount Clarification**: Corrected Pre-0 and audit documentation regarding `/home/marielle/projects/praxia`. Clarified that `praxia` is an external sibling repository outside cisternal's package boundary that is unmounted in sandboxed and CI environments.

### Cycle 4 (Phase 3 Adversarial Challenge & Defense) — 2026-11-06 — superseded
- Cycle 4 argued six probes (POSIX atomic append, subagent transcript segregation, CLI tokenizer wrappers, fallback-ledger latency, C4a scope-header parsing, prune-list sample floor). None cited an executed test, so Cycle 5 withdraws their conclusions as verification claims; the earlier status, gap count and loop-termination claims are withdrawn with them. Each subject is now an explicit test requirement (atomic-append concurrency test, Pre-0 session-type probe, tokenizer cases, latency benchmark, C4a controls, C1 floor controls), except the fallback ledger, which Cycle 5 deletes.

### Cycle 5 Reconciliation (spec revision brief A1–A16, decisions R1–R5) — 2026-11-06
Claimed by: cycle5_reviser. Status returned to `draft`. Audit: `.praxia/docs/audits/261106_cycle5_audit.md`.
- **A1** PreToolUse output is `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ...}}`; golden test against a captured real hook run.
- **A2** Canonical tool key `server/tool` (prefix-stripped from `mcp__plugin_<p>_<s>__x`, `mcp__<s>__x`, bare `x`) added under Shared Definitions; families, verbs, C0, C1 and the dangling check use it; test with live-style names.
- **A3** C0 transcript dir corrected to `~/.claude/projects/<slug>/*.jsonl`.
- **A4** A5 returned to UNVERIFIED (constant restates a secondhand binary reading; cap configurable via `skillListingMaxDescChars`); A3 cites `skill_schema.py:153`.
- **A5** `covers_families` / `distinctive_strings` specified as tuple fields on the frozen, slotted `SkillAsset` (`bundle.py:98`), with `FIELD_KINDS` entries (`skill_schema.py:29`), a manual length check, and a migration for existing skills. Pydantic `Field` removed.
- **A6** Server fallback ledger and 900 s cross-session default ledger deleted (`session_id_var` is never set in `src/`); the client PostToolUse hook is the sole author; no ledger means nudge.
- **A7** `normalize_error` is a non-abstract default; `normalize_exception` added; adapters write no files; Passthrough text reworded (it re-raises).
- **A8** PostToolUse counts only `mcp__` tool names; prose regex removed; per-server envelope rules; per-adapter success/error fixtures; positive controls (CLI error does not suppress; success payload with an `error` column does not log).
- **A9** C1 floor is N ≥ 20 sessions AND ≥ 14 days, per-repo N for `enable-per-project`; `enable-per-project` rewritten; rule-of-three limit stated.
- **A10** Session-type signal (`isSidechain` or file location) chosen by a Pre-0 probe and recorded; `stratify_session_type` takes an iterable; A9 decided by C0.
- **A11** Controls: golden fixture from a redacted real transcript; wrapper tokenizer cases; positive controls for C2, C3, C4a; C4a run against shipped skills before enabling.
- **A12** Derived-data directory resolver (arg > env > pyproject > XDG > off) with layer reporting, atomic append, size cap and off switch, generalized from `pipeline.py:222`.
- **A13** Real-transcript situation sets untracked or redacted and hashed; CI uses a synthetic set.
- **A14** "MCP active" mechanism (registration cache), canonical names in `[verbs]`, global-flag handling, latency budget; nudge text no longer claims speed or telemetry; ctxp/myxcel verbs marked UNVERIFIED.
- **A15** C0 sidecar with `[outcomes]` committed before first run (scripts, conditions, C3 0.80 threshold, C3 recall, C4b descriptive quantities; the C4b delta in A15 is superseded by R2). E1–E5 labelled unregistered; E1 = 10.6%; E4 intervals added. C6 text and graph agree (C0, C1). Build Constraints name a model per role.
- **A16** Check (b) stopwords are case-insensitive; backticked tokens need not be headings.
- **R1** Pre-1 independent of Pre-0, off the C0/C1 critical path; graph `Pre-0 -> C0`, Pre-1 parallel feeding only a later server-side enrichment; C5 no longer depends on Pre-1.
- **R2** C4b descriptive only: paired fire rates with intervals, no pass/fail, no margin; 0.05 margin and Wilson-difference formula removed.
- **R3** C2 family coverage warn-only until C3 shows a relation to tool use; dangling-name check fails now.
- **R4** C1 uses per-skill invocation counts; skill-bearing plugins eligible for `drop` when all skills have 0 invocations over the floor; hooks and commands still whitelist.
- **R5** C3 adds a ~30-session hand-labelled recall sample, reported with its interval and labelled descriptive; precision keeps its interval; both registered.

Cycle 5 re-review corrections (claimed by cycle5_rereviewer; errors in how the revision above implemented A2/A5, recorded in the cycle 5 audit Part 4):
- C0 synthetic fixture no longer plants a bare `run_sql` in a transcript as `bathos/run_sql` (contradicted the A2 rule that bare names resolve only in a manifest); it uses the two `mcp__` forms (GAP-32).
- C5 nudge text prints the registered raw name from the active-servers cache instead of a hard-coded `mcp__bathos__run_sql`, which does not exist when bathos is installed as a plugin (GAP-28).
- Migration target and C6 path corrected from the nonexistent `src/cisternal/assets/skills/` to the `[[plugin.skills]]` entries of `.praxia/manifest.toml` (`.praxia/skills/<name>/SKILL.md`) (GAP-31).

### Cycle 6 Revisions (Resolution of Cycle 5 Open Gaps & Codebase Integration Audit) — 2026-11-08
Claimed by: challenger_c6, defender_c6. Audit: `.praxia/docs/audits/261106_cycle6_audit.md`.
- **GAP-23 (Registration cache ownership & graph edge)**: Extracted `scan_active_registrations()` into `src/cisternal/usage/registrations.py` (shared by C1 and C5) and added `C1` to C5's prerequisites and dependency graph (`(Pre-0, C0, C1, C2) -> C5`). C5's `PreToolUse` hook lazily creates or rebuilds `<sessions dir>/active_servers.json` via atomic temp-file + `os.replace` on cache miss or stale mtime (reading local JSON files only, no `claude` subprocess), with both warm-cache and cold-cache rebuild covered by the 150 ms p95 benchmark test.
- **GAP-24 & GAP-33 (Hermetic C2 dangling-name definition)**: Defined quoted tool names in skills as backticked tokens (or `allowed_tools` / `disallowed_tools` entries) matching raw `mcp__...` form or `<server>/<tool>` where `<server>` is in the hermetic declared-server set; bare words and file paths are never checked. Defined the hermetic known-tool set for `assets validate` from `[families]`, `[verbs]`, and `AssetBundle.commands` (never reading machine-local `~/.claude.json` or `~/.claude/settings.json`).
- **GAP-25 (Compound shell commands in CLI tokenizer)**: Added `parse_cli_commands(cmd, verbs) -> list[tuple[str, str]]` splitting unquoted `&&`, `||`, `;`, `|`, `&`, and `\n` (skipping command substitutions `$(...)` / backticks and unclosed quotes fail-open). C0 tallies all matched segments; C5 evaluates segments in order and nudges on the first non-excluded, active, non-suppressed match.
- **GAP-26 (Consistent `<sessions dir>` across hook processes)**: Anchored layer-3 `pyproject.toml` lookup in hooks to `$CLAUDE_PROJECT_DIR` when set, and skipped layer 3 in hooks when `$CLAUDE_PROJECT_DIR` is unset (falling straight from `CISTERNAL_SESSIONS_DIR` to XDG default). Added a cross-cwd control with a decoy `pyproject.toml`.
- **GAP-27 (Unambiguous C3 precision gate)**: Specified that the registered 0.80 threshold applies to the **point estimate** $\hat{p} = \text{TP} / (\text{TP} + \text{FP}) \ge 0.80$ over $n \ge 50$ hand-labelled matched turns (with two-sided Wilson 95% interval reported alongside, and `INCONCLUSIVE` if $n < 50$).
- **GAP-29 (Nested subagent transcript discovery)**: Added `discover_transcript_files` in Pre-0/C0 covering both `<slug>/*.jsonl` and `<slug>/<session_id>/subagents/*.jsonl`, plus a multi-stratum directory control.
- **GAP-30 (Canonical repository key across worktrees)**: Added `resolve_repo_key(session_cwd, slug)` in Pre-0/C1 folding `/.claude/worktrees/<name>` paths and `--claude-worktrees-<suffix>` slugs into their parent repository for per-repo session floors and 80% concentration checks.
- **GAP-34 (Skill metadata preservation for installed plugins)**: Kept `format_skill_markdown` (`export/_markdown.py:77`) emitting only documented Claude Code keys; updated `publish_bundle` (`plugin/shared.py:119`) to write `skills_meta` (`covers_families`, `distinctive_strings`) into `.claude-plugin/cisternal-source.json` and `snapshot.py` to round-trip both fields. C3 reads `--manifest` and `--marketplace` plugins (via `cisternal-source.json` manifest path, then `skills_meta`, then `SKILL.md`), reporting skills without `distinctive_strings` under `unmonitored_skills`.
- **RISK-01 & RISK-02 (Hook error routing & external adapter envelopes)**: Added `PostToolUseFailure` check to the A6/C5 fixture capture probe (RISK-01), relaxed the `myxcel` and `contemplex` top-level envelope checks in C5, and marked both external envelope shapes UNVERIFIED until checked against captured real error fixtures (RISK-02).
- **GAP-35 (`LoadReport.advisories` vs fatal `LoadReport.warnings`)**: Added `LoadReport.advisories: tuple[str, ...] = ()` so warn-only / report-mode diagnostics (C2 family coverage under R3, C3 pre-migration missing `distinctive_strings`, C4a report mode) log in `validate_assets` without causing `validate`, `publish-shared`, `snapshot`, or `plugin install` to exit 1.
- **GAP-36 (`CompositeAssetSource`, `snapshot.py` late defaults, and golden digests)**: Specified forwarding of `families`, `verbs`, and `advisories` in `CompositeAssetSource.merge_registry` (`composite.py:65`), late-default omission (`_SKILL_LATE_DEFAULTS`) and `bundle_from_dict` restoration in `snapshot.py` (`:36, :88`), and updating `src/cisternal/agent_plugin.json` plus `tests/golden/{,rust_parity/}self_manifest/` whenever `.praxia/manifest.toml` assets change.
- **GAP-37 (C4a Check (a)/Check (b) reconciliation and `--baseline-ref` edge cases)**: Removed `distinctive_strings` and `covers_families` from Check (b)'s heading requirement (resolving the contradiction with Check (a)), clarified fenced/inline code matching and hyphenated-modifier stopwords, and defined `--baseline-ref` behaviour for newly added skills (skip baseline comparison) vs invalid git refs (exit 2).
- **GAP-38 (Explicit Source of truth / Delivery / Controls on C4a, C4b, and C6)**: Added explicit `Source of truth`, `Delivery`, and paired negative/positive `Controls` sections to C4a, C4b, and C6.

### Cycle 7 Revisions (Marketplace Read-Only Resolution, Active-Server Tool Expansion & Shipped-Skill Check) — 2026-11-08
Claimed by: challenger_c7, defender_c7. Audit: `.praxia/docs/audits/261106_cycle7_audit.md`.
- **GAP-39 (Read-only `marketplace_root_source` vs mutating `resolve_marketplace_root` and `claude_home()`)**: Replaced `resolve_marketplace_root` (`plugin/config.py:162`, which creates/modifies `~/.config/cisternal/config.toml` when unconfigured) with read-only `marketplace_root_source` (`plugin/config.py:91`) in C1, C3, and C5, and anchored `~/.claude` paths to `claude_home()` (`$CLAUDE_CONFIG_DIR` or `~/.claude`, `plugin/shared.py:143`) with a read-only control test.
- **GAP-40 (`scan_active_registrations()` tool-name expansion and C5 runtime bundle loading outside checkout)**: Specified that because `.claude-plugin/plugin.json` and `.mcp.json` (`export/claude.py:145–151, 216–229`) contain only plugin and server names (not individual tool names like `run_sql`), `scan_active_registrations()` maps each active server to its wire prefix (`mcp__plugin_<plugin>_<server>__` or `mcp__<server>__`) and combines that prefix with the known tool names in `[families]` and `[verbs]` (loaded via `locate_bundle` / `loads_snapshot` from `src/cisternal/agent_plugin.json` or checkout `.praxia/manifest.toml` plus installed plugin `cisternal-source.json` sidecars) to populate `active_servers.json["tools"]` (`canonical_key -> registered_raw_name`), `verbs`, and `families`.
- **GAP-41 (C4a Check (b)/Check (c) regex and fence-stripping audit against shipped `.praxia/manifest.toml` skills, and `[plugin.families]`/`[plugin.verbs]` aliases)**: Executed C2 and C4a Check (b)/Check (c) extraction rules against all 4 shipped skills in `.praxia/manifest.toml` (`export-trust`, `run-cisternal`, `customizing-tools`, `writing-skill-triggers`); fixed Check (b)'s PascalCase regex from `\b[A-Z][a-zA-Z0-9]+[a-z][A-Za-z0-9]*\b` (which falsely matched every sentence-initial capitalized word like `Build` and `Decides`) to `\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b`, specified stripping ` ```...``` ` fenced code blocks before matching single-line inline `` `[^`\n]+` `` spans so triple-backtick fences do not invert inline backtick pairs (which previously broke matching `` `emit_event()` `` in `run-cisternal/SKILL.md`), added `"agent-asset"` to the hyphenated-modifier stopword list, recorded the concrete C4a Check (c) report-mode findings on the 4 shipped skills, and specified that `ManifestAssetSource` supports both top-level `[families]`/`[verbs]` and `[plugin.families]`/`[plugin.verbs]`.

### Cycle 8 Verification (Sequential Adversarial Challenge & Defense) — 2026-11-08
Claimed by: challenger_c8, defender_c8. Audit: `.praxia/docs/audits/261106_cycle8_audit.md`.
- Sequential Challenger 8 -> Defender 8 pass verified all resolutions from Cycles 5, 6, and 7 (`GAP-23` through `GAP-41`, `RISK-01`, `RISK-02`), all brief items (`A1`–`A16`, `R1`–`R5`), and all Phase 3 invariants against the worktree source code, yielding no new genuine specification gap. Status remains `draft` pending implementation and execution of the specified probes and test suite.
