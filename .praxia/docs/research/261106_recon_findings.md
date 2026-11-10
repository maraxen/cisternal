---
title: "Tool-Surface Triage: Phase 1 Reconnaissance Findings"
description: "Static code audits of assumptions A1-A9 and survey of existing precursors C0-C6 across cisternal, praxia, and bathos."
status: complete
task_id: 261106_tool-surface-triage
date: '261106'
author: worker_p1_recon
confidence: high
sources: "src/cisternal/assets/manifest.py, src/cisternal/export/claude.py, src/cisternal/telemetry/record.py, src/cisternal/assets/skill_schema.py, src/cisternal/adapters/base.py"
---
# Phase 1 Reconnaissance Findings: Tool Surface Triage Assumptions and Existing Tooling
Claimed by: worker_p1_recon (Phase 1), worker_docs_indexer (Docs Alignment)
Target: .praxia/docs/specs/261106_tool-surface-triage.md

---

## Executive Summary

This document presents the official Phase 1 Reconnaissance Deliverable for the Tool-Surface Triage specification (`.praxia/docs/specs/261106_tool-surface-triage.md`). It synthesizes direct code inspections, static analysis, and runtime artifact investigations conducted across `/home/marielle/projects/cisternal` (including worktree `.claude/worktrees/261106-agy-spec-cycles/`), `praxia`, and `bathos`.

### Key Findings
1. **Assumptions Audit (A1–A9)**:
   - **VERIFIED (4)**: A1 (hook export support), A2 (server-side telemetry scope), A3 (listing length advisory at 250 chars), A5 (skill listing budget: 1,536-char hard cap and 1% context pool).
   - **REFUTED (1)**: **A8** (error shape consistency across servers) is decisively refuted by `src/cisternal/adapters/base.py:278–388`. Adapters output heterogeneous error types (dict envelopes with differing keys, JSON-serialized strings, and unhandled exception re-raising).
   - **STILL-UNVERIFIED (4)**: 
     - **A4**: `session_context_audit.py` internals were verified in code at `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py` (lines 55–63, 76, 138–158, 193–213, 215–248, 447, 578–809), confirming it tallies `skills_by_plugin` and `other_mcp_by_server`, discards per-tool data for non-praxia servers, and matches only `praxia` CLI regex. However, because `praxia` is an external project not checked out in the current workspace, C0 cannot wrap or move it in-place without explicit vendoring or repo importation.
     - **A6**: Transcript record separation is observed in exploratory probes, but zero transcript parsing code exists within the `cisternal` repository.
     - **A7**: Behavioral adherence to additive context in hooks requires an empirical matched-session A/B test; no measurement harness currently exists.
     - **A9**: Subagents remain unmeasured in exploratory evidence (E1–E5); they operate headless with ~26k fewer tokens of standing context.
2. **Tooling Survey (C0–C6)**:
   - No component (C0–C6) is fully implemented in finished spec form.
   - However, mature precursors exist across the ecosystem: `session_context_audit.py` provides the JSONL transcript parser and synthetic test scaffold for C0; `src/cisternal/plugin/shared.py` provides shadow pruning logic for C1; `src/cisternal/assets/skill_schema.py` provides validation rules for C2 and C4; praxia's operational PreToolUse hook (`pretool-tool-rewrite.sh` and `tool_rewrite_decider.py`) provides the live CLI-to-MCP nudge engine for C5.

---

## 1. Status Summary of Assumptions A1–A9

| ID | Spec Description | Spec Tag | Verified Status | Primary Code Citation | Verdict Summary |
|---|---|---|---|---|---|
| **A1** | cisternal-exported plugins can ship PreToolUse hooks | verified: `assets/manifest.py:232`, `export/claude.py:30` | **VERIFIED** | `src/cisternal/assets/manifest.py:232–271`<br>`src/cisternal/export/claude.py:124, 137–143`<br>`src/cisternal/export/hooks.py:26–39` | Manifest parser captures `hook_specs` and Claude exporter groups any event name (including `PreToolUse`) into `hooks/hooks.json`. |
| **A2** | cisternal telemetry is server-side (`mcp.call_start/call_end/tool_error`, session_id, task_id); sees no CLI substitution and no unmet need | verified: `telemetry/record.py`, `otlp_exporter.py:37`, `pipeline.py:222` | **VERIFIED** | `src/cisternal/telemetry/record.py:8–43`<br>`src/cisternal/telemetry/otlp_exporter.py:37–39, 96–102, 132–165`<br>`src/cisternal/telemetry/pipeline.py:222–237` | Telemetry records are emitted exclusively within server-side MCP adapters. They observe no client Bash commands or skipped tool opportunities. |
| **A3** | `assets validate` already reports a listing-length advisory at 250 chars | verified: `skill_schema.py:26,137` | **VERIFIED** | `src/cisternal/assets/skill_schema.py:26, 145–159`<br>`src/cisternal/cli.py:1041–1047`<br>`tests/test_skill_schema.py:214–234` | Soft advisory triggers at `chars > 250` without failing validation. (Line 137 is the 1,536-char hard cap; advisory is at line 145). |
| **A4** | praxia `session_context_audit.py` already tallies `other_mcp_by_server`, `skills_by_plugin` | verified by name (`:447`); internals unread | **STILL-UNVERIFIED / CODE AUDITED** | `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py:55–63, 76, 138–158, 193–213, 215–248, 447, 578–809` | Code audit confirms tallies: discards per-tool breakdown for non-praxia servers and matches only `praxia` CLI. File is external to this workspace. |
| **A5** | Claude Code skill-listing budget is a shared pool (~1% of context) with per-entry cap 1,536 chars | verified only via `writing-skill-triggers` skill | **VERIFIED** | `src/cisternal/assets/skill_schema.py:23, 137–141`<br>`tests/test_skill_schema.py:236–247`<br>`.praxia/skills/writing-skill-triggers/SKILL.md:13–19`<br>`.praxia/docs/research/261017_skill-frontmatter-schema.md:36–45` | Hard cap (1,536 chars) enforced in cisternal schema; shared 1% budget derived from Claude Code 2.1.318 binary analysis. |
| **A6** | Transcript record types separate listing, hook, skill, user, tool-result text | verified by probe (`deferred_tools_*`, `hook_*`, etc.) | **STILL-UNVERIFIED IN CODE** | `.gemini/config/plugins/praxia/skills/triaging-harness-files/SKILL.md:320–327` | Probes were uncommitted ad-hoc scripts. Zero transcript-parsing code exists in the `cisternal` repository. |
| **A7** | A hook's additive context changes behaviour | UNVERIFIED: needs matched-session A/B | **STILL-UNVERIFIED** | None (no experimental harness in tree) | Spec correctly tags as unverified. No A/B test or adherence metrics exist. |
| **A8** | Error shapes are consistent across servers | UNVERIFIED | **REFUTED** | `src/cisternal/adapters/base.py:278–286, 314–318, 343–346, 364–368, 386–388` | Error return types and schemas diverge completely: dict with `error_code`, raw exception re-raising, JSON-serialized string, and `{error, message}`. |
| **A9** | Subagents do not change the picture | UNVERIFIED (excluded so far) | **STILL-UNVERIFIED** | `triaging-harness-files/SKILL.md:317` | Subagents excluded from E1–E5 exploratory data; operate headless with ~26k fewer tokens of standing context. |

---

## 2. Detailed Verification and Code Observations

### A1: PreToolUse Hook Export Support (VERIFIED)
- **Manifest Ingestion**: `src/cisternal/assets/manifest.py:232–271`:
  ```python
  def _load_hook_specs(
      plugin: dict[str, object],
      root: Path,
      warnings: list[str],
  ) -> tuple[HookSpecAsset, ...]:
      entries = plugin.get("hook_specs")
      if not isinstance(entries, list):
          return ()
      specs: list[HookSpecAsset] = []
      for entry in entries:
          ...
          event = str(entry.get("event") or "")
          matcher = str(entry.get("matcher") or "")
          script = str(entry.get("script") or "")
          ...
          specs.append(HookSpecAsset(event=event, matcher=matcher, script=script, ...))
      return tuple(specs)
  ```
- **Claude Export Dispatch**: `src/cisternal/export/claude.py:124, 137–143`:
  ```python
  hook_specs = hooks_for_surface(bundle.hook_specs, "claude")
  ...
  if hook_specs:
      hooks_root = build_claude_style_hooks(hook_specs)
      files[_HOOKS_JSON_PATH] = json.dumps(
          {"hooks": hooks_root},
          sort_keys=True,
          indent=2,
      )
  ```
- **Hook Formatting**: `src/cisternal/export/hooks.py:26–39`:
  ```python
  def build_claude_style_hooks(
      hook_specs: tuple[HookSpecAsset, ...],
  ) -> dict[str, list[dict[str, object]]]:
      events: dict[str, list[dict[str, object]]] = defaultdict(list)
      for spec in hook_specs:
          hook_cmd: dict[str, str] = {"type": "command", "command": spec.script}
          entry: dict[str, object] = {
              "matcher": spec.matcher,
              "hooks": [hook_cmd],
          }
          events[spec.event].append(entry)
      return dict(sorted(events.items()))
  ```
- **Conclusion**: Cisternal places no restrictions on hook event names. Supplying `event: "PreToolUse"` will correctly group entries under `"PreToolUse"` in `hooks/hooks.json`.

---

### A2: Server-Side Telemetry Scope and Env Precedence (VERIFIED)
- **Record Structure**: `src/cisternal/telemetry/record.py:8–43`:
  The `Record` dataclass captures:
  - `name`: event identifier (`'mcp.call_start'`, `'mcp.call_end'`, `'mcp.tool_error'`, `'cli.cmd_end'`).
  - `session_id`, `task_id`, `mcp_request_id`, `request_id`, `phase`.
  - `fields`: arbitrary dictionary containing `tool`, `duration_ms`, `error`, etc.
- **Span Pairing**: `src/cisternal/telemetry/otlp_exporter.py:37–39, 96–102, 132–165`:
  Pairs `mcp.call_start` and `mcp.call_end` into single OpenTelemetry spans; captures `mcp.tool_error`.
- **Environment Hierarchy**: `src/cisternal/telemetry/pipeline.py:222–237`:
  ```python
  def resolve_log_dir_from_env() -> Path:
      raw = (
          os.getenv("CISTERNAL_LOG_DIR")
          or os.getenv("BTH_LOG_DIR")
          or os.getenv("CTXP_LOG_DIR")
      )
      if raw is None:
          return Path.home() / ".cisternal" / "logs"
      return Path(raw)
  ```
- **Boundary**: All telemetry instrumentation lives inside server MCP adapters (`src/cisternal/adapters/base.py:157–208`). The server cannot observe client-side Bash commands (e.g. `bth sql`) or tools that the model considered but decided not to invoke.

---

### A3: Skill Listing-Length Advisory at 250 Characters (VERIFIED)
- **Constants**: `src/cisternal/assets/skill_schema.py:23, 26`:
  - `LISTING_CAP_CHARS = 1536` (hard validation error)
  - `LISTING_TARGET_CHARS = 250` (soft non-fatal advisory)
- **Advisory Function**: `src/cisternal/assets/skill_schema.py:145–159`:
  ```python
  def listing_advisory(skill: SkillAsset) -> str | None:
      chars = skill.listing_chars
      if chars <= LISTING_TARGET_CHARS or chars > LISTING_CAP_CHARS:
          return None
      return (
          f"skill {skill.name!r}: description + when_to_use is {chars} chars, "
          f"over the {LISTING_TARGET_CHARS}-char target; skills share one listing budget "
          "(see cisternal:writing-skill-triggers)"
      )
  ```
- **CLI Logging**: `src/cisternal/cli.py:1041–1047`:
  Invoked during `assets validate`: logs a warning via `_log.warning("cisternal.cli: advisory — %s", advisory)` but returns exit code 0.
- **Unit Test Parity**: `tests/test_skill_schema.py:214–234`:
  Explicitly asserts boundary condition: 250 characters returns `None`; 251 characters returns the advisory string.

---

### A4: `session_context_audit.py` Internals (STILL-UNVERIFIED / CODE AUDITED)
- **Script Location**: `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`.
- **Detailed Code Findings**:
  1. *Layer Types* (lines 55–63):
     `LAYER_TYPES = ("skill_listing", "instructions", "deferred_tools_delta", "agent_listing_delta", "mcp_instructions_delta", "hook_additional_context", "sandbox_instructions")` parses session attachment records.
  2. *Hardcoded CLI Regex* (line 76):
     ```python
     CLI_RE = re.compile(
         r"(?:^|[;&|(]|-l?c[ \t]+[\"'])[ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*(?:env[ \t]+(?:[A-Za-z_]\w*=\S*[ \t]+)*)?(?:(?:timeout|nice|time)[ \t]+(?:-\S+[ \t]+)*(?:\d\S*[ \t]+)?)?(?:\S*/)?praxia[ \t]+([a-z][a-z-]+)",
         re.M,
     )
     ```
     Matches only `praxia` CLI invocations; completely ignores `bth`, `rtk`, or generic bash commands.
  3. *Line-by-Line Reading* (lines 138–158):
     `_read_jsonl(path: Path)` provides robust line parsing, skipping malformed records.
  4. *Tool Tallying & Server-Only Aggregation* (lines 215–248):
     ```python
     def _tally_tool(s: dict, block: dict):
         name = block.get("name", "")
         if name.startswith("mcp__"):
             parts = name.split("__")
             server = parts[1] if len(parts) > 1 else ""
             if "praxia" in server:
                 s["praxia_mcp"][parts[-1]] += 1
             else:
                 s["other_mcp"][server or "unknown"] += 1
     ```
     **Critical Finding**: Non-praxia MCP tools (such as bathos tools) are aggregated strictly by *server name* (`other_mcp[server] += 1`). Individual tool names are discarded!
  5. *Skill Tallying* (lines 240–248):
     Tallies `Skill` tool calls by plugin prefix only (`sk.split(":", 1)[0]`).
  6. *Reporting* (line 447):
     Outputs `"skills_by_plugin": _sorted(skills)` and `"other_mcp_by_server": _sorted(other)`.
  7. *Synthetic Control Scaffold* (lines 578–809):
     Contains complete synthetic test suite (`_positive_control`, `_negative_control`, `_consistency_control`) generating in-memory JSONL sessions to verify tallies.
- **Architectural Implication**: C0 cannot simply "wrap" `session_context_audit.py` unchanged. It must be adapted to: (a) parse individual tool names for all MCP servers, (b) support generic CLI verbs like `bth`, (c) parse `ToolSearch` and `select:` provenance, and (d) be relocated or vendored into `cisternal` because `praxia` is an external project repository.

---

### A5: Skill-Listing Budget and Character Caps (VERIFIED)
- **1,536-Character Hard Cap in Cisternal**:
  `src/cisternal/assets/skill_schema.py:23, 137–141`:
  ```python
  if skill.listing_chars > LISTING_CAP_CHARS:
      out.append(
          f"skill {skill.name!r}: description + when_to_use is {skill.listing_chars} chars, "
          f"over the {LISTING_CAP_CHARS}-char listing cap (the excess is truncated)"
      )
  ```
  Verified by `tests/test_skill_schema.py:236–247` (fails when `listing_chars == 1537`).
- **Claude Code Shared Pool (~1% of Context)**:
  - Documented in `.praxia/skills/writing-skill-triggers/SKILL.md:13–19`:
    Derived from reverse-engineering Claude Code binary 2.1.318:
    - Listing pool = `context window × 4 × skillListingBudgetFraction` (default 0.01).
    - On a 200k context window, total pool = ~8,000 characters.
    - When budget is exceeded, lowest-priority / least-recently-invoked skills lose their description and collapse to bare names.
  - Documented in `.praxia/docs/research/261017_skill-frontmatter-schema.md:39–45`:
    Documents configuration knobs: `skillListingBudgetFraction`, env `SLASH_COMMAND_TOOL_CHAR_BUDGET`, and `skillOverrides: {"x": "name-only"}`.

---

### A6: Transcript Record Separation in Code (STILL-UNVERIFIED IN CODE)
- **Repo Code Status**: An exhaustive search of `cisternal` (`src/`, `tests/`, `.praxia/`) reveals **zero** transcript-parsing code.
- **Probe Lineage**: The exploratory probes (`deferred_tools_*`, `invoked_skills`, `skill_listing`) referenced in E1–E5 were executed via untracked, ad-hoc Python scripts.
- **Documentation**: Record formats are only referenced in audit documentation (`.gemini/config/plugins/praxia/skills/triaging-harness-files/SKILL.md:320–327`) and `session_context_audit.py:55–63`.
- **Verdict**: While the JSONL transcript schema separates these layer types in practice, the capability does not exist in any committed, reusable cisternal module.

---

### A7: Hook Additive Context Behavioral Adherence (STILL-UNVERIFIED)
- **Status**: The spec accurately tags this as UNVERIFIED.
- **Code Audit**: No test harness, metric, or transcript evaluator exists in the codebase to evaluate whether model behavior changes when `additionalContext` is emitted by a `PreToolUse` hook.
- **Requirement**: An empirical A/B test over matched sessions is strictly required before treating C5 nudging as validated.

---

### A8: Error Shapes Across MCP Servers (REFUTED)
Assumption A8 claims: *"Error shapes are consistent across servers"*.  
**Inspection of `src/cisternal/adapters/base.py:278–388` directly REFUTES this claim.**

Verbatim implementations of `shape_error`:
1. **`BathosAdapter.shape_error`** (lines 280–285):
   ```python
   return {
       "ok": False,
       "error_code": "INTERNAL",
       "error": str(exc),
       "resolution_hint": "",
   }
   ```
   *Returns*: A Python `dict` containing `ok`, `error_code`, `error`, and `resolution_hint`.
2. **`PassthroughAdapter.shape_error`** (lines 314–318):
   ```python
   def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
       raise exc
   ```
   *Returns*: Does NOT return an envelope; **re-raises the raw exception**.
3. **`ContemplexAdapter.shape_error`** (lines 343–346):
   ```python
   return contemplex_errors.err_envelope(
       contemplex_errors.ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}"
   )
   ```
   *Returns*: A structured object/dict produced by `contemplex.errors.err_envelope`.
4. **`XpeririAdapter.shape_error`** (lines 364–368):
   ```python
   payload: dict[str, Any] = {"ok": False, "error": str(exc)}
   payload.update(fields)
   return json.dumps(payload, sort_keys=True)
   ```
   *Returns*: A **JSON-serialized string (`str`)**, not a dict.
5. **`MyxcelAdapter.shape_error`** (lines 386–388):
   ```python
   return {"error": type(exc).__name__, "message": str(exc)}
   ```
   *Returns*: A Python `dict` with keys `error` and `message`. **Lacks `ok` and `error_code` entirely.**

#### Divergence Matrix
| Adapter | Return Type | Envelope Keys | Control Flow |
|---|---|---|---|
| `BathosAdapter` | `dict` | `ok`, `error_code`, `error`, `resolution_hint` | Returns dict |
| `PassthroughAdapter` | None | None | Re-raises exception |
| `ContemplexAdapter` | `dict` | `ok`, `error_code`, `message`, `details` | Returns dict |
| `XpeririAdapter` | `str` (JSON) | `ok`, `error`, [custom fields] | Returns JSON string |
| `MyxcelAdapter` | `dict` | `error`, `message` | Returns dict (missing `ok`) |

**Impact on Spec**: Components C0 (error detector) and C5 (nudge suppression on error) cannot rely on a naive `is_error` or `error_code` check. They must implement a multi-schema normalization layer that handles dicts, JSON strings, and protocol-level tool errors.

---

### A9: Subagent Invariance (STILL-UNVERIFIED)
- **Status**: UNVERIFIED.
- **Exploratory Data Omission**: Spec explicitly notes that Evidence E1–E5 was collected with "subagents excluded".
- **Standing Context Divergence**: `.gemini/config/plugins/praxia/skills/triaging-harness-files/SKILL.md:317` records median first-turn context of **61,440 tokens** for subagents versus **87,252 tokens** for main sessions (a ~26k token deficit).
- **Execution Divergence**: Subagents run non-interactively (headless), preventing user clarification prompts. Their tool discovery and fallback behaviors cannot be assumed to match main interactive sessions.

---

## 3. Comprehensive Survey of Existing Tooling (Components C0–C6)

### Component C0: Tracked Usage Counter
**Objective**: Parse Claude Code transcripts and cisternal JSONL logs to compute per-tool usage, `ToolSearch` provenance, and error-to-fallback metrics.

#### Existing Tooling
1. **`session_context_audit.py`**:
   - Location: `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`
   - Capabilities:
     - `_read_jsonl` (lines 138–158): Safe line-by-line streaming of JSONL transcripts.
     - `LAYER_TYPES` (lines 55–63): Categorizes transcript layers (`skill_listing`, `deferred_tools_delta`, etc.).
     - `_tally_tool` (lines 215–248): Groups MCP calls by server and skills by plugin.
     - `summarize_session` (lines 250–302): Calculates tokens, durations, and session counts.
     - Synthetic test harness (lines 578–809): Built-in positive, negative, and consistency controls using mock JSONL transcripts.
2. **Cisternal Telemetry Pipeline**:
   - `src/cisternal/telemetry/record.py:8–50`: Standardized `Record` model with `session_id`, `task_id`, `name`, and `fields`.
   - `src/cisternal/telemetry/exporter.py:48–80`: `JsonlExporter` supporting non-blocking rotating JSONL log writes.
   - `src/cisternal/telemetry/pipeline.py:220–228`: Environment variable hierarchy resolution.
3. **Bathos Server-Side Telemetry**:
   - `/home/marielle/projects/bathos/src/bathos/telemetry.py:35–50`: Server-side event emission into `events.<hostname>.<pid>.jsonl`.

#### Missing Capabilities
1. **Universal Per-Tool Tallying**: `session_context_audit.py:228` aggregates non-praxia MCP tools into `other_mcp[server]`. It must be refactored to parse `parts[-1]` for all servers.
2. **Generic CLI Extraction**: `CLI_RE` (line 76) matches only `praxia`. Must be generalized to extract `bth` and other CLI subcommands.
3. **`ToolSearch` Provenance Parser**: No logic currently parses `select:<tool>` vs keyword search, nor classifies whether the selected tool was previously mentioned in listings, hooks, user prompts, or assistant turns.
4. **Multi-Schema Error Detector**: No logic normalizes heterogeneous adapter error envelopes (as proven in A8).
5. **Error-to-Fallback Transition Metric**: No calculation measuring whether a same-verb CLI command occurs within $N$ turns following an MCP error.
6. **Subagent Inclusion**: Transcript reader currently excludes subagent logs; must aggregate them with distinct tagging.
7. **Telemetry Reconciliation**: Cross-join joining client transcript timestamps with server JSONL records.
8. **CLI Interface**: `cisternal usage` subcommand does not exist in `src/cisternal/cli.py`.
9. **Pre-Registration Sidecar**: Missing `.bth.toml` with `[outcomes]` and planted-never-called negative control.

---

### Component C1: Prune List
**Objective**: Generate keep / drop / enable-per-project recommendations by intersecting registered tools/plugins against C0 empirical usage.

#### Existing Tooling
1. **Configuration Registries**:
   - `~/.claude/settings.json`: Stores `enabledPlugins` and `mcpServers`.
   - `~/.claude.json`: Stores `mcpServers`, `pluginUsage`, `skillUsage`.
   - `/home/marielle/projects/bathos/src/bathos/export.py:81, 91–93` & `praxia-tools/.../locations.rs:47`: Robust cross-platform resolution of `~/.claude.json` paths.
2. **Shadow Pruning Infrastructure in Cisternal**:
   - `src/cisternal/plugin/shared.py:164–188`: `find_shadowed` and `handle_shadowed` locate unmanaged agents/skills duplicating plugin definitions.
   - `src/cisternal/cli.py:557, 695`: Exposed via `--prune-shadowed` CLI flag.
3. **Standing Stack Triage Protocol**:
   - `.gemini/config/plugins/praxia/skills/triaging-harness-files/SKILL.md:340–355`: Formal decision rubric: *"Before removing anything, read the usage in the same audit output (skills_by_plugin, other_mcp_by_server, agents)... Move rather than delete, and re-measure afterwards."*

#### Missing Capabilities
1. **Registry Parser**: A unified loader merging `settings.json`, `~/.claude.json`, and installed plugin manifests.
2. **Set Intersection Engine**: Logic computing `ActiveSurface = Registered ∩ Used(C0)` and `DeadSurface = Registered \ Used(C0)`.
3. **Recommendation Formatter**: Safe markdown/terminal output classifying tools into `keep`, `drop`, or `enable-per-project` (without performing destructive in-place edits).
4. **Negative Controls**: Tests asserting that unregistered historical servers in transcripts are omitted, and servers with $>0$ calls are never flagged for dropping.

---

### Component C2: Guidance-Coverage Lint
**Objective**: Invariant checker ensuring: (1) every tool family has a situation-matched skill trigger, and (2) every quoted tool in a skill exists in the registry (dangling-name check).

#### Existing Tooling
1. **Cisternal Validation Framework**:
   - `src/cisternal/cli.py:967–1047`: `validate_assets` parses `AssetBundle` and runs structural schema checks.
   - `src/cisternal/assets/bundle.py:99–174`: Rich asset representations (`SkillAsset`, `McpAsset`, `HookSpecAsset`).
   - `src/cisternal/assets/skill_schema.py:129–159`: Validation pipeline enforcing naming, character limits, and listing advisories.
2. **Dangling Reference Resolution**:
   - `/home/marielle/projects/praxia/scripts/context_audit/check_harness_files.py:34, 104–111`: Implements AST/regex extraction of markdown links and cross-validates against on-disk file targets, emitting `dangling` findings.

#### Missing Capabilities
1. **Quoted Tool Extractor**: Regex scanner extracting backticked tool names (e.g. `` `mcp__bathos__run_sql` `` or `` `run_sql` ``) from skill frontmatter and markdown bodies.
2. **Dangling-Tool Validator**: Cross-checker verifying that extracted tool names exist within `bundle.mcp_servers` or registered system tools.
3. **Tool Family Coverage Invariant**: Checker ensuring that every declared MCP tool belongs to a family covered by at least one skill's `when_to_use` trigger.
4. **Negative Controls**: Unit tests verifying validation failure when a trigger is deleted or a tool name is intentionally misspelled.

---

### Component C3: Skill Coverage Tooling
**Objective**: Evaluate guidance effectiveness by identifying skill opportunities (actions matching distinctive strings) and calculating loaded-before-action rates.

#### Existing Tooling
1. **Skill Invocation Extraction**:
   - `session_context_audit.py:240–248`: Detects `Skill` tool calls in assistant turns.
2. **Distinctive Strings Methodology**:
   - `.praxia/skills/writing-skill-triggers/SKILL.md:30–33`:
     *"2. Distinctive strings. The 2–5 terms only this skill would claim: commands, file names, error text, the user's own phrasing."*
3. **Distinctive Term Co-occurrence Matching**:
   - `/home/marielle/projects/praxia/scripts/eval/premise_valid_recon.py:219, 253, 263–270`: Implements term extraction, token set intersections, and action co-occurrence heuristics.

#### Missing Capabilities
1. **Distinctive String Catalog**: Structured dictionary mapping each skill to its signature file patterns, CLI subcommands, and error strings.
2. **Opportunity Scanner**: Transcript parser identifying turns where matching actions occurred (Bash command execution, tool calls, file edits).
3. **Temporal Ordering Evaluator**: Evaluator determining whether `Skill` load preceded the action ($T_{\text{skill}} < T_{\text{action}}$), occurred post-hoc ($T_{\text{skill}} > T_{\text{action}}$), or was missed entirely.
4. **Follow-Through Metric**: Evaluator measuring whether the tool recommended by the skill was actually called after loading.
5. **Negative Controls & Calibration**: Synthetic transcript tests with planted missed/late opportunities, plus hand-labelled precision calibration.

---

### Component C4: Progressive-Disclosure Honesty Check
**Objective**: Enforce accuracy across progressive disclosure tiers: Listing description ($\le 250$ chars) $\to$ `SKILL.md` body $\to$ `references/`.

#### Existing Tooling
1. **Listing Target & Advisory**:
   - `src/cisternal/assets/skill_schema.py:26, 145–159`: Enforces 250-character soft target and emits non-fatal advisory.
2. **Multi-Tier Asset Bundling**:
   - `src/cisternal/assets/bundle.py:110–125`: `SkillAsset.resources` parses and stores sibling `references/*.md`, `scripts/*`, and `assets/*`.
3. **Trigger Shortening Utility**:
   - `src/cisternal/assets/skillmod.py:1–60`: CLI utility migrating legacy `triggers` arrays into frontmatter `when_to_use`.
4. **Progressive Disclosure Architecture**:
   - `/home/marielle/projects/praxia/scripts/context_audit/standing_context_audit.py:14–30`: Codifies three loading tiers: `spawn` (always on), `session_only`, and `on_demand`.

#### Missing Capabilities
1. **Static Honesty Verifier** (in `assets validate`):
   - *(a) No Loss*: Verifies that all distinctive strings in the long description remain present in the short trigger or body.
   - *(b) No Overclaim*: Verifies that every technical noun or claim in `when_to_use` corresponds to a heading or text block in `SKILL.md` or `references/`.
   - *(c) Scope Header*: Verifies that the first 500 characters of `SKILL.md` explicitly state the skill's operational boundaries.
2. **Behavioral Non-Inferiority Harness**: Automated evaluation measuring short vs long trigger fire-rates against C3's frozen opportunity set.
3. **Negative Controls**: Test cases asserting failure when a distinctive term is stripped or an unbacked claim is introduced.

---

### Component C5: Verb-to-Tool Nudge Hook
**Objective**: PreToolUse hook intercepting CLI commands and injecting additive context nudging towards equivalent MCP tools, suppressed if that MCP tool errored earlier in the session.

#### Existing Tooling
1. **Hook Packaging & Export in Cisternal**:
   - `src/cisternal/assets/manifest.py:220–250`: Ingests `hook_specs` manifest declarations.
   - `src/cisternal/export/hooks.py:26–40`: Converts specs to Claude-style `hooks.json`.
   - `src/cisternal/export/claude.py:30–35`: Emits `hooks/hooks.json` in exported plugin packages.
2. **Operational PreToolUse Hook in Praxia**:
   - `/home/marielle/.gemini/config/plugins/praxia/hooks.json:1`: Configures PreToolUse interceptor.
   - `/home/marielle/.gemini/config/plugins/praxia/scripts/pretool-tool-rewrite.sh:1–119`: Bash wrapper passing tool call payload to Python decider.
   - `/home/marielle/.gemini/config/plugins/praxia/scripts/tool_rewrite_decider.py:63–67`:
     ```python
     SEARCH_REASON = (
         "praxia tool-rewrite: this grep is a {shape}-shaped where-is-X search. Prefer one praxia search "
         "call: {call} (MCP tool mcp__plugin_praxia_core__search, or mcp__praxia__search). For regex or "
         "grep-only flags, re-run with rg instead."
     )
     ```
     **Demonstrates a live, working CLI-to-MCP nudge engine!**
   - `/home/marielle/.gemini/config/plugins/praxia/scripts/emit_hook_output.sh:12–23`:
     ```bash
     emit_additional_context() {
         local ctx="${1:-}"
         case "${PRAXIA_HOOK_SURFACE:-claude}" in
             cursor) jq -n --arg m "$ctx" '{"agent_message": $m}' ;;
             *)      jq -n --arg c "$ctx" '{"additionalContext": $c}' ;;
         esac
     }
     ```
     Provides production-tested JSON emitter for `additionalContext`.
3. **Bathos Verb Mappings**:
   - `/home/marielle/projects/bathos/src/bathos/mcp.py`: Pairs `bth sql` with `run_sql_tool` (line 514), `bth campaign show` with `campaign_show_tool` (line 5176), and `bth validate-sidecar` with `validate_sidecar_tool` (line 4539).

#### Missing Capabilities
1. **Plugin Verb Table Schema**: A declarative table in `cisternal.toml` mapping CLI verbs to MCP tool identifiers (e.g. `bth sql -> mcp__bathos__run_sql`).
2. **Additive-Context Hook Script**: A standardized hook script for cisternal plugins executing purely additive nudges (without command blocking or rewriting).
3. **Session-Scoped Error Suppression**: State file or in-memory tracking in the hook script recording prior MCP errors in the session to suppress nudges after an MCP failure.
4. **Historical Error Classification**: Auditing and classifying the 57 historical bathos MCP errors (token limits / stdio pipe breaks vs schema validation errors).
5. **Negative Controls**: Automated tests confirming hook fires on `bth sql`, does not fire on `bth run` (long-running subprocess), and suppresses after an MCP error.
6. **Matched-Session A/B Protocol**: Rigorous experimental harness to test behavioral adherence (A7).

---

### Component C6: `triage-tool` Skill
**Objective**: Ship an on-demand skill in cisternal guiding agents through tool/skill auditing, C0 analysis, and C1 prune list application.

#### Existing Tooling
1. **Shipped Cisternal Skills**:
   - Inspected in `.praxia/skills/` and `src/cisternal/agent_plugin.json`: `run-cisternal`, `export-trust`, `developing-cisternal-tools`, `developing-cisternal-tools-workspace`, `customizing-tools`, and `writing-skill-triggers`.
2. **Reference Audit Skills**:
   - `.gemini/config/plugins/praxia/skills/triaging-harness-files/SKILL.md:340–355`: Triage protocol for standing context and uncalled plugins.
   - `.praxia/skills/writing-skill-triggers/SKILL.md:23–42`: Guidelines for concise trigger writing.

#### Missing Capabilities
1. **`triage-tool` Skill Definition**: `skills/triage-tool/SKILL.md` authored with trigger $\le 150$ characters.
2. **Modular References**: `references/` directory documenting:
   - `usage_counter.md` (interpreting C0 output).
   - `prune_guidelines.md` (evaluating C1 recommendations safely).
   - `progressive_disclosure.md` (evaluating C4 tiers).
3. **Non-Destructive Guardrail**: Explicit instruction that agents must present recommendations to the user and never modify `~/.claude/settings.json` directly.

---

## 4. Capability Matrix Across All Components

| Component | Target Artifact | Existing Precursors (with file:line) | Implemented Features | Missing Features |
|---|---|---|---|---|
| **C0** | `cisternal usage` | `session_context_audit.py:55–809`<br>`record.py:8–50`<br>`pipeline.py:220–228` | JSONL reading, session summary, token costs, synthetic test scaffold | All-server per-tool tallying, `ToolSearch` provenance, error detector, error-to-fallback metrics, subagents |
| **C1** | Prune List | `shared.py:164–188`<br>`cli.py:557,695`<br>`triaging-harness-files:340` | Shadow agent pruning, registration path discovery, triage heuristics | Registry intersection engine, keep/drop/project formatter, negative controls |
| **C2** | Guidance Lint | `cli.py:967–1047`<br>`skill_schema.py:129–159`<br>`check_harness_files.py:104` | Asset validation pipeline, character caps, link target checker | Quoted tool regex extractor, dangling-tool checker, family coverage check |
| **C3** | Skill Coverage | `session_context_audit.py:240`<br>`writing-skill-triggers:30`<br>`premise_valid_recon.py:219` | Skill invocation tallying, distinctive strings concept | Distinctive string catalog, opportunity scanner, temporal ordering check, follow-through tracker |
| **C4** | Honesty Check | `skill_schema.py:26,145`<br>`bundle.py:110–125`<br>`standing_context_audit.py:14` | 250-char soft advisory, multi-tier asset model (`references/`) | Static (no loss, no overclaim, scope header), behavioural non-inferiority harness |
| **C5** | Nudge Hook | `manifest.py:220–250`<br>`export/hooks.py:26–40`<br>`pretool-tool-rewrite.sh:1–119`<br>`tool_rewrite_decider.py:63`<br>`emit_hook_output.sh:12` | Hook export pipeline, live PreToolUse command interception, CLI-to-MCP reason generator, context emitter | Declarative verb table, additive-only script, session error suppression, error classification, A/B harness |
| **C6** | `triage-tool` | `agent_plugin.json:135`<br>`triaging-harness-files:340`<br>`writing-skill-triggers:23` | Asset bundling and export framework, reference triage documentation | `SKILL.md` ($\le 150$ chars trigger), sibling `references/`, non-destructive guardrails |

---

## 5. Architectural Recommendations for Subsequent Phases

Based on the empirical evidence gathered during Phase 1 reconnaissance, the following adjustments are recommended for Phase 2 (Background Research) and Phase 3 (Adversarial Spec-Coherence Cycles):

1. **Address Assumption A8 Refutation in C0 and C5**:
   - The spec currently assumes uniform error handling (`is_error` or `error_code`).
   - Because `base.py:278–388` proves that server error shapes range from dicts to strings to unhandled exceptions, C0 must implement a resilient multi-adapter error normalizer, and C5's error classification must inspect both transport-level errors and body envelopes.
2. **Reconcile Assumption A4 in Component C0**:
   - Because `session_context_audit.py` resides in `praxia` outside the `cisternal` repository, C0 cannot simply "move or wrap" it without either vendoring the code into `cisternal` or declaring `praxia` as an explicit dependency. Vendoring with attribution is recommended to preserve repo autonomy.
3. **Strict Sequencing of C5 Dependencies**:
   - C5 cannot be deployed until: (a) historical bathos errors are classified, (b) session-scoped error suppression is implemented, and (c) an A/B measurement protocol validates that additive context does not degrade task performance.
4. **Preserve Non-Destructive Guardrails across C1 and C6**:
   - In accordance with project safety rules, neither C1 nor C6 should ever execute automatic edits against `~/.claude/settings.json` or `~/.claude.json`. All recommendations must be output as user-applied review lists.
