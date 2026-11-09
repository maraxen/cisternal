---
title: "Tool-Surface Triage: Phase 3 Cycle 2 Adversarial Audit"
description: "Sequential adversarial audit of tool-surface triage spec cycle 2: 6 operational gaps resolved, achieving structural coherence."
status: complete
task_id: 261106_tool-surface-triage
date: '261106'
author: "challenger_c2 / defender_c2"
verdict: COHERENT
---
# Phase 3 Cycle 2 Adversarial Audit: Tool-Surface Triage Spec
Claimed by: challenger_c2 (Challenger), defender_c2 (Defender), worker_docs_indexer (Docs Alignment)

- **Target Spec**: `.praxia/docs/specs/261106_tool-surface-triage.md`
- **Audit Cycle**: Phase 3, Cycle 2 (Challenger Audit & Defender Resolution)
- **Author**: Adversarial Spec Challenger (`challenger_c2`) & Defender Subagent (`defender_c2`)
- **Status**: Audit & Resolution Complete — All 6 Gaps Conceded with Full Architectural Specifications
- **Date**: 2026-11-06

---

## Executive Summary & Overall Risk Assessment

**Overall Risk Assessment**: **MEDIUM** (Down from **HIGH** in Cycle 1)

The Cycle 1 revision of `.praxia/docs/specs/261106_tool-surface-triage.md` represents substantial architectural progress. All 13 gaps identified in Cycle 1 (**GAP-01 through GAP-13**) have been explicitly addressed:
- Assumption A8 is formally marked **REFUTED** with verbatim code citations.
- Pre-0 (Vendoring Core Parser) and Pre-1 (Adapter Error Normalization Pass) have been formally introduced into the prerequisite architecture and dependency graph.
- Falsification rigor has been upgraded with paired positive/negative controls ($N=5$ planted calls, $N=0$ uncalled tools, non-empty count assertions) for C0 and C3.
- Tool families are formalized via declarative schemas (`[families]` in manifests, `covers_families` in `SkillAsset`).
- C4 has been decomposed into C4a (Static Honesty Lint) and C4b (Behavioral Non-Inferiority Gate with pre-registered margin $\delta \le 0.05$).
- C5 incorporates an ephemeral on-disk error state ledger (`~/.cisternal/sessions/<session_id>/errors.jsonl`), Claude Code JSON payload formatting (`{"additionalContext": "..."}`), fail-open semantics, and temp-file streaming under the 128 KiB shell argument limit.
- Exploratory numbers E1–E5 have been reframed as Preliminary Motivating Probes.
- C2 invariant consistency with E3 has been preserved.

However, executing an empirical adversarial audit and testing against the physical runtime and codebase reveals **6 new or unaddressed operational gaps (GAP-14 through GAP-19)**. If left unaddressed, these issues will cause runtime crashes, dangling path build failures, or artificial scheduling blockages during implementation.

### Key Cycle 2 Vulnerabilities:
1. **Server-Side Session ID Propagation Hole (GAP-14, High)**: C5 specifies that `AdapterBase.normalize_error` appends to `~/.cisternal/sessions/<session_id>/errors.jsonl`. However, inspection of `src/cisternal/telemetry/context.py` confirms that `session_id_var` is never set anywhere in the cisternal codebase. In standard MCP stdio protocol, clients do not pass `session_id` in `CallToolRequest`. Attempting `Path.home() / ".cisternal" / "sessions" / session_id` will crash with `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'NoneType'` or write to `sessions/None/`. Meanwhile, Claude Code hook subshells receive the active `session_id` in their stdin JSON payload, resulting in a session key disconnect.
2. **Dangling External Filesystem Path in Pre-0 (GAP-15, High)**: Pre-0 instructs the builder to "vendor transcript-parsing engine from `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`". Physical inspection confirms `/home/marielle/projects/praxia` does not exist on disk (`projects` contains only `cisternal`). A build script attempting to copy or import from this path will immediately fail with `FileNotFoundError`. The spec must specify Pre-0 as a clean native implementation within `src/cisternal/usage/transcript.py` inspired by and attributed to praxia's design.
3. **Artificial Serialization Bottleneck in Build Order (GAP-16, Medium)**: The revised build graph places C6 (`triage-tool` skill) and C5 (CLI nudge hook) strictly downstream of C4b (Behavioral Non-Inferiority Gate). C4b requires LLM inference over a frozen situation set with Wilson score intervals and API access. In contrast, C6 only documents C0/C1 usage, and C5 only depends on Pre-1, C0, and the error ledger. Serializing `C4b -> C6 -> C5` creates an unnecessary development roadblock.
4. **Ambiguous Token Extraction and Vanishing Baseline in C4a (GAP-17, Medium)**: C4a Check (b) requires that "candidate topic tokens" extracted from listing descriptions match section headings or code blocks, but provides no token extraction grammar (risking catastrophic false positives on natural language words). In Check (a), an author compressing a description can simultaneously delete distinctive strings from the working tree frontmatter, bypassing static loss detection unless `--baseline-ref` is made mandatory in CI.
5. **Client/Server Join Disconnect in C0 Metrics Extraction (GAP-18, Medium)**: C0 defines its source of truth as client transcripts joined with server JSONL logs. However, client transcripts lack server `mcp_request_id`, and server logs lack `tool_use_id`. In reality, all core metrics (tool calls, CLI invocations, ToolSearch provenance, error-to-fallback transitions) reside entirely within client transcripts. Claiming a mandatory join creates unnecessary implementation friction.
6. **Manifest Discovery and Naming Ambiguity (GAP-19, Low/Medium)**: C2 specifies declaring `[families]` in `cisternal.toml`. However, `src/cisternal/cli.py` hardcodes default manifest paths to `.praxia/manifest.toml` (lines 517, 809), and `cisternal.toml` is not recognized by `ManifestAssetSource`. Declarative schemas should be anchored in `.praxia/manifest.toml` (and plugin manifests).

---

## 1. Cycle 1 Gap Resolution Verification Matrix (GAP-01 to GAP-13)

| Gap ID | Issue Summary | Spec Section | Cycle 1 Resolution in Revised Spec | Verification Verdict | Notes & Observations |
|---|---|---|---|---|---|
| **GAP-01** | Cross-repo import failure of `session_context_audit.py`. | Pre-0, line 40 | Added Pre-0 to vendor core parser into `src/cisternal/usage/transcript.py` with attribution, removing `CLI_RE` and adding generic parser. | **PARTIALLY RESOLVED / CAVEAT** | Architectural concept resolved, but physical source path `~/projects/praxia` does not exist on disk (see GAP-15). |
| **GAP-02** | Assumption A8 REFUTED; heterogeneous adapter error shapes. | A8 (line 35), Pre-1 (line 48) | Marked A8 as **REFUTED** with verbatim code citations to `base.py:278–388`. Inserted Pre-1 `normalize_error` contract on `AdapterBase`. | **VERIFIED RESOLVED** | Verbatim citations verified against `src/cisternal/adapters/base.py`. Contract cleanly specifies dataclass and adapter mappings. |
| **GAP-03** | Stateless hook subshell cannot query prior MCP errors. | C5 (line 160) | Defined ephemeral session error state ledger at `~/.cisternal/sessions/<session_id>/errors.jsonl`. | **VERIFIED RESOLVED (SPEC)** | Architectural mechanism resolved, though server-side session ID propagation needs clarification (see GAP-14). |
| **GAP-04** | Single-sided negative controls susceptible to silent masking. | C0 (line 75), C3 (line 131) | Added paired positive ($N=5$) and negative ($N=0$) controls, plus `len(counts) >= 2` non-empty assertions. | **VERIFIED RESOLVED** | Completely prevents false-pass bugs from empty dictionary returns. |
| **GAP-05** | C4 check (a) compares against non-existent "long form" description. | C4a (line 139) | Check (a) redefined as containment against `SKILL.md` body, with optional `--baseline-ref` for git history. | **VERIFIED RESOLVED** | Cleanly grounds check (a) in current files while supporting versioned CI baselines. |
| **GAP-06** | C4 checks (b) and (c) lack deterministic static algorithms. | C4a (line 142) | Check (b) matches tokens against headings/code blocks; check (c) enforces `## Scope` within first 50 lines / 2,000 chars. | **VERIFIED RESOLVED** | Deterministic AST rules replace vague semantic checks. Token extraction grammar refined in GAP-17. |
| **GAP-07** | "Tool family" undefined and unmodelled in cisternal assets. | C2 (line 98) | Defined declarative `[families]` manifest schema and `covers_families: list[str]` frontmatter in `SkillAsset`. | **VERIFIED RESOLVED** | Fully grounds C2 invariant in static data models without breaking E3. |
| **GAP-08** | C1 prune list destroys hook-only and skill-only plugins. | C1 (line 83) | Added active asset whitelisting: plugins with `hook_specs`, `commands`, or `skills` cannot be marked `drop`. | **VERIFIED RESOLVED** | Protects non-MCP developer guardrails from accidental deletion. |
| **GAP-09** | C1 lacks lookback window and project-split decision rules. | C1 (line 86) | Established $N \ge 20$ sessions (or 14-day) lookback window; defined $\ge 80\%$ workspace threshold for `enable-per-project`. | **VERIFIED RESOLVED** | Prevents volatile recommendations on sparse sample sizes. |
| **GAP-10** | Exploratory numbers E1–E5 cited as ground truth. | Lines 17, 20–23, 247 | Renamed section to "Preliminary Motivating Probes"; rephrased "E3 falsifies", "the 57 errors", and scope rationales. | **VERIFIED RESOLVED** | Epistemic humility cleanly restored throughout document. |
| **GAP-11** | C5 hook risks shell argument overflow and schema failure. | C5 (line 167) | Specified Claude Code JSON (`{"additionalContext": "..."}`), fail-open `|| exit 0`, and temp-file streaming under 128 KiB. | **VERIFIED RESOLVED** | Respects Linux `MAX_ARG_STRLEN` and host execution contracts. |
| **GAP-12** | C4 behavioral gate lacks non-inferiority margin $\delta$. | C4b (line 153) | Pre-registered $\delta \le 0.05$ (5 percentage points) at 95% confidence using Wilson score confidence intervals. | **VERIFIED RESOLVED** | Statistical decision threshold is unambiguous and falsifiable. |
| **GAP-13** | Subagent headless execution disparity unmeasured in C0. | A9 (line 36), C0 (line 71) | A9 marked UNVERIFIED; C0 mandates metric stratification by `session_type: "main_interactive" | "subagent_headless"`. | **VERIFIED RESOLVED** | Prevents conflating interactive human workflows with headless subagent execution. |

---

## 2. Detailed Adversarial Challenges (Cycle 2 Findings)

### GAP-14 (Critical/High): Server-Side Session ID Propagation Hole for C5 Ephemeral Error Ledger

- **Spec Section**: Component C5 (lines 160–166) & Pre-1 (lines 48–65).
- **Observation**:
  Spec line 160 states:
  > *Ephemeral Session Error State Ledger: Location: `~/.cisternal/sessions/<session_id>/errors.jsonl`. Appended by: Cisternal server telemetry / `AdapterBase.normalize_error` upon any failed MCP tool execution.*
- **Code Fact**:
  1. Direct inspection of `src/cisternal/telemetry/context.py` reveals:
     ```python
     session_id_var: ContextVar[str | None] = ContextVar("cisternal.session_id", default=None)
     ```
     `session_id_var` defaults to `None`. A codebase-wide search confirms that `session_id_var.set(...)` is **never called anywhere in the entire `cisternal` repository**.
  2. In the Model Context Protocol (MCP) JSON-RPC 2.0 specification over `stdio`, the client sends `CallToolRequest` containing only `{"name": str, "arguments": dict}`. Standard MCP requests **do not carry a `session_id` parameter**.
  3. Running `Path.home() / ".cisternal" / "sessions" / None / "errors.jsonl"` in Python immediately raises:
     ```
     TypeError: unsupported operand type(s) for /: 'PosixPath' and 'NoneType'
     ```
  4. In contrast, client-side hook subshells invoked by Claude Code natively receive `.session_id` in their stdin JSON payload (e.g. `SESSION_ID=$(jq -r '.session_id')` in `posttool-mcp-telemetry.sh:65`).
- **Attack Scenario**:
  An MCP tool fails. `AdapterBase.normalize_error` is invoked inside the server process to append the failure to the error ledger. It attempts to resolve `<session_id>`. Because `session_id_var.get()` is `None`, the path construction crashes with `TypeError` or defaults to `sessions/None/errors.jsonl`. Meanwhile, the PreToolUse hook runs on a subsequent `bth sql` command, extracts the valid session ID (`SESSION_ID="e6f4234c-..."`), inspects `~/.cisternal/sessions/e6f4234c-.../errors.jsonl`, finds nothing, and emits an erroneous nudge. The error suppression invariant fails.
- **Blast Radius**:
  C5 error suppression is broken; agents entering fallback cascades will receive repeated, invalid nudges towards broken MCP tools, inducing cognitive loops.
- **Mitigation**:
  Clarify error ledger authorship and session binding:
  1. **Option A (Client-Side Recording via Hook)**: Let the existing client-side `PostToolUse` hook (which natively receives `session_id` and the tool outcome in its stdin payload) append to `~/.cisternal/sessions/<session_id>/errors.jsonl`.
  2. **Option B (Server Fallback Ledger)**: If appended by `AdapterBase`, specify that if `session_id` is `None`, the record is written to a workspace-scoped active ledger (e.g. `<workspace>/.cisternal/session_errors.jsonl` or `~/.cisternal/sessions/active_errors.jsonl`).
- **Defender Rebuttal / Answer**:
  **Conceded**. Challenger's observation is physically verified: MCP over standard `stdio` JSON-RPC 2.0 does not transmit client session IDs, and `session_id_var` in `src/cisternal/telemetry/context.py` defaults to `None` without any mutator calls. Attempting `Path.home() / ".cisternal" / "sessions" / None / "errors.jsonl"` unconditionally raises `TypeError`.
  
  We adopt a hybrid, highly resilient two-tier architecture:
  1. **Primary Author (Client-Side Hook)**: The client-side `PostToolUse` hook (`posttool-mcp-telemetry.sh` or dedicated `posttool-error-ledger.sh`) runs directly inside the Claude Code host environment, where `INPUT.session_id` is guaranteed to be present on stdin. Whenever `tool_result.is_error == true` (or error payload is detected), the hook appends the structured JSONL record directly to `~/.cisternal/sessions/<session_id>/errors.jsonl`.
  2. **Secondary Fallback (Server-Side Adapter)**: In `AdapterBase.normalize_error` (or `pipeline.py`), `session_id` is resolved defensively: `session_id_str = session_id_var.get() or "default"`. When running over stdio without an explicit session ID, errors append to `~/.cisternal/sessions/default/errors.jsonl`.
  3. **Consumer Dual Lookup in PreToolUse Hook**: The PreToolUse nudge hook checks both `~/.cisternal/sessions/<session_id>/errors.jsonl` (session-exact) and `~/.cisternal/sessions/default/errors.jsonl` (filtering records with timestamps within the last 15 minutes, or `mtime <= 900s`). If an error matching the verb's MCP tool or family is found in either ledger, the nudge is suppressed and the hook exits 0 immediately.
- **Disposition**: **CONCEDED — HYBRID CLIENT POSTTOOLUSE WRITER + SERVER DEFAULT FALLBACK SPECIFIED**

---

### GAP-15 (High): Dangling External Filesystem Path in Pre-0 Vendoring

- **Spec Section**: Build Prerequisites: Pre-0 (lines 40–47).
- **Observation**:
  Spec line 41 states:
  > *Formally vendor the transcript-parsing engine from `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py` into `src/cisternal/usage/transcript.py`.*
- **Code Fact**:
  Empirical inspection of the local filesystem reveals:
  ```bash
  python3 -c "import os; print(os.listdir('/home/marielle/projects'))"
  # Output: ['cisternal']
  ```
  `/home/marielle/projects/praxia` does not exist on disk.
- **Attack Scenario**:
  An implementation engineer or autonomous agent starts building Pre-0. It attempts to read or copy `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`. The build script or tool call fails immediately with `FileNotFoundError: [Errno 2] No such file or directory`.
- **Blast Radius**:
  Pre-0 is the root prerequisite in the build sequence (`Pre-0 -> Pre-1 -> C0 ...`). A hard path failure stalls the entire triage development pipeline.
- **Mitigation**:
  Update Pre-0 to specify a **clean native implementation** in `src/cisternal/usage/transcript.py` adhering to the specified interfaces (streaming JSONL reader, `(binary, subcommand)` parser, layer categorization), with architectural attribution to Praxia `session_context_audit.py`, rather than assuming an on-disk source file copy.
- **Defender Rebuttal / Answer**:
  **Conceded**. Physical verification confirms `/home/marielle/projects/praxia` is not mounted or cloned in the active development workspace (`/home/marielle/projects` contains only `cisternal`). Specifying a build step that copies or vendors from an unresolvable local path will cause automated build pipelines and CI workflows to fail with `FileNotFoundError`.
  
  Pre-0 is therefore redefined as a **native cisternal implementation** in `src/cisternal/usage/transcript.py`:
  1. **Attribution**: A module docstring explicitly records architectural design attribution to Praxia's `session_context_audit.py` (2026).
  2. **Self-Contained Interfaces**: Implements the streaming Claude Code transcript JSONL reader, event dataclasses (`TranscriptEvent`), generic `parse_cli_command` tokenizer, and session stratification logic (`main_interactive` vs `subagent_headless`) directly within cisternal with zero cross-repository filesystem dependencies.
- **Disposition**: **CONCEDED — REDEFINED AS NATIVE CISTERNAL IMPLEMENTATION WITH ARCHITECTURAL ATTRIBUTION**

---

### GAP-16 (Medium): Artificial Serialization Bottleneck in Build Order (`C4b -> C6 -> C5`)

- **Spec Section**: Order and Dependency Graph (lines 189–245).
- **Observation**:
  Spec line 244 specifies:
  > *Build sequence: `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C4b -> C6 -> C5`*
- **Logic Flaw**:
  1. Component C6 is the `triage-tool` skill (`src/cisternal/assets/skills/triage-tool/SKILL.md`). It provides interactive instructions for running `cisternal usage` (C0) and `cisternal prune-list` (C1). It has **zero functional dependency** on C4b (a statistical non-inferiority evaluation of compressed descriptions using Wilson score intervals).
  2. Component C5 is the CLI-to-MCP nudge hook. It depends on Pre-1 (error normalization), C0 (error detection), and the error state ledger. It has **zero functional dependency** on C4b.
  3. C4b requires executing an LLM across a frozen opportunity set (`frozen_situations.jsonl`) with API keys and network access. In sandboxed or offline CI environments, C4b cannot run synchronously.
- **Attack Scenario**:
  An engineering team completes C0, C1, C2, and C4a. They want to ship the `triage-tool` skill and the nudge hook to help developers prune unused tools. The build pipeline blocks because C4b (statistical non-inferiority evaluation) requires running an LLM evaluation harness that is unrunnable in sandbox CI.
- **Blast Radius**:
  Delays deployment of useful triage skills and nudge hooks behind an experimental evaluation gate.
- **Mitigation**:
  Uncouple C6 and C5 from C4b. Decouple the dependency graph:
  ```
  Pre-0 -> Pre-1 -> C0 -> (C1, C2)
  (C1, C0) -> C6 (triage-tool skill)
  (Pre-1, C0) -> C5 (nudge hook)
  (C2) -> (C4a, C3) -> C4b (offline evaluation gate)
  ```
- **Defender Rebuttal / Answer**:
  **Conceded**. Challenger is entirely correct regarding dependency coupling. Component C6 (`triage-tool` skill) only requires documentation of `cisternal usage` (C0) and `cisternal prune-list` (C1). Component C5 (nudge hook) depends on Pre-1, C0, and the dual-tier session error ledger. Neither C5 nor C6 has any functional, data, or runtime dependency on C4b. Furthermore, C4b is an empirical behavioral evaluation requiring external LLM API access across a frozen opportunity set, which cannot execute within hermetic offline CI runners.
  
  The build order is uncoupled:
  1. Mainline release sequence: `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C6 -> C5`.
  2. Component C4b is branched off C3 as a **non-blocking, asynchronous evaluation track**.
  Operational tools (C0, C1, C2, C3, C4a, C5, C6) can build, run lint/unit tests, and ship immediately without blocking on C4b empirical LLM runs.
- **Disposition**: **CONCEDED — BUILD SEQUENCE UNCOUPLED; C4b BRANCHED AS NON-BLOCKING EVALUATION TRACK**

---

### GAP-17 (Medium): Ambiguous Token Extraction and Vanishing Baseline in C4a Static Honesty Lint

- **Spec Section**: Component C4a: Static Honesty Lint (lines 137–150).
- **Observation**:
  - Spec line 142 states: *Check (b) (No Overclaim): Candidate topic tokens extracted from the listing description must match at least one section heading (`#`, `##`, `###`) or code block identifier in `SKILL.md` or a file in `references/`.*
  - Spec line 139 states: *Check (a) (No Loss / Containment): Every string declared in frontmatter `distinctive_strings` must appear in the listing description (`when_to_use` / `description`) OR in the Markdown body of `SKILL.md`.*
- **Logic Flaw**:
  1. In Check (b), the algorithm for extracting "candidate topic tokens" is unspecified. If words like "handling", "session", "support", or "tools" are treated as topic tokens, valid skills will fail linting because natural language prose contains words that are not Markdown headings. Conversely, if only backticked tokens are checked, unbackticked overclaims are missed.
  2. In Check (a), if an author shortens a description and removes a distinctive capability, they can simultaneously delete that token from `distinctive_strings` in the working tree file. The check compares current `distinctive_strings` against current body text, trivially passing without detecting the capability loss unless `--baseline-ref` is provided.
- **Attack Scenario**:
  A developer runs `cisternal assets validate`. Check (b) raises 15 false-positive warnings because words in `description` are not exact Markdown headings. The developer gets frustrated and disables Check (b). In another pull request, a developer compresses a description from 800 to 200 chars and removes 3 trigger strings from frontmatter; Check (a) reports PASS because it only validates the remaining strings.
- **Mitigation**:
  1. For Check (b): Formally define "candidate topic tokens" as **capitalized domain terms, declared keywords, or backticked identifiers** (excluding standard English stopwords).
  2. For Check (a): Mandate `--baseline-ref HEAD~1` (or `origin/main`) in CI pull-request validation pipelines to enforce regression detection against git history.
- **Defender Rebuttal / Answer**:
  **Conceded**. Challenger has pinpointed critical specification ambiguities in C4a that would lead to false-positive lint noise in Check (b) and undetectable silent capability erosion in Check (a).
  
  The specification is updated with formal AST and CI semantics:
  1. **Deterministic Grammar for Check (b) (No Overclaim)**:
     Candidate topic tokens extracted from the listing description (`when_to_use` / `description`) are strictly defined as:
     - **Backticked terms**: Anything enclosed in markdown backticks (e.g. `` `run_sql` ``, `` `errors.jsonl` ``).
     - **PascalCase / camelCase terms**: Identifiers matching `\b[A-Z][a-zA-Z0-9]+[a-z][A-Za-z0-9]*\b` or `\b[a-z]+[A-Z][a-zA-Z0-9]*\b`.
     - **Hyphenated / Underscored verb-noun expressions**: Tokens matching `\b[a-z0-9]+(?:[-_][a-z0-9]+)+\b` (e.g. `prune-list`, `distinctive_strings`).
     - **Explicitly declared keywords**: Any token in `distinctive_strings` or `covers_families`.
     - Standard English prose words, conjunctions, prepositions, and generic English stopwords (e.g., "for", "with", "when", "use", "audit", "tools", "support", "handling") are explicitly filtered out.
     - Every candidate topic token must match at least one heading (`#`, `##`, `###`) or code block identifier in `SKILL.md` or a file in `references/`.
  2. **Mandatory `--baseline-ref` for CI in Check (a) (No Loss / Containment)**:
     - In CI pull-request pipelines, `cisternal assets validate --baseline-ref origin/main` (or `HEAD~1`) is **mandatory**.
     - Check (a) extracts `distinctive_strings` from the baseline git commit: any baseline string that was deleted from frontmatter during description compression must remain present in the `SKILL.md` body or `references/`. Deleting a distinctive capability from frontmatter without retaining it in the body causes a hard CI failure.
     - For standalone local runs without git access, Check (a) validates current frontmatter `distinctive_strings` containment against the markdown body.
- **Disposition**: **CONCEDED — DETERMINISTIC TOKEN GRAMMAR DEFINED; MANDATORY CI BASELINE REF SPECIFIED**

---

### GAP-18 (Medium): Client/Server Join Disconnect in C0 Core Metrics Extraction

- **Spec Section**: Component C0 (lines 69–80) & Problem (line 15).
- **Observation**:
  Spec line 70 states:
  > *Source of Truth: Claude Code JSONL transcripts (client) + Cisternal JSONL logs (`~/.cisternal/logs/` or `CISTERNAL_LOG_DIR`, server) + Pre-1 normalized error stream.*
- **Empirical Code Fact**:
  1. In Claude Code client transcripts, tool calls contain Anthropic API IDs (`id: "toolu_01..."`), tool names, input arguments, and `tool_result` blocks with `is_error` and content.
  2. In cisternal server logs, events contain `mcp_request_id` (JSON-RPC ID), `name: "mcp.call_end"`, and `fields: {"duration_ms": float}`.
  3. Client transcripts do not record `mcp_request_id`; server logs do not record Anthropic `tool_use_id`.
  4. Core triage metrics:
     - MCP call tallies $\to$ 100% available in client transcripts.
     - CLI command invocations (`bth sql`) $\to$ 100% available in client transcripts (server has 0% visibility).
     - ToolSearch provenance (`select:<name>`) $\to$ 100% available in client transcripts (server has 0% visibility).
     - Error-to-fallback transitions (CLI within 3 turns of error) $\to$ 100% available in client transcripts.
- **Attack Scenario**:
  A developer implementing C0 attempts to build a synchronous relational join between client transcripts and server JSONL logs. They discover that no common join key exists (`tool_use_id` vs `mcp_request_id`, with `session_id=None` on server). The developer stalls C0 implementation attempting to design an approximate timestamp-matching engine.
- **Mitigation**:
  Clarify that **client transcripts are the primary, self-sufficient source of truth** for tool tallies, CLI substitution, and transition metrics. Server JSONL logs serve as an optional enrichment source for server-side duration (`duration_ms`) and low-level internal stack traces.
- **Defender Rebuttal / Answer**:
  **Conceded**. Challenger correctly notes that Claude Code client JSONL transcripts and cisternal server JSONL logs do not share a common correlation ID (`tool_use_id` vs `mcp_request_id`), and that server logs have zero visibility into CLI commands (`bth sql`), `ToolSearch` query strings (`select:<name>`), or error-to-fallback transition timings. Treating server logs as a mandatory synchronous join partner for C0 creates an artificial implementation blocker.
  
  The source-of-truth hierarchy is clarified:
  1. **Primary, Self-Sufficient Source of Truth (Client Transcripts)**: All primary triage metrics—MCP tool call counts, CLI command invocations, ToolSearch provenance, error-to-fallback transitions, and session stratification—are extracted directly and self-sufficiently from Claude Code client transcripts. C0 can compute and output certified usage benchmarks without reading any server logs.
  2. **Secondary Enrichment (Server JSONL Logs)**: Cisternal server telemetry logs (`~/.cisternal/logs/` or `CISTERNAL_LOG_DIR`) serve strictly as an optional enrichment pass. When available, server logs are joined heuristically by `(tool_name, timestamp +/- 5s)` to attach low-level `duration_ms` and internal exception tracebacks. If server logs are absent, unreadable, or unmatched, C0 emits `duration_ms: null` and proceeds normally.
- **Disposition**: **CONCEDED — CLIENT TRANSCRIPTS ESTABLISHED AS SELF-SUFFICIENT PRIMARY SOURCE OF TRUTH**

---

### GAP-19 (Low/Medium): Manifest Discovery Inconsistency (`cisternal.toml` vs `.praxia/manifest.toml`)

- **Spec Section**: Component C2 (lines 98–109).
- **Observation**:
  Spec line 99 states:
  > *Declarative `[families]` manifest in `cisternal.toml` (and plugin manifests)*
- **Code Fact**:
  Inspection of `src/cisternal/cli.py:517, 809` shows that `Path(".praxia/manifest.toml")` is the hardcoded default manifest path throughout cisternal CLI commands. Furthermore, `ManifestAssetSource` in `src/cisternal/assets/manifest.py:35` is designed to load Praxia-style `.praxia/manifest.toml`.
  `cisternal.toml` does not exist in the repository and is not recognized by any asset loading class.
- **Attack Scenario**:
  A plugin author adds `[families]` to a new file named `cisternal.toml`. They run `cisternal assets validate`. Cisternal reads `.praxia/manifest.toml`, completely ignores `cisternal.toml`, and fails with a missing tool family error.
- **Mitigation**:
  Standardize the primary declaration path: specify `[families]` in `.praxia/manifest.toml` (and `plugin.json` for marketplace plugins), while adding support for `cisternal.toml` as an optional project-level override.
- **Defender Rebuttal / Answer**:
  **Conceded**. Code inspection of `src/cisternal/cli.py:517, 809` confirms that cisternal's CLI discovery logic hardcodes `Path(".praxia/manifest.toml")` as the default manifest location, and `ManifestAssetSource` in `src/cisternal/assets/manifest.py:35` parses that file. A file named `cisternal.toml` does not exist and is unparsed by existing loaders. Directing plugin authors to declare `[families]` solely in `cisternal.toml` creates a schema discovery failure.
  
  The declaration schema is standardized to align with existing discovery conventions:
  1. **Primary Manifest**: `[families]` is declared in `.praxia/manifest.toml` for local workspace tools, and in `manifest.toml` or `plugin.json` for marketplace plugins.
  2. **Schema Definition**:
     ```toml
     [families]
     bathos_query = ["mcp__bathos__run_sql", "mcp__bathos__get_run", "mcp__bathos__find_runs"]
     bathos_lineage = ["mcp__bathos__lineage_prov", "mcp__bathos__cite_run"]
     contemplex_brainstorm = ["brainstorm_start", "brainstorm_reply", "brainstorm_finalize"]
     ```
  3. **Discovery Integration**: `ManifestAssetSource` parses `[families]` directly during manifest ingestion. CLI commands accept `--manifest <path>` (defaulting to `.praxia/manifest.toml`), with optional support for `cisternal.toml` if present as an explicit project-level override.
- **Disposition**: **CONCEDED — ANCHORED IN .praxia/manifest.toml AND PLUGIN MANIFESTS WITH DEFAULT CLI DISCOVERY**

---

## 3. Stress Test Results & Empirical Proofs

### Test 1: Testing Python PosixPath with None Session ID
```python
from pathlib import Path

session_id = None
try:
    p = Path.home() / ".cisternal" / "sessions" / session_id / "errors.jsonl"
except TypeError as e:
    print(f"FAILED: {e}")
```
- **Result**: `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'NoneType'`
- **Implication**: Proves GAP-14: without guaranteed non-None session resolution, path construction in `errors.jsonl` raises an unhandled exception.

### Test 2: Verifying Absence of Local Praxia Repository
```python
import os

projects = os.listdir("/home/marielle/projects")
print("Projects on disk:", projects)
print("Praxia exists:", os.path.exists("/home/marielle/projects/praxia"))
```
- **Result**: `Projects on disk: ['cisternal']`, `Praxia exists: False`
- **Implication**: Proves GAP-15: vendoring from `/home/marielle/projects/praxia/...` is a dangling path reference.

### Test 3: Verifying Adapter Error Heterogeneity (Refutation of A8)
```python
# Direct line inspection of src/cisternal/adapters/base.py
# Lines 280-285: BathosAdapter returns dict with ok, error_code, error
# Lines 314-318: PassthroughAdapter executes 'raise exc'
# Lines 343-346: ContemplexAdapter returns err_envelope
# Lines 364-368: XpeririAdapter returns json.dumps(payload)
# Lines 386-388: MyxcelAdapter returns {"error": ..., "message": ...} (no ok)
```
- **Result**: Verbatim code confirms 5 distinct return types and shapes.
- **Implication**: Re-confirms GAP-02 resolution is necessary and Pre-1 normalization contract is verified.

---

## 4. Epistemic Alignment & Invariant Checks

1. **Epistemic Framing (E1–E5)**:
   - Evaluated throughout lines 17–24, 69, 97, 186, 247.
   - Exploratory disclaimer is prominent and consistently maintained.
   - Categorical phrases ("falsifies", "the 57 errors", "discovery is not the bottleneck") have been successfully replaced with parametric design rationales.
2. **C2 Invariant Consistency with E3**:
   - Evaluated in lines 21, 97, and 108.
   - C2 requires tool family coverage (`covers_families`) and checks for dangling names of quoted tools.
   - Individual tool names are **not** required to appear in skills, maintaining 100% conceptual and operational consistency with probe E3 (where 50.2% of tool loads occurred from bare stubs).

---

## 5. Summary of Recommended Actions for Cycle 2 Defender

To achieve full spec coherence and immediate implementability, the Defender should incorporate the following targeted refinements:

1. **Resolve GAP-14 (Session ID Transport in C5)**:
   Specify that `~/.cisternal/sessions/<session_id>/errors.jsonl` is appended by the client-side `PostToolUse` hook (which natively receives `session_id` in Claude Code JSON), or define a fallback to `<workspace>/.cisternal/errors.jsonl` when `session_id` is None in server adapters.
2. **Resolve GAP-15 (Native Implementation for Pre-0)**:
   Update Pre-0 to specify a clean native implementation of `src/cisternal/usage/transcript.py` within cisternal, attributing the architectural design to Praxia `session_context_audit.py`, removing dangling local path assumptions.
3. **Resolve GAP-16 (Decouple Build Graph)**:
   Uncouple C6 (`triage-tool` skill) and C5 (nudge hook) from C4b (behavioral non-inferiority gate), allowing operational tooling to ship without waiting for statistical LLM evaluations.
4. **Resolve GAP-17 (Clarify C4a Token Extraction Grammar)**:
   Define topic tokens for Check (b) as capitalized domain terms, declared keywords, or backticked identifiers; mandate `--baseline-ref` for CI pull requests.
5. **Resolve GAP-18 (Client Transcript Self-Sufficiency in C0)**:
   Explicitly declare client session transcripts as the primary source of truth for tool counts and transitions, with server logs as secondary duration enrichment.
6. **Resolve GAP-19 (Anchor Manifest Schema in `.praxia/manifest.toml`)**:
   Standardize `[families]` manifest declarations in `.praxia/manifest.toml` and `plugin.json` to match cisternal's existing CLI discovery defaults.

---

## 6. Defender Resolution & Architectural Specifications (Cycle 2)

### 6.1 Overview of Cycle 2 Concessions

The Defender concessions for Cycle 2 address all six operational vulnerabilities (**GAP-14 through GAP-19**) identified by the Challenger. Each gap is conceded with full technical rigor and accompanied by an explicit, implementable architectural specification:

1. **GAP-14**: Resolves the stdio MCP session ID disconnect by delegating primary error-ledger appending to the client-side `PostToolUse` hook (which receives `session_id` natively from Claude Code), with a server-side defensive fallback to `~/.cisternal/sessions/default/errors.jsonl`.
2. **GAP-15**: Eliminates the dangling `/home/marielle/projects/praxia` filesystem path by defining Pre-0 as a clean, native cisternal implementation in `src/cisternal/usage/transcript.py` with formal Praxia design attribution.
3. **GAP-16**: Decouples the serialized build order, allowing operational components (`C6` skill and `C5` nudge hook) to ship immediately via static linting and unit testing, while branching `C4b` (LLM-based behavioral non-inferiority gate) into an asynchronous, non-blocking evaluation track.
4. **GAP-17**: Establishes a deterministic token extraction grammar (backticked terms, PascalCase, hyphenated/underscored verbs) for C4a Check (b), and mandates `--baseline-ref` in CI for Check (a) to prevent silent capability deletion during description compression.
5. **GAP-18**: Establishes client session transcripts as the self-contained primary source of truth for all triage metrics (tool call tallies, CLI invocations, ToolSearch provenance, error-to-fallback transitions, and session stratification), relegating server logs to optional duration enrichment.
6. **GAP-19**: Anchors declarative `[families]` schemas in `.praxia/manifest.toml` and plugin manifests (`manifest.toml` / `plugin.json`), aligning directly with cisternal's existing CLI discovery logic.

---

### 6.2 Detailed Architectural Specifications for Cycle 2 Gaps

#### 6.2.1 Resolution of GAP-14: Two-Tier Ephemeral Error Ledger Architecture

To guarantee that the C5 PreToolUse nudge hook reliably suppresses nudges after an MCP error without crashing or encountering empty session directories:

1. **Primary Recording Path (Client-Side `PostToolUse` Hook)**:
   - File: `src/cisternal/export/hooks/posttool_mcp_error.sh` (or integrated into `posttool-mcp-telemetry.sh`).
   - Trigger: Claude Code executes this hook subshell following every tool execution.
   - Input Payload: The hook reads JSON from stdin containing `.session_id`, `.tool_name`, and `.tool_result`.
   - Logic:
     ```bash
     INPUT=$(cat)
     SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""')
     IS_ERROR=$(echo "$INPUT" | jq -r 'if .tool_result.is_error == true or (.tool_result.content[]? | select(.type=="text" and (.text | test("(^ERROR|^Exception|Error:)")))) then "true" else "false" end')
     TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
     
     if [ "$IS_ERROR" = "true" ] && [ -n "$SESSION_ID" ]; then
       LEDGER_DIR="$HOME/.cisternal/sessions/$SESSION_ID"
       mkdir -p "$LEDGER_DIR"
       jq -n \
         --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
         --arg sess "$SESSION_ID" \
         --arg tool "$TOOL_NAME" \
         --arg src "client_posttool_hook" \
         '{timestamp: $ts, session_id: $sess, tool_name: $tool, source: $src}' \
         >> "$LEDGER_DIR/errors.jsonl"
     fi
     ```

2. **Secondary Fallback Path (Server-Side Adapter)**:
   - In `src/cisternal/adapters/base.py` (`AdapterBase.normalize_error`):
     ```python
     from pathlib import Path
     import json
     from datetime import datetime, timezone
     from cisternal.telemetry.context import session_id_var

     def record_error_to_ledger(tool_name: str, family: str, error: NormalizedError) -> None:
         session_id = session_id_var.get()
         session_folder = session_id if session_id else "default"
         ledger_path = Path.home() / ".cisternal" / "sessions" / session_folder / "errors.jsonl"
         try:
             ledger_path.parent.mkdir(parents=True, exist_ok=True)
             record = {
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "session_id": session_id,
                 "tool_name": tool_name,
                 "family": family,
                 "error_code": error.error_code,
                 "message": error.error_message,
                 "source": "server_adapter"
             }
             with open(ledger_path, "a", encoding="utf-8") as f:
                 f.write(json.dumps(record) + "\n")
         except Exception:
             pass  # Fail-open: telemetry logging must never crash server
     ```

3. **PreToolUse Consumer Dual Lookup**:
   - The `PreToolUse` hook checks both:
     - `~/.cisternal/sessions/$SESSION_ID/errors.jsonl` (session-exact).
     - `~/.cisternal/sessions/default/errors.jsonl` (evaluating entries within a 15-minute sliding window).
   - If a matching error is found in either ledger, the hook exits 0 with zero output, strictly suppressing the nudge.

---

#### 6.2.2 Resolution of GAP-15: Native Implementation for Pre-0 (`src/cisternal/usage/transcript.py`)

Pre-0 is restructured to eliminate all external filesystem dependencies:
1. **Module Location**: `src/cisternal/usage/transcript.py`.
2. **Attribution**: Formal header documentation:
   ```python
   # Copyright (c) 2026 Cisternal Contributors
   # Architectural design attributed to Praxia session_context_audit.py (2026).
   # Native cisternal re-implementation under project license.
   ```
3. **Core Interface Components**:
   - `TranscriptEvent`: Dataclass capturing timestamp, turn index, event type (`tool_use`, `tool_result`, `user_message`, `assistant_message`, `skill_invoked`), tool name, inputs, error status.
   - `parse_cli_command(cmd: str) -> tuple[str, str]`: Generic CLI tokenizer stripping prefix proxies (`rtk`, `just`, `env`) and returning `(binary_name, subcommand)`.
   - `stream_transcript_events(path: Path) -> Iterator[TranscriptEvent]`: Streaming memory-efficient JSONL parser processing transcripts of arbitrary size.
   - `stratify_session_type(events: list[TranscriptEvent]) -> str`: Evaluates initial prompt context and turns to label session as `"main_interactive"` or `"subagent_headless"`.

---

#### 6.2.3 Resolution of GAP-16: Uncoupled Build Sequence and Non-Blocking C4b Evaluation Track

The build sequence and dependency graph are updated to decouple empirical evaluations from operational tool deployments:

```
               +-------------------------------------------------+
               | Pre-0: Native transcript parsing core           |
               |        (src/cisternal/usage/transcript.py)      |
               +-------------------------------------------------+
                                       │
               +-----------------------▼-------------------------+
               | Pre-1: Adapter Error Shape Normalization Pass   |
               |        (src/cisternal/adapters/base.py)         |
               +-------------------------------------------------+
                                       │
               +-----------------------▼-------------------------+
               |           C0: Tracked Usage Counter             |
               |   (Paired Positive/Negative Controls, Strat)    |
               +-------------------------------------------------+
                                       │
                      ┌────────────────┴────────────────┐
                      ▼                                 ▼
    +-----------------------------------+ +-----------------------------------+
    |          C1: Prune List           | |     C2: Guidance-Coverage Lint    |
    |  (Whitelist Hook & Skill Plugins) | |   (Tool Family Schema + Dangling) |
    |      (Lookback Window N >= 20)    | +-----------------------------------+
    +-----------------------------------+                 │
                      │                 ┌─────────────────┴─────────────────┐
                      │                 ▼                                   ▼
                      │ +-------------------------------+   +-------------------------------+
                      │ |  C4a: Static Honesty Lint     |   |   C3: Skill Coverage Tooling  |
                      │ | (No loss, no overclaim, scope)|   |  (Mines Frozen Situation Set) |
                      │ +-------------------------------+   +-------------------------------+
                      │                 │                                   │
                      └────────┬────────┴───────────────────┐               │
                               ▼                            ▼               ▼
               +-------------------------------+ +-------------------------------+ +---------------------------------------+
               |  C6: triage-tool Skill Build  | |   C5: Verb-to-Tool Nudge Hook | | [Non-Blocking Evaluation Track]       |
               | (Trigger <= 150c, References) | | (Two-Tier Session Error State)| | C4b: Behavioral Non-Inferior Gate    |
               +-------------------------------+ +-------------------------------+ | (Fire-rate on Frozen Set, δ <= 0.05)  |
                                                                                   +---------------------------------------+
```

- **Operational Mainline**: `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C6 -> C5` (all fully executable in hermetic CI with unit and lint tests).
- **Evaluation Track**: `C3 -> C4b` runs asynchronously in benchmark environments with LLM inference credentials, preventing blocking of core release artifacts.

---

#### 6.2.4 Resolution of GAP-17: Deterministic AST Grammar and Mandatory CI Baseline Comparison for C4a

To make C4a completely deterministic and eliminate both false-positive warnings and silent capability deletions:

1. **Deterministic Candidate Topic Token Grammar for Check (b)**:
   A candidate topic token extracted from `when_to_use` / `description` must match one of four explicit syntactic categories:
   - **Backticked Literals**: Enclosed in backticks: `` `([a-zA-Z0-9_\-\.:]+)` ``.
   - **PascalCase / camelCase Identifiers**: `\b[A-Z][a-zA-Z0-9]+[a-z][A-Za-z0-9]*\b` or `\b[a-z]+[A-Z][a-zA-Z0-9]*\b`.
   - **Hyphenated / Underscored Verb-Noun Expressions**: `\b[a-z0-9]+(?:[-_][a-z0-9]+)+\b`.
   - **Explicitly Declared Keywords**: Identifiers declared in `distinctive_strings` or `covers_families`.
   
   *Stopwords Filter*: An explicit set of common English words and generic verbs ("audit", "session", "support", "tools", "handling", "using", "when", "with", "from", "into", "every", "should") are excluded from being treated as candidate topic tokens.
   
   *Containment Target*: Every extracted candidate token must match at least one heading (`#`, `##`, `###`) or code identifier in `SKILL.md` or a referenced file in `references/`.

2. **Mandatory CI Baseline Comparison for Check (a)**:
   - In CI pull-request validation: `cisternal assets validate --baseline-ref origin/main`.
   - The validator loads `distinctive_strings` from the baseline commit.
   - If any distinctive string was deleted from the frontmatter during compression, it MUST exist in the Markdown body or `references/` of the revised skill. If a distinctive string is absent from both the compressed frontmatter and the body, the lint fails with `CAPABILITY_EROSION_DETECTED`.

---

#### 6.2.5 Resolution of GAP-18: Client Transcripts as Self-Contained Primary Source of Truth

The data dependency for C0 is formally updated:
1. **Primary Source of Truth**: Claude Code JSONL client transcripts (`~/.claude/transcripts/` or specified directory). Client transcripts contain 100% of the information necessary for triage:
   - Tool calls and input arguments.
   - Direct execution outcomes (`tool_result.is_error`).
   - CLI command invocations (`Bash` tool executions with parsed binaries).
   - `ToolSearch` query provenance (`select:<exact_name>` vs keyword).
   - Turn-by-turn fallback transitions (CLI calls within 3 turns of an MCP error).
   - Subagent delegation and execution modes.
2. **Secondary Enrichment**: Cisternal server JSONL telemetry logs (`~/.cisternal/logs/`).
   - Joined heuristically on `(tool_name, timestamp +/- 5s)`.
   - Provides server-side execution duration (`duration_ms`) and adapter exception details.
   - Non-blocking: If server logs are missing or timestamps do not correlate, C0 outputs all primary metrics with `duration_ms: null`.

---

#### 6.2.6 Resolution of GAP-19: Standardized Family Schemas in `.praxia/manifest.toml`

1. **Manifest Location**:
   Declarative `[families]` are anchored in `.praxia/manifest.toml` for repository workspace assets, and in `manifest.toml` / `plugin.json` for installed plugins.
2. **Schema Definition**:
   ```toml
   [families]
   bathos_query = ["mcp__bathos__run_sql", "mcp__bathos__get_run", "mcp__bathos__find_runs"]
   bathos_lineage = ["mcp__bathos__lineage_prov", "mcp__bathos__cite_run"]
   contemplex_brainstorm = ["brainstorm_start", "brainstorm_reply", "brainstorm_finalize"]
   ```
3. **Discovery Consistency**:
   - `ManifestAssetSource` in `src/cisternal/assets/manifest.py` loads `[families]` by default from `Path(".praxia/manifest.toml")`.
   - The CLI `--manifest` argument accepts custom paths, with fallback to `cisternal.toml` if present.

---

### 6.3 Cycle 2 Gap Resolution Verification Matrix (GAP-14 to GAP-19)

| Gap ID | Issue Summary | Spec Section | Cycle 2 Defender Resolution | Verification Verdict |
|---|---|---|---|---|
| **GAP-14** | Server `session_id_var` is None; path construction crashes on stdio MCP. | C5 (line 160), Pre-1 | Dual-tier error ledger: client-side `PostToolUse` hook writes using `INPUT.session_id`; server fallback writes to `sessions/default/errors.jsonl`. PreToolUse hook performs dual lookup. | **CONCEDED & RESOLVED** |
| **GAP-15** | Dangling path `/home/marielle/projects/praxia` causes build failure. | Pre-0 (line 40) | Pre-0 redefined as clean native cisternal implementation in `src/cisternal/usage/transcript.py` with formal Praxia architectural attribution. | **CONCEDED & RESOLVED** |
| **GAP-16** | Build order blocks C6 and C5 behind offline LLM evaluation gate C4b. | Build Order (line 244) | Build sequence decoupled to `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C6 -> C5`; C4b established as non-blocking asynchronous evaluation track. | **CONCEDED & RESOLVED** |
| **GAP-17** | C4a lacks token grammar; Check (a) vulnerable to simultaneous deletion. | C4a (lines 139–145) | Deterministic AST token grammar defined (backticked, PascalCase, hyphenated verbs, stopwords excluded); `--baseline-ref` mandated for CI PR checks. | **CONCEDED & RESOLVED** |
| **GAP-18** | Client transcripts and server logs lack join keys in C0. | C0 (line 70) | Client transcripts established as self-contained primary source of truth; server logs relegated to optional duration enrichment. | **CONCEDED & RESOLVED** |
| **GAP-19** | `cisternal.toml` not discovered by `ManifestAssetSource`. | C2 (line 99) | Standardized `[families]` in `.praxia/manifest.toml` and plugin manifests, matching cisternal's CLI discovery defaults. | **CONCEDED & RESOLVED** |

---

### 6.4 Verification of Spec Coherence Post-Cycle 2

With all 6 Cycle 2 gaps conceded and their concrete architectural solutions integrated into `.praxia/docs/specs/261106_tool-surface-triage.md`:
1. Every component C0–C6 possesses an explicit, verified **source of truth**, a concrete **delivery mechanism**, and a robust **negative control**.
2. All prerequisites (Pre-0 and Pre-1) are fully specified as native implementations within cisternal, with zero unresolvable filesystem paths.
3. The build order strictly respects architectural and environment constraints, separating fast, hermetic CI steps from offline LLM evaluation gates.
4. Exploratory numbers E1–E5 remain strictly framed as motivating probes.
5. C2 invariant consistency with probe E3 is fully preserved.

The revised specification has achieved complete internal coherence, implementability, and epistemic integrity.

