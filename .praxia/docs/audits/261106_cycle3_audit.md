---
title: "Tool-Surface Triage: Phase 3 Cycle 3 Adversarial Audit"
description: "Sequential adversarial audit of tool-surface triage spec cycle 3: resolution of dependency ordering, A8 client hook consistency, and sandbox boundary clarity."
status: complete
task_id: 261106_tool-surface-triage
date: '261106'
author: "challenger_c3 / defender_c3"
verdict: COHERENT
---
# Phase 3 Cycle 3 Adversarial Audit: Tool-Surface Triage Spec
Claimed by: challenger_c3 (Challenger), defender_c3 (Defender)

- **Target Spec**: `.praxia/docs/specs/261106_tool-surface-triage.md`
- **Audit Cycle**: Phase 3, Cycle 3 (Challenger Adversarial Audit & Defender Resolution)
- **Author**: Adversarial Spec Challenger (`challenger_c3`) & Defender Subagent (`defender_c3`)
- **Status**: Audit & Resolution Complete — All 3 Gaps Conceded with Full Architectural Specifications (GAP-20, GAP-21, GAP-22)
- **Date**: 2026-11-06

---

## Executive Summary & Overall Risk Assessment

**Overall Risk Assessment**: **HIGH** (Elevated from Cycle 2 due to acute runtime blind-spots and dependency paradoxes)

Following the Cycle 2 revisions documented in `.praxia/docs/audits/261106_cycle2_audit.md` and committed to `.praxia/docs/specs/261106_tool-surface-triage.md`, the specification has made commendable progress in establishing client-first telemetry (GAP-18), AST token grammars (GAP-17), and declarative family manifests (GAP-19).

However, an empirical adversarial audit testing the post-Cycle-2 specification against the cisternal codebase (`src/cisternal/adapters/base.py`), the FastMCP/Claude Code JSON-RPC runtime protocol, and the physical filesystem environment reveals **three critical, unimplementable flaws and contract regressions**:

1. **Dependency Ordering Paradox & Missing Error-Path Mainline Link (GAP-20, Critical/High)**:
   In attempting to uncouple C4b in Cycle 2 (GAP-16), the ASCII dependency graph and mainline sequence were restructured to place `C4a` in parallel with `C3` (`(C4a, C3)`), with an incoming arrow from `C2 -> C4a`. However, `C4a` Check (a) and Check (b) explicitly evaluate `distinctive_strings`—a schema attribute introduced and defined solely in `C3`! Implementing `C4a` before or in parallel with `C3` results in missing attributes and validation crashes, directly violating the explicit architectural constraint: **"C4 needs C3"**. Furthermore, the mainline build sequence (`... -> C6 -> C5`) fails to link `C5` to `Pre-1` and the E4 error-path classification, obscuring the primary functional prerequisite for `C5`'s error-suppression invariant.

2. **A8 Envelope Blindness in Client-Side PostToolUse Hook & Missing Plugin Verb Schema (GAP-21, Critical/High)**:
   In Cycle 2, `GAP-14` attempted to resolve server-side `session_id` absence by delegating primary error-ledger recording to a client-side `PostToolUse` hook reading `tool_result.is_error == true` or crude regex (`^ERROR|^Exception|Error:`). However, empirical inspection of `src/cisternal/adapters/base.py:278–388` reveals that **4 of 5 adapters (`BathosAdapter`, `ContemplexAdapter`, `XpeririAdapter`, `MyxcelAdapter`) catch exceptions and return structured JSON dictionaries or strings (`{"ok": false, ...}` or `{"error": ...}`)**. Under the Model Context Protocol, returning a payload results in wire-level `is_error: false`! A client hook inspecting only `tool_result.is_error` or text regex will be completely blind to all adapter-shaped errors, leaving the error ledger permanently empty and causing C5 to emit destructive cognitive-loop nudges. Furthermore, the spec omits a formal `[verbs]` schema linking CLI command invocations (`bth sql`) to MCP tool names (`mcp__bathos__run_sql`), rendering `PreToolUse` correlation unimplementable.

3. **Inaccurate Sandbox Mount Attribution in GAP-15 / Pre-0 (GAP-22, Medium)**:
   The Cycle 2 audit and spec changelog asserted that `/home/marielle/projects/praxia` "does not exist on disk". In reality, Phase 1 Recon audited the exact internals of `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py:55–63, 76, 138–158` on the host machine. The Cycle 2 agent observed an empty directory because it executed within a workspace container sandbox where `/home/marielle/projects` only mounted `cisternal`. Claiming the external repository "does not exist on disk" creates epistemic confusion; the spec and audit must accurately state that `praxia` is an external sibling repository outside `cisternal`'s package boundary and is unmounted in sandboxed and CI environments.

---

## 1. Prior Cycle Resolution Verification Matrix (GAP-14 through GAP-19)

| Gap ID | Issue Summary | Spec Section | Cycle 2 Resolution | Cycle 3 Empirical Audit Verdict | Notes & Findings |
|---|---|---|---|---|---|
| **GAP-14** | Server-side `session_id_var` unset on stdio MCP; ledger path `TypeError`. | Pre-1 (line 68), C5 (line 174) | Assigned primary ledger writing to client-side `PostToolUse` hook; added server fallback to `default/errors.jsonl`. | **PARTIALLY RESOLVED / FLAWED IN CLIENT HOOK** | Server fallback safely prevents `TypeError`. However, client hook check `tool_result.is_error == true` is completely blind to in-band A8 adapter error envelopes (see **GAP-21**). |
| **GAP-15** | Dangling path `/home/marielle/projects/praxia` in Pre-0 vendoring. | Pre-0 (line 42) | Redefined Pre-0 as a clean native cisternal implementation with Praxia architectural attribution. | **RESOLVED IN IMPLEMENTATION / CAVEAT IN SPEC LANGUAGE** | Eliminating external filesystem imports is sound. However, the rationale inaccurately claimed praxia does not exist on disk due to sandbox mount confusion (see **GAP-22**). |
| **GAP-16** | Artificial build serialization bottleneck (`C4b -> C6 -> C5`). | Order & Graph (lines 207–251) | Uncoupled C4b as an asynchronous evaluation track; updated mainline sequence to `(C4a, C3) -> C6 -> C5`. | **PARTIALLY RESOLVED / INTRODUCED ORDERING REGRESSION** | Uncoupling C4b is correct. However, placing `C4a` in parallel with `C3` breaks the explicit dependency "C4 needs C3", and mainline omits `Pre-1 -> C5` (see **GAP-20**). |
| **GAP-17** | Ambiguous token extraction & vanishing baseline in C4a. | C4a (lines 146–158) | Defined deterministic AST token extraction grammar; mandated `--baseline-ref origin/main` in CI. | **VERIFIED RESOLVED** | Deterministic regex grammar for backticks, PascalCase, hyphenated identifiers, and git baseline comparison eliminates ambiguity and capability erosion. |
| **GAP-18** | Client/server relational join disconnect in C0 metrics. | C0 (lines 74–77) | Established client JSONL transcripts as self-sufficient primary source of truth; server logs relegated to optional enrichment. | **VERIFIED RESOLVED** | Cleanly removes join dependency; allows C0 to compute certified metrics directly from client transcripts. |
| **GAP-19** | Manifest discovery inconsistency (`cisternal.toml` vs `.praxia/manifest.toml`). | C2 (lines 104–116) | Standardized declarative `[families]` manifest in `.praxia/manifest.toml` and plugin manifests. | **VERIFIED RESOLVED** | Directly aligns with `src/cisternal/cli.py:517, 809` and `ManifestAssetSource` default discovery paths. |

---

## 2. Detailed Challenger Findings for Cycle 3

### GAP-20 (Critical/High): Dependency Ordering Violation (`C3 -> C4a` Paradox) & Missing Error-Path Mainline Link

- **Spec Section**: Order and Dependency Graph (lines 207–251) & Component C4a (lines 146–158).
- **Subsystem**: Build Architecture, Static Lints, CI Pipeline.
- **Severity**: **Critical / High** (Build sequence failure; violated prompt constraint).

#### Concrete Failure Scenario / Code Inspection Evidence:
1. In the target specification, the ASCII dependency graph (lines 225–237) and mainline build sequence (line 249) state:
   ```
                      ┌─────────────────┴─────────────────┐
                      ▼                                   ▼
    +-------------------------------+   +-------------------------------+
    |  C4a: Static Honesty Lint     |   |   C3: Skill Coverage Tooling  |
    | (No loss, no overclaim, scope)|   |  (Mines Frozen Situation Set) |
    +-------------------------------+   +-------------------------------+
   ```
   Mainline sequence: `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C6 -> C5`
   `C4a` is depicted branching in parallel with `C3`, with an incoming arrow solely from `C2 -> C4a`.
2. Inspecting the component definitions in the specification exposes a direct circular dependency:
   - Component **C4a** Check (a) (lines 146–148) explicitly mandates:
     > *"Every string declared in frontmatter `distinctive_strings` must appear in the listing description (`when_to_use` / `description`) OR in the Markdown body of `SKILL.md`."*
   - Component **C4a** Check (b) (line 155) explicitly mandates:
     > *"Candidate topic tokens are strictly defined as: ... 4. Explicitly declared keywords: Tokens listed in `distinctive_strings` or `covers_families`."*
   - However, `distinctive_strings` is **introduced and defined in Component C3** (lines 124–131):
     ```python
     distinctive_strings: list[str] = Field(
         default_factory=list,
         min_length=1,
         max_length=5,
         description="2 to 5 specific domain tokens or CLI triggers uniquely identifying opportunities for this skill"
     )
     ```
3. If an engineer or automated pipeline builds `C4a` in parallel with `C3` (or before `C3`), `SkillAsset` in `src/cisternal/assets/skill_schema.py` does not possess the `distinctive_strings` attribute!
   Executing `cisternal assets validate` with C4a checks will raise `AttributeError: 'SkillAsset' object has no attribute 'distinctive_strings'` or fail Pydantic model validation.
4. This directly violates the core task requirement established in the Authoritative Request (`ORIGINAL_REQUEST.md:25`):
   > *"Build order respects dependencies (C4 needs C3; C5 needs the E4 error-path fix)."*
   `C4` in its entirety (both `C4a` static lint and `C4b` behavioral evaluation) strictly depends on `C3` (`C3 -> C4a` and `C3 -> C4b`).
5. Furthermore, the mainline build sequence `... -> (C4a, C3) -> C6 -> C5` presents an incorrect operational dependency:
   - `C5` is the Verb-to-Tool Nudge Hook. Its core invariant is that nudges must be suppressed when an MCP tool errors (E4).
   - `C5` functionally depends on `Pre-1` (error shape normalization), `C0` (error-to-fallback transition tracking), `C2` (declarative family schema), and the two-tier error ledger.
   - `C5` has **zero functional dependency on C6** (a user-facing interactive triage skill). Chaining `C6 -> C5` in the mainline sequence obscures the foundational requirement that **"C5 needs the E4 error-path fix"** (`Pre-1 -> C5`).

#### Impact on Implementation / Operational Failure:
- Attempting to run static validation for C4a in CI before C3 schema attributes are merged causes build crashes.
- The build graph misrepresents system prerequisites, allowing C5 to be deployed without ensuring Pre-1 error normalization is active.

#### Challenger Proposed Requirement for Defender:
1. **Enforce `C3 -> C4a` in ASCII Graph and Mainline Sequence**:
   - Re-route the dependency graph so that `C2` leads to `C3`, and `C3` leads to `C4a`:
     `C2 -> C3 -> C4a`
   - Explicitly update the mainline build sequence to:
     `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> C3 -> C4a -> C6`
     with `(Pre-1, C0, C2) -> C5` clearly rooted in the error-path fix.
2. **Explicitly Document `Pre-1 -> C5` Dependency**:
   - In both the ASCII diagram and Component C5 section, explicitly annotate that `C5` requires the Pre-1 error normalization pass and error ledger before deployment.

---

### GAP-21 (Critical/High): A8 Envelope Blindness in Client-Side PostToolUse Hook & Missing Plugin Verb Schema

- **Spec Section**: Component C5: Verb-to-Tool Nudge Hook (lines 172–199) & Pre-1 (lines 50–70).
- **Subsystem**: Client Hooks, MCP Error Ledger, Telemetry Protocol.
- **Severity**: **Critical / High** (Complete failure of error detection; broken error suppression invariant).

#### Concrete Failure Scenario / Code Inspection Evidence:
1. In Cycle 2, `GAP-14` shifted primary error ledger recording to a client-side `PostToolUse` hook:
   - Target spec line 175:
     > *"When `tool_result.is_error == true` (or error text detected), hook writes directly to `~/.cisternal/sessions/<session_id>/errors.jsonl`."*
   - Cycle 2 audit line 99:
     > *"Whenever `tool_result.is_error == true` (or error payload is detected), the hook appends the structured JSONL record directly..."*
2. Code inspection of `src/cisternal/adapters/base.py:278–388` reveals how cisternal adapters handle errors:
   - **`BathosAdapter.shape_error`** (lines 280–285):
     ```python
     return {
         "ok": False,
         "error_code": "INTERNAL",
         "error": str(exc),
         "resolution_hint": "",
     }
     ```
   - **`ContemplexAdapter.shape_error`** (lines 343–346):
     ```python
     return {"ok": False, "error_code": "INTERNAL", "error": str(exc)}
     ```
   - **`XpeririAdapter.shape_error`** (lines 366–368):
     ```python
     payload: dict[str, Any] = {"ok": False, "error": str(exc)}
     payload.update(fields)
     return json.dumps(payload, sort_keys=True)
     ```
   - **`MyxcelAdapter.shape_error`** (lines 387–388):
     ```python
     return {"error": type(exc).__name__, "message": str(exc)}
     ```
   - Only **`PassthroughAdapter.shape_error`** (lines 318) re-raises the raw exception.
3. **The Wire-Protocol Reality of MCP**:
   - When an MCP tool wrapped by an adapter catches an exception and returns a dictionary or JSON string, the FastMCP / MCP server treats the tool execution as **successful at the protocol level**!
   - In MCP JSON-RPC 2.0, the response returned to the client is:
     ```json
     {
       "content": [
         {
           "type": "text",
           "text": "{\"ok\": false, \"error_code\": \"INTERNAL\", \"error\": \"relation 'runs' does not exist\"}"
         }
       ],
       "isError": false
     }
     ```
   - Consequently, in Claude Code client transcripts and in the `PostToolUse` stdin payload, **`tool_result.is_error` evaluates to `false`**!
4. **Failure of Naive Regex and Blindness to In-Band Envelopes**:
   - If the client `PostToolUse` hook only checks `tool_result.is_error == true` or matches text regex like `(^ERROR|^Exception|Error:)`, **it will detect ZERO errors from Bathos, Contemplex, Xperiri, or Myxcel**:
     - `{"ok": false, ...}` does NOT start with `ERROR` or `Exception`.
     - `{"error": "JobFailed", ...}` does NOT match `Error:` or `^ERROR`.
   - As a result, when an MCP tool like `mcp__bathos__run_sql` fails, the client `PostToolUse` hook logs **nothing** to `~/.cisternal/sessions/<session_id>/errors.jsonl`.
5. **The Fatal Consequence (Cognitive Fallback Loop)**:
   - An agent encounters a failure in `mcp__bathos__run_sql`.
   - Per E4, the agent falls back to CLI: `bth sql "SELECT * FROM runs"`.
   - The PreToolUse hook intercepts `bth sql` and inspects `errors.jsonl`.
   - Because `PostToolUse` was blind to the in-band error envelope, `errors.jsonl` is empty.
   - The PreToolUse hook emits an active nudge:
     `"Recommendation: An equivalent MCP tool is available: 'mcp__bathos__run_sql'. Consider using it..."`
   - The agent is pushed directly back into the failing MCP tool, inducing an infinite cognitive retry loop. The core invariant of C5 is completely broken!
6. **Missing Plugin Verb Mapping Schema**:
   - Furthermore, `PostToolUse` observes only `tool_name` (e.g. `mcp__bathos__run_sql`).
   - `PreToolUse` intercepts CLI commands (e.g. `bth sql`).
   - The specification currently states in line 173 that "each plugin ships its own verb table", but defines **no schema, storage location, or discovery mechanism** for this table.
   - Without a formal mapping linking `(binary="bth", subcommand="sql")` to `(tool="mcp__bathos__run_sql", family="bathos_query")`, the PreToolUse hook cannot determine which MCP tool to check in the error ledger!

#### Impact on Implementation / Operational Failure:
- Complete breakdown of error suppression: 80% of MCP adapters (4 of 5) produce zero error records in the client ledger.
- Agents experiencing MCP failures are repeatedly harassed with CLI nudges to use broken tools.
- CLI-to-MCP matching in PreToolUse cannot be implemented without a declared verb table schema.

#### Challenger Proposed Requirement for Defender:
1. **Mandate Pre-1 Normalized JSON Parsing in Client `PostToolUse` Hook**:
   - The client-side hook script (`posttool-mcp-telemetry.sh` / `posttool-error-ledger.sh`) must not rely solely on `tool_result.is_error == true`.
   - It must attempt JSON decoding of `tool_result.content` (or text blocks) and check for canonical error envelope signatures:
     - `obj.ok === false` (Bathos, Contemplex, Xperiri)
     - `obj.error !== undefined && obj.error !== null && obj.error !== ""` (Myxcel, Xperiri, generic)
     - `obj.error_code !== undefined` (Bathos, Contemplex)
   - Fall back to checking `tool_result.is_error === true` and raw text regex (`^ERROR`, `^Exception`, `Traceback`) only if content is not JSON or does not contain envelope keys.
2. **Formalize Declarative `[verbs]` Manifest Schema in `.praxia/manifest.toml`**:
   - Specify a declarative `[verbs]` section in `.praxia/manifest.toml` (and plugin manifests):
     ```toml
     [verbs.bathos]
     binary = "bth"
     subcommands = { sql = "mcp__bathos__run_sql", show = "mcp__bathos__get_run", validate-sidecar = "mcp__bathos__validate_sidecar" }
     exclude = ["run"]
     ```
   - Both `PostToolUse` (for family attribution) and `PreToolUse` (for CLI verb correlation) read this declared mapping.

---

### GAP-22 (Medium): Inaccurate External Repository Claim in GAP-15 / Pre-0 Attribution

- **Spec Section**: Build Prerequisites: Pre-0 (lines 42–49) and Cycle 2 Audit (GAP-15, lines 106–133).
- **Subsystem**: Documentation Rigor, Repository Boundaries, Epistemic Attribution.
- **Severity**: **Medium** (Factual inaccuracy in audit rationale; potential confusion for multi-repo developers).

#### Concrete Failure Scenario / Code Inspection Evidence:
1. In the Cycle 2 Audit (`261106_cycle2_audit.md:113–118`), Challenger 2 asserted:
   > *"Empirical inspection of the local filesystem reveals:*
   > ```bash
   > python3 -c "import os; print(os.listdir('/home/marielle/projects'))"
   > # Output: ['cisternal']
   > ```
   > */home/marielle/projects/praxia does not exist on disk."*
2. Defender 2 conceded this claim (line 126):
   > *"Physical verification confirms `/home/marielle/projects/praxia` is not mounted or cloned in the active development workspace..."*
3. However, Phase 1 Recon (`261106_recon_findings.md:26, 43`) specifically audited `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py` with exact line citations:
   > *"lines 55–63, 76, 138–158, 193–213, 215–248, 447, 578–809"*.
   These lines were physically read and audited from the real repository on the host machine during Phase 1.
4. The divergence occurred because Cycle 2 execution ran within a workspace-scoped container / sandbox mount where `/home/marielle/projects` only mounted the active workspace (`cisternal`).
5. Asserting that `/home/marielle/projects/praxia` "does not exist on disk" is factually incorrect and introduces contradictory narratives across the project's audit records.
6. The true, sound engineering justification for implementing Pre-0 natively in cisternal is **package boundary separation and hermetic CI reproducibility**:
   - `cisternal` is a standalone open/modular library. It must never have hard filesystem dependencies on external sibling repositories.
   - In hermetic CI runners, containerized agent sandboxes, or user environments, sibling repositories like `praxia` are unmounted and unavailable.

#### Impact on Implementation / Operational Failure:
- Internal contradiction between Phase 1 Recon (verbatim line citations of praxia code) and Cycle 2 Audit ("praxia does not exist on disk").
- Obscures the real architectural principle: package boundary hygiene, not ephemeral directory existence.

#### Challenger Proposed Requirement for Defender:
1. **Clarify Package Boundary and Sandbox Mount Wording**:
   - Update Pre-0 documentation in the specification and audit records to explicitly state:
     > *"Praxia is an external sibling repository outside cisternal's package boundary that is unmounted in sandboxed and CI environments."*
   - Remove assertions claiming that the repository does not exist on the host machine.

---

## 3. Comprehensive Rigor Audit of Components C0–C6

To ensure no other subtle vulnerabilities exist, Challenger 3 re-audited all components C0–C6 against the criteria established in R4:

| Component | Source of Truth | Delivery Mechanism | Negative Control | Paired Positive Control | Rigor Assessment |
|---|---|---|---|---|---|
| **C0: Tracked Usage Counter** | Claude Code client JSONL transcripts (`~/.claude/transcripts/`) primary; optional server JSONL logs. | `cisternal usage` CLI; JSON and summary table; `.bth.toml` sidecar. | Planted uncalled tool equals exactly 0. | Planted called tool (`run_sql`) equals $N=5$; `len(counts) >= 2`. | **ROBUST** |
| **C1: Prune List** | Active registrations (`settings.json`, manifests) INTERSECT C0 usage; active asset whitelisting (`hook_specs`, `commands`, `skills`). | `cisternal prune-list`; three buckets (`keep`, `drop`, `enable-per-project`). | Server in transcripts but not active registration omitted; active hook/skill plugins never dropped; call > 0 never dropped. | Active plugin with 0 calls across $N \ge 20$ sessions and no non-MCP assets MUST appear in `drop`. | **ROBUST** |
| **C2: Guidance-Coverage Lint** | Declarative `[families]` in `.praxia/manifest.toml` (and plugin manifests); frontmatter `covers_families` in `SkillAsset`. | `cisternal assets validate`. | Deleting declared family from all skills fails; renaming MCP tool while skill quotes old name fails (dangling check). | Valid skills covering declared families and quoting existing tools pass validation. | **ROBUST (Preserves E3)** |
| **C3: Skill Coverage Tooling** | Frontmatter `distinctive_strings: list[str]` (min 1, max 5). Minimum 0.80 precision on 50-turn frozen set. | `cisternal skill-coverage`; generates reports and outputs `frozen_situations.jsonl`. | Synthetic transcripts with 0 opportunities trigger 0 skill opportunities. | Synthetic transcripts with known opportunities assert correct opportunity counts. | **ROBUST** |
| **C4a: Static Honesty Lint** | AST parsing of `SKILL.md` body, `references/`, and frontmatter `distinctive_strings`. Mandatory `--baseline-ref origin/main` in CI. | `cisternal assets validate`. | Description with topic token absent from headings fails (b); stripped baseline string fails (a); missing scope header in first 50 lines fails (c). | Properly structured skill matching headings, retaining baseline strings, and declaring scope header passes validation. | **ROBUST (Requires C3)** |
| **C4b: Behavioral Non-Inferiority Gate** | Asynchronous evaluation track across C3 `frozen_situations.jsonl`. Pre-registered margin $\delta \le 0.05$ (Wilson score CI). | Evaluation runner script emitting `.bth.toml` outcome. | Mutated/degraded description with fire-rate drop $> 0.05$ fails gate. | Identical or non-inferior description passes gate ($\delta \ge -0.05$). | **ROBUST (Non-blocking)** |
| **C5: Verb-to-Tool Nudge Hook** | Client `PostToolUse` error ledger (`~/.cisternal/sessions/<session_id>/errors.jsonl`) + server fallback ledger + declared `[verbs]` table. | Cisternal `hook_specs`; PreToolUse hook. Fail-open, streaming under 128 KiB limit. | Does NOT fire on `bth run` (whitelisted); does NOT fire on `bth sql` when error in ledger; exits 0 cleanly if ledger missing/corrupt. | Fires on `bth sql` when no error in ledger and MCP tool is registered. | **DEFICIENT (Requires GAP-21 resolution)** |
| **C6: `triage-tool` Skill** | Consumes C0 usage and C1 prune recommendations. Target trigger $\le 150$ chars. | `src/cisternal/assets/skills/triage-tool/SKILL.md` + `references/`. | Skill contains no automated shell commands modifying `settings.json`. | Interactive guide correctly directs user to review and apply prune list. | **ROBUST** |

### Review of Exploratory Numbers (E1–E5) and C2 Invariant
- **Exploratory Status**: Numbers E1–E5 are explicitly framed as "Preliminary Motivating Probes" in Section 2 (lines 19–26) and are not cited as frozen empirical benchmarks. C0 is explicitly tasked with re-deriving certified metrics.
- **C2 Invariant vs E3 Consistency**: Probe E3 demonstrated that 113 of 225 tool loads occurred from deferred stubs without any prior mention in skills. The C2 invariant enforces tool family coverage (`covers_families`) and dangling-name validation for tools that *are* quoted, but explicitly preserves that individual tool names do NOT need to appear in skills. This consistency is preserved.

---

## 4. Summary of Challenger 3 Requirements for Defender 3

To achieve final specification coherence and reach cycle termination, Defender 3 must resolve:

1. **GAP-20 Resolution**:
   - Reorder the dependency graph and mainline build sequence so that `C3` precedes `C4a`: `C2 -> C3 -> C4a`.
   - Explicitly link `Pre-1` and `C0` (error-path fix and ledger) to `C5` in the graph and mainline sequence, uncoupling `C5` from `C6`.
2. **GAP-21 Resolution**:
   - Update C5 specification to mandate JSON envelope parsing in the client `PostToolUse` hook, specifically inspecting `ok === false`, `error`, and `error_code` keys to match A8 adapter error shapes.
   - Specify a formal declarative `[verbs]` table schema in `.praxia/manifest.toml` mapping `(binary, subcommand) -> (mcp_tool_name, tool_family)` for PreToolUse and PostToolUse correlation.
3. **GAP-22 Resolution**:
   - Clarify Pre-0 and audit language: `praxia` is an external sibling repository outside `cisternal`'s package boundary and is unmounted in sandboxed/CI environments, rather than claiming it does not exist on disk.

---

## 5. Defender 3 Resolution

### 5.1 Concessions and Architectural Framework

Defender 3 acknowledges and **concedes all three findings raised by Challenger 3 (GAP-20, GAP-21, and GAP-22) in full as genuine gaps**.

The empirical evidence and protocol analysis presented by Challenger 3 are incontrovertible:
1. **GAP-20**: Placing `C4a` in parallel with `C3` creates a circular attribute dependency. `C4a` Check (a) and (b) statically evaluate `distinctive_strings`, which is declared and instantiated in `SkillAsset` only by `C3`. Implementing `C4a` before or beside `C3` breaks schema validation and violates the core requirement: *"Build order respects dependencies (C4 needs C3; C5 needs the E4 error-path fix)"*. Furthermore, `C5`'s error-suppression invariant depends functionally on Pre-1's normalized errors and C0's transition classification, not on the user-facing skill `C6`.
2. **GAP-21**: Because FastMCP and cisternal adapters catch exceptions and return dictionaries or JSON strings (A8), MCP JSON-RPC returns `isError: false` on the wire. A client-side `PostToolUse` hook inspecting only `tool_result.is_error == true` or crude text regex (`^ERROR|^Exception|Error:`) is completely blind to 80% of adapter error envelopes (`BathosAdapter`, `ContemplexAdapter`, `XpeririAdapter`, `MyxcelAdapter`). This leaves the error ledger empty and induces toxic cognitive fallback loops. Furthermore, correlating CLI commands to MCP tools requires a formal declarative `[verbs]` manifest schema.
3. **GAP-22**: Claiming that `/home/marielle/projects/praxia` "does not exist on disk" confused a workspace-scoped container mount boundary with physical host reality, creating unnecessary contradictions with Phase 1 Recon. The true justification for native implementation is clean package boundary separation and hermetic CI reproducibility.

---

### 5.2 Detailed Architectural Resolutions

#### 5.2.1 Resolution of GAP-20: Dependency Ordering Realignment (`C3 -> C4a`) & Error-Path Mainline Link

To satisfy the strict build dependency rule **"C4 needs C3"** and explicitly ground **"C5 needs the E4 error-path fix"**:

1. **Dependency Realignment (`C2 -> C3 -> C4a`)**:
   - `C2` establishes the tool family schema (`covers_families`) on `SkillAsset`.
   - `C3` extends `SkillAsset` with `distinctive_strings: list[str] = Field(..., min_length=1, max_length=5)` and builds the opportunity mining and evaluation harness (`tests/fixtures/eval/frozen_situations.jsonl`).
   - `C4a` imports `SkillAsset` containing both `covers_families` (from C2) and `distinctive_strings` (from C3) to execute its AST static honesty lints:
     - Check (a) (Containment): Validates that frontmatter `distinctive_strings` appear in description or body.
     - Check (b) (No Overclaim): Uses declared `distinctive_strings` as candidate topic tokens.
     - Check (c) (Scope Header): Enforces `## Scope` or `## When to Use` within the first 50 lines.
   - Therefore, `C3` strictly precedes `C4a` in the dependency graph: `C2 -> C3 -> C4a`.

2. **Decoupling and Error-Path Rooting of C5 (`(Pre-1, C0, C2) -> C5`)**:
   - `C5` (the Verb-to-Tool Nudge Hook) does **not** depend on `C6` (the interactive `triage-tool` skill).
   - `C5`'s operational invariant (suppressing CLI nudges after MCP failures) strictly requires:
     - **Pre-1**: Normalized error envelopes (`NormalizedError`) and adapter error contract.
     - **C0**: Tracked usage counter, client transcript parsing, and error-to-fallback transition tracking.
     - **C2**: Declarative tool family schema (`[families]`) to resolve tool-to-family relationships.
     - **Two-Tier Error Ledger**: Session-exact and fallback error ledger infrastructure.
   - Mainline build sequence and the dependency graph explicitly route `(Pre-1, C0, C2) -> C5`.

3. **Revised ASCII Dependency Graph**:
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
                         │                                   ▼
                         │                   +-------------------------------+
                         │                   |   C3: Skill Coverage Tooling  |
                         │                   | (distinctive_strings Schema)  |
                         │                   |  (Mines Frozen Situation Set) |
                         │                   +-------------------------------+
                         │                                   │
                         │                 ┌─────────────────┴─────────────────┐
                         │                 ▼                                   ▼
                         │ +-------------------------------+ +---------------------------------------+
                         │ |  C4a: Static Honesty Lint     | | [Non-Blocking Evaluation Track]       |
                         │ | (No loss, no overclaim, scope)| | C4b: Behavioral Non-Inferior Gate    |
                         │ |   (Strictly Depends on C3)    | | (Fire-rate on Frozen Set, δ <= 0.05)  |
                         │ +-------------------------------+ +---------------------------------------+
                         │                 │
                         └────────┬────────┘
                                  ▼
                  +-------------------------------+
                  |  C6: triage-tool Skill Build  |
                  | (Trigger <= 150c, References) |
                  +-------------------------------+

                  [Error-Path Hook Track: Requires Pre-1, C0, C2]
                  (Pre-1, C0, C2) ───────► +-------------------------------+
                                           |   C5: Verb-to-Tool Nudge Hook |
                                           | (Two-Tier Session Error State)|
                                           | (In-Band JSON Envelope Parser)|
                                           | (Declared [verbs] CLI Mapping)|
                                           +-------------------------------+
   ```

4. **Revised Mainline Build Sequence**:
   - **Mainline Tools & Static Lints**: `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> C3 -> C4a -> C6`
   - **Error-Path Hook Track**: `(Pre-1, C0, C2) -> C5`
   - **Asynchronous Evaluation Track**: `C3 -> C4b`

---

#### 5.2.2 Resolution of GAP-21: In-Band Error Envelope Parsing in PostToolUse Hook & Declarative `[verbs]` Manifest Schema

To prevent client-side hook blindness to adapter error payloads (A8) and establish reliable CLI verb correlation:

1. **In-Band JSON Error Envelope Parsing in `PostToolUse` Hook**:
   - The client-side hook script (`posttool-error-ledger.sh` / `posttool-mcp-telemetry.sh`) receives Claude Code's standard `PostToolUse` JSON payload on stdin:
     ```json
     {
       "session_id": "...",
       "tool_name": "mcp__bathos__run_sql",
       "tool_input": { "query": "SELECT * FROM invalid_table" },
       "tool_result": {
         "content": [
           {
             "type": "text",
             "text": "{\"ok\": false, \"error_code\": \"INTERNAL\", \"error\": \"relation 'invalid_table' does not exist\"}"
           }
         ],
         "is_error": false
       }
     }
     ```
   - **Parsing Algorithm**:
     1. Resolve `session_id` from top-level input (`session_folder = session_id or "default"`).
     2. Extract text blocks from `tool_result.content` (or `tool_result.text`).
     3. For each text block, attempt JSON decoding:
        - If valid JSON object `data`:
          - Check canonical adapter error keys:
            - **Bathos / Contemplex / Xperiri**: `data.get("ok") is False`
            - **Myxcel / Generic**: `data.get("error") is not None and str(data.get("error")).strip() != ""`
            - **Bathos / Contemplex**: `data.get("error_code") is not None`
            - **Fallback Generic**: `data.get("is_error") is True` or `data.get("success") is False`
          - If any match:
            - `is_error = True`
            - `error_code = str(data.get("error_code") or data.get("error") or "TOOL_ERROR")`
            - `message = str(data.get("error") or data.get("message") or data)`
        - If not JSON or JSON parsing fails:
          - Check wire-level flag: `tool_result.is_error == True`
          - Check raw text regex: `re.search(r"(^ERROR\b|^Exception\b|\bError:\s*|\bTraceback \(most recent call last\):)", text, re.MULTILINE)`
          - If matched: `is_error = True`, `error_code = "RAW_ERROR"`, `message = text[:200]`.
     4. If `is_error` is detected:
        - Resolve tool family from declared `[verbs]` or `[families]` manifest table (default to plugin prefix if unmapped).
        - Append structured JSONL entry to `~/.cisternal/sessions/<session_folder>/errors.jsonl`:
          ```json
          {
            "timestamp": "2026-11-06T20:45:00Z",
            "session_id": "<session_id>",
            "tool_name": "mcp__bathos__run_sql",
            "family": "bathos_query",
            "error_code": "INTERNAL",
            "message": "relation 'invalid_table' does not exist",
            "source": "client_posttool_hook"
          }
          ```
     5. Fail-open execution: Wrap script in `|| exit 0` so telemetry errors never disrupt agent interaction.

2. **Declarative `[verbs]` Manifest Schema in `.praxia/manifest.toml`**:
   To allow `PreToolUse` (which intercepts CLI commands like `bth sql`) and `PostToolUse` (which intercepts MCP tools like `mcp__bathos__run_sql`) to correlate actions unambiguously, declare the `[verbs]` table in `.praxia/manifest.toml` (and plugin manifests):
   ```toml
   [verbs.bathos]
   binary = "bth"
   subcommands = { sql = "mcp__bathos__run_sql", show = "mcp__bathos__get_run", validate-sidecar = "mcp__bathos__validate_sidecar" }
   tool_family = "bathos_query"
   exclude = ["run"]

   [verbs.contemplex]
   binary = "ctxp"
   subcommands = { start = "brainstorm_start", reply = "brainstorm_reply", finalize = "brainstorm_finalize" }
   tool_family = "contemplex_brainstorm"
   exclude = []

   [verbs.myxcel]
   binary = "myxcel"
   subcommands = { status = "job_status", list = "list_jobs", logs = "job_logs" }
   tool_family = "myxcel_slurm"
   exclude = ["submit", "cancel"]
   ```

3. **PreToolUse Execution Protocol**:
   - `PreToolUse` intercepts CLI commands via `parse_cli_command(command) -> (binary, subcommand)`.
   - Reads `[verbs]` from `.praxia/manifest.toml` / plugin manifests:
     - If `subcommand in verbs[binary].exclude`: exit 0 immediately (no nudge; whitelisted command like `bth run`).
     - If `(binary, subcommand)` maps to `(tool_name, tool_family)`:
       - Checks `~/.cisternal/sessions/<session_id>/errors.jsonl` (session-exact).
       - Checks `~/.cisternal/sessions/default/errors.jsonl` (within last 900 seconds).
       - If either ledger contains an entry matching `tool_name` or `tool_family`: **exit 0 immediately (suppress nudge)**.
       - If no error record exists and MCP tool is active: emit Claude Code JSON nudge:
         ```json
         {
           "additionalContext": "Recommendation: An equivalent MCP tool is available: 'mcp__bathos__run_sql'. Consider using it for structured telemetry and faster execution."
         }
         ```

---

#### 5.2.3 Resolution of GAP-22: Clarification of Repository Boundary vs Sandbox Mount Attribution

1. **Reconciliation of Epistemic Inconsistency**:
   - In Phase 1 Recon (`261106_recon_findings.md:26, 43`), `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py` was directly audited at lines 55–63, 76, 138–158 from the host filesystem.
   - In Cycle 2, execution occurred within a containerized/sandboxed worktree where `/home/marielle/projects` mounted only the active workspace (`cisternal`). The command `os.listdir('/home/marielle/projects')` returned `['cisternal']`, leading to the inaccurate claim that praxia "does not exist on disk".
   - Claiming the external repository does not exist on disk was an artifact of sandbox mount scoping, not physical absence.

2. **Formal Package Boundary Specification for Pre-0**:
   - The specification and audit records are updated to state the genuine architectural rationale:
     > *"Praxia is an external sibling repository outside cisternal's package boundary that is unmounted in sandboxed and CI environments."*
   - `cisternal` is an independent, hermetic library. Hard filesystem path dependencies on external sibling repositories (`/home/marielle/projects/praxia/...`) violate package isolation, break hermetic CI builds, and fail in containerized environments.
   - Pre-0 implements a native, self-contained transcript parser in `src/cisternal/usage/transcript.py` with formal header attribution to Praxia's architectural design, guaranteeing 100% hermetic reproducibility across all environments.

---

### 5.3 Final Disposition Table for Cycle 3

| Gap ID | Issue Summary | Spec Section | Defender 3 Resolution | Final Disposition |
|---|---|---|---|---|
| **GAP-20** | Build order violates "C4 needs C3" (`C4a` parallel with `C3`); C5 missing error-path link. | Order & Graph (lines 207–251), C4a, C5 | Conceded. ASCII dependency graph updated to `C2 -> C3 -> C4a`. Mainline sequence updated to `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> C3 -> C4a -> C6`, with `(Pre-1, C0, C2) -> C5` explicitly linked to Pre-1 error normalization pass. | **CONCEDED & RESOLVED** |
| **GAP-21** | Client `PostToolUse` hook blind to in-band adapter JSON errors (`is_error: false`); missing `[verbs]` manifest schema. | C5 (lines 172–199), Pre-1 | Conceded. Specified JSON envelope decoding in `PostToolUse` checking canonical keys (`ok === false`, `error`, `error_code`). Defined declarative `[verbs]` table schema in `.praxia/manifest.toml` mapping CLI `(binary, subcommand)` to `(tool_name, tool_family)` with `exclude` list. | **CONCEDED & RESOLVED** |
| **GAP-22** | Rationale for Pre-0 inaccurately claimed praxia does not exist on disk due to sandbox mount confusion. | Pre-0 (line 42), Cycle 2 Audit | Conceded. Clarified language across spec and audit: praxia is an external sibling repository outside cisternal's package boundary that is unmounted in sandboxed and CI environments. Grounded Pre-0 in hermetic package boundary hygiene. | **CONCEDED & RESOLVED** |

---

### 5.4 Verification of Spec Coherence Post-Cycle 3

With the incorporation of Defender 3's resolutions into `.praxia/docs/specs/261106_tool-surface-triage.md`:
1. **Dependency Invariants Satisfied**: The build sequence strictly honors `C4 needs C3` (`C2 -> C3 -> C4a`) and `C5 needs the E4 error-path fix` (`(Pre-1, C0, C2) -> C5`).
2. **Error Suppression Runtime Integrity**: The client-side `PostToolUse` error ledger parses in-band adapter envelopes (A8), guaranteeing that MCP errors from all adapters suppress subsequent CLI nudges and prevent infinite cognitive fallback loops.
3. **Declarative CLI-to-Tool Correlation**: The formal `[verbs]` manifest schema allows `PreToolUse` and `PostToolUse` to discover and correlate CLI verbs to MCP tools and families unambiguously.
4. **Hermetic Boundary Clarity**: Pre-0 cleanly encapsulates transcript parsing natively within cisternal with proper architectural attribution, free from dangling filesystem paths and grounded in clear package boundary separation.

Cycle 3 has successfully resolved all remaining structural and operational gaps. The specification is fully coherent, implementable, and resilient.
