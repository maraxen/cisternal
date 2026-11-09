---
title: "Tool-Surface Triage: Phase 3 Cycle 1 Adversarial Audit"
description: "Sequential adversarial audit of tool-surface triage spec: 13 gaps conceded by defender and resolved with architectural specifications."
status: complete
task_id: 261106_tool-surface-triage
date: '261106'
author: "challenger_c1 / defender_c1"
verdict: CONCEDED_AND_RESOLVED
---
# Phase 3 Cycle 1 Adversarial Audit: Tool-Surface Triage Spec
Claimed by: challenger_c1 (Challenger), defender_c1 (Defender), worker_docs_indexer (Docs Alignment)

- **Target Spec**: `.praxia/docs/specs/261106_tool-surface-triage.md`
- **Audit Cycle**: Phase 3, Cycle 1 (Challenger Audit & Defender Resolution)
- **Author**: Adversarial Spec Challenger (`challenger_c1`) & Defender Subagent (`defender_c1`)
- **Status**: Audit & Resolution Complete — All 13 Gaps Conceded with Full Architectural Specifications

---

## Executive Summary & Overall Risk Assessment

**Overall Risk Assessment**: **HIGH**

While `.praxia/docs/specs/261106_tool-surface-triage.md` defines a compelling vision for measuring and optimizing agent tool/skill surfaces, the draft in its current form contains **critical architectural omissions, cross-repository blockers, ungrounded static checks, and flawed falsification controls**. If handed to an engineering agent today, implementation would stall or produce false invariants.

### Key Vulnerabilities Identified:
1. **Repository Boundary Blocker (C0)**: C0 claims to "Wrap or move praxia `session_context_audit.py`", ignoring that `praxia` is an external, uncoupled repository (`/home/marielle/projects/praxia`). Cisternal cannot wrap or move external files without an explicit vendoring or migration contract.
2. **Ignored Assumption A8 Refutation (C0, C5)**: The spec marks A8 as `UNVERIFIED`, but code inspection of `src/cisternal/adapters/base.py:278–388` proves A8 is **REFUTED**. MCP adapters return heterogeneous error shapes (dicts, JSON strings, and re-raised exceptions). C0's error counter and C5's error suppression will fail on 4 out of 5 adapters without an Adapter Error Normalization pass.
3. **Stateless Subprocess Blindness (C5)**: C5 mandates suppressing nudges if an MCP tool errored earlier in the session, but fails to define any session state mechanism for ephemeral PreToolUse hook subprocesses.
4. **Vulnerable Negative Controls (Silent Masking)**: Negative controls for C0 and C3 test only for zero-counts on uncalled entities. In the presence of parser crashes or silent harness failures (as demonstrated in research note Topic 1.1.B), broken code trivially passes by returning zero for everything. Paired positive controls are mandatory.
5. **Ungrounded "Long Form" Baseline (C4)**: C4 static check (a) requires that no distinctive string from the "long form" description is lost, but the long form is deleted during compression and exists nowhere on disk or in the AST without a defined historical baseline.
6. **Undefined "Tool Family" Schema (C2)**: C2 enforces that "every tool family has a situation-matched skill trigger", but cisternal asset models define no concept of a "tool family" or declarative mapping from tools to triggers.
7. **Epistemic Circularity**: The spec states in line 19 that exploratory numbers from 145 transcripts must be re-derived by C0 "before anything cites it", yet lines 41–63 cite E1–E5 as established justifications for architectural decisions.

---

## 1. Component Rigor Audit (C0–C6)

Every component must define an unambiguous **Source of Truth**, a concrete **Delivery Mechanism**, and a rigorous **Negative Control** (falsification test).

| Component | Source of Truth Evaluation | Delivery Mechanism Evaluation | Negative Control Evaluation | Rigor Verdict |
|---|---|---|---|---|
| **C0: Tracked Usage Counter** | **DEFICIENT**: "Wrap or move praxia `session_context_audit.py`" fails across repo boundaries. Path discovery for transcripts and join keys for server JSONL are unspecified. | **PARTIAL**: Specifies `cisternal usage` and `.bth.toml`, but omits CLI flags, output formats (JSON vs stdout), and pre-registration outcomes schema. | **FLAWED**: Planted never-called tool returning 0 is susceptible to silent masking (a broken parser returning 0 passes). Lacks paired positive control. | **REJECTED** |
| **C1: Prune List** | **AMBIGUOUS**: "settings, `~/.claude.json`, plugin manifests". Ambiguous file paths, undefined retention window, and fails to protect hook-only/skill-only plugins emitting 0 MCP calls. | **INCOMPLETE**: Output format is unspecified; decision rules for the `enable-per-project` bucket are completely undefined. | **WEAK**: Asserts registered server with calls is not dropped, but does not test zero-call hook/skill plugins or empty transcript sets. | **REJECTED** |
| **C2: Guidance-Coverage Lint** | **UNIMPLEMENTABLE**: Requires "every tool family has a situation-matched skill trigger", but "tool family" has no data model, schema, or registry in cisternal. | **PARTIAL**: Hosted in `cisternal assets validate`, but lacks regex/AST grammar for extracting quoted tools and lacks semantic evaluation mechanism for offline static runs. | **INCOMPLETE**: Test fixture requires mocked tool family definitions that do not currently exist. | **REJECTED** |
| **C3: Skill Coverage Tooling** | **AMBIGUOUS**: "transcripts + manifests". Lacks storage schema for "distinctive strings" (frontmatter vs body) and lacks exact definition/window of an "opportunity". | **INCOMPLETE**: Delivery mechanism (CLI vs Python API) is unspecified. Data schema for the "frozen situation set" feeding C4 is omitted. | **DEFICIENT**: "precision measured on a hand-labelled sample" lacks an explicit acceptance threshold (e.g. precision $\ge 0.80$). | **REJECTED** |
| **C4: Honesty Check** | **BROKEN**: Check (a) checks against a "long form" that does not exist on disk after compression. Checks (b) and (c) lack deterministic static algorithms. | **SPLIT DEPENDENCY**: Monolithically blocked on C3. Static checks ((a)-(c)) could ship immediately; behavioral check requires C3 and lacks non-inferiority margin $\delta$. | **ASYMMETRIC**: Tests static overclaim and loss, but specifies zero negative control for behavioral non-inferiority. | **REJECTED** |
| **C5: Verb Nudge Hook** | **MISSING STATE**: Ephemeral hook subprocess cannot query prior MCP errors without a shared session state ledger. Verb table location/schema is undefined. | **HAZARDOUS**: Omits exact Claude Code JSON schema (`{"additionalContext": "..."}`), risking tool execution failure. Ignores 128 KiB shell argument ceiling. | **PARTIAL**: Tests `bth sql` vs `bth run` vs error suppression, but lacks fail-open negative control when verb table is corrupt or missing. | **REJECTED** |
| **C6: `triage-tool` Skill** | **PARTIAL**: Uses telemetry (A2) and ends in prune list, but canonical repo path (`.praxia/skills/` vs `src/cisternal/`) is not pinned. | **SOUND**: Target trigger $\le 150$ chars; modular `references/`; strictly non-destructive (user applies prune list). | **INCOMPLETE**: Lacks negative control asserting that skill instructions never advise automatic editing of `~/.claude/settings.json`. | **CONDITIONAL** |

---

## 2. Detailed Component Challenges

### C0: Tracked Usage Counter
- **Challenge 1.1 (Cross-Repository Import Failure)**:
  - *Observation*: Spec line 41 states: `Wrap or move praxia session_context_audit.py`.
  - *Code Fact*: `session_context_audit.py` resides at `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`. Cisternal is an independent package at `/home/marielle/projects/cisternal`.
  - *Attack Scenario*: A developer runs `pip install -e .` in a fresh checkout of cisternal (e.g., CI or a consumer machine without `praxia`). C0 fails immediately with `FileNotFoundError` or `ModuleNotFoundError`.
  - *Blast Radius*: C0 is the foundational deliverable on which C1, C3, and C4 depend; the entire triage pipeline is dead on arrival.
  - *Mitigation*: Vendor the core transcript-parsing logic into `src/cisternal/usage/transcript.py` with explicit attribution, removing praxia-specific hardcoded regex (`CLI_RE`) and replacing it with generic CLI extraction.
- **Challenge 1.2 (Silent Masking Vulnerability in Negative Control)**:
  - *Observation*: Spec line 42 states: `NC: synthetic transcript with known counts, a planted never-called tool must appear as zero.`
  - *Empirical Precedent*: In July 2026, Anthropic's `run_eval.py` failed silently inside Claude Code's sandbox, reporting 0.0 for all queries (`trigger_harness_controls.py:1–45`). A broken script looks identical to a tool that is never called.
  - *Attack Scenario*: The parser encounters an unexpected JSON structure, swallows the exception, and returns `{}`. The test inspects `counts.get("planted_tool", 0)`, finds `0`, and reports **PASS**.
  - *Mitigation*: The test harness must execute **paired positive and negative controls**: a synthetic transcript with 5 planted calls to `mcp__bathos__run_sql` and 0 calls to `mcp__bathos__planted_tool` must assert `run_sql == 5` AND `planted_tool == 0`. An empty dictionary or failure to parse must raise a hard error.

### C1: Prune List
- **Challenge 1.3 (Destructive Pruning of Hook-Only and Skill-Only Plugins)**:
  - *Observation*: Spec line 43 defines Truth as `current registration INTERSECT C0 usage`.
  - *Code Fact*: `src/cisternal/export/hooks.py` and `src/cisternal/export/claude.py` allow plugins to ship PreToolUse hooks, commit hooks, or skills without exporting any MCP tools.
  - *Attack Scenario*: An engineer installs a security plugin that registers a `PreToolUse` bash linter and git commit hook. C0 inspects transcripts and records 0 MCP calls for this plugin. C1 flags the plugin as `drop`. The engineer applies the recommendation, silently removing their commit safety guardrails.
  - *Mitigation*: C1's registration scanner must inspect plugin manifests for non-MCP assets (`hook_specs`, `commands`, `skills`). Any plugin providing active hooks or skills must be whitelisted from `drop` recommendations regardless of MCP call volume.
- **Challenge 1.4 (Undefined Retention Window and Sample Size)**:
  - *Observation*: Spec line 43 provides no time horizon or minimum session volume for calculating usage.
  - *Attack Scenario*: An engineer switches to a new project or runs C1 after working on a task that didn't require database queries. Bathos has 0 calls in the last 2 sessions. C1 recommends dropping Bathos.
  - *Mitigation*: C1 must require a minimum sample threshold (e.g., $N \ge 20$ sessions or 14-day lookback window) and output sample size confidence metrics.

### C2: Guidance-Coverage Lint
- **Challenge 1.5 (Unimplementable "Tool Family" Invariant)**:
  - *Observation*: Spec line 45 states: `Invariant: every tool family has a situation-matched skill trigger, and every tool name a skill quotes exists (dangling-name check).`
  - *Code Fact*: In `src/cisternal/assets/bundle.py`, tools are represented as flat `McpAsset` objects. There is no `family` field on tools, nor any declaration linking a skill to a tool family.
  - *Attack Scenario*: A developer adds a new MCP tool `mcp__bathos__figure_diff`. They run `cisternal assets validate`. Does it pass or fail? The validator has no data structure to determine whether `figure_diff` belongs to the "bathos inspection" family or requires a new skill trigger.
  - *Mitigation*: Introduce a declarative `families` section in `cisternal.toml` or `plugin.json` mapping tool prefixes/names to family identifiers, and add a `covers_families = ["..."]` frontmatter key to `SkillAsset`.
- **Challenge 1.6 (Semantic Situation Matching Cannot Run in Static Lint)**:
  - *Observation*: C2 requires the static lint in `assets validate` to ensure the trigger is "situation-matched".
  - *Attack Scenario*: A skill trigger says "Use when handling fish". A static regex cannot determine whether this matches a database query tool family without invoking an LLM judge.
  - *Mitigation*: Decouple static structural integrity (explicit family tag matching + dangling name check) from semantic trigger quality (evaluated via C4 behavioral harness).

### C3: Skill Coverage Tooling
- **Challenge 1.7 (Storage Location of Distinctive Strings)**:
  - *Observation*: Spec line 47 defines opportunities as: `a Bash/tool/file action matching its distinctive strings`.
  - *Code Fact*: Currently, distinctive strings are only discussed conceptually in `.praxia/skills/writing-skill-triggers/SKILL.md:30–33`. They do not exist as a structured field in any schema.
  - *Attack Scenario*: C3 executes and attempts to read distinctive strings from `SkillAsset`. The attribute does not exist. The opportunity scanner falls back to matching raw skill descriptions, generating massive false positives on generic English words.
  - *Mitigation*: Add `distinctive_strings: list[str]` to the skill schema in `src/cisternal/assets/skill_schema.py` and enforce a limit of 2–5 strings.

### C4: Progressive-Disclosure Honesty Check
- **Challenge 1.8 (Missing "Long Form" Baseline in Check (a))**:
  - *Observation*: Spec line 50 states: `(a) no loss: every distinctive string of the long form is in the short description or the body`.
  - *Code Fact*: Once an author edits `when_to_use` down to $\le 250$ chars to satisfy A3/A5, the "long form" is destroyed in working tree files.
  - *Attack Scenario*: A static check runs on the file. Where does it fetch the "long form"? If it queries `git diff HEAD~1`, it breaks in fresh checkouts, detached HEADs, and uncommitted branches.
  - *Mitigation*: Clarify that check (a) compares the compressed `description + when_to_use` against the **Tier 2 `SKILL.md` body**: every distinctive string claimed in the skill must be present in the body. If comparing against a historical pre-compression description, specify an explicit `--baseline-ref` git commit flag.
- **Challenge 1.9 (Unspecified Behavioral Non-Inferiority Margin)**:
  - *Observation*: Spec line 51 states: `non-inferiority of fire-rate for short vs long description on a frozen situation set, threshold pre-registered.`
  - *Attack Scenario*: An author shortens a description. Fire rate drops from 85% to 75%. Is this acceptable? Without a pre-registered non-inferiority margin $\delta$, this check cannot pass or fail deterministically.
  - *Mitigation*: Pre-register the non-inferiority margin explicitly: $\delta \le 0.05$ at 95% confidence on the frozen opportunity set.

### C5: Verb-to-Tool Nudge Hook
- **Challenge 1.10 (Stateless Subprocess Blindness to Prior MCP Errors)**:
  - *Observation*: Spec line 55 mandates: `Do not nudge when the same verb's MCP tool errored earlier in the session (E4).`
  - *Code Fact*: PreToolUse hooks run as isolated, ephemeral shell subprocesses (`pretool-tool-rewrite.sh`). When the hook runs on turn 10 for `bth sql`, it has zero memory of turn 8.
  - *Attack Scenario*: An agent calls `mcp__bathos__run_sql`, which crashes with an OOM error. The agent falls back to `bth sql`. The hook spawns, has no session memory, and nudges: "Use mcp__bathos__run_sql". The agent enters an infinite cognitive thrashing loop.
  - *Mitigation*: Implement a session-scoped error marker: cisternal server adapters must record errors to an ephemeral file (`~/.cisternal/sessions/<session_id>/errors.jsonl`), which the hook checks before emitting a nudge.
- **Challenge 1.11 (Refutation of Assumption A8 Breaks Error Detection)**:
  - *Observation*: Spec line 55 states: `Fix the error path first: classify the 57 errors... before shipping.`
  - *Code Fact*: Recon proved A8 is **REFUTED** (`base.py:278–388`). `MyxcelAdapter` returns `{error, message}` (no `ok` or `error_code`); `XpeririAdapter` returns a JSON string; `PassthroughAdapter` re-raises exceptions.
  - *Attack Scenario*: C5 checks `result.get("ok") is False`. An error from `myxcel` or `xperiri` is completely missed. The hook assumes success and continues nudging broken tools.
  - *Mitigation*: C5 must be explicitly blocked on an **Adapter Error Normalization Pass** in `base.py` that normalizes error reporting across all adapters.
- **Challenge 1.12 (Cross-Surface Schema Incompatibility and Shell Limits)**:
  - *Observation*: Spec line 55 states: `Additive context only.`
  - *Code Fact*: Research findings Topic 4.1.B (`emit_hook_output.sh:110–116`) show that Claude Code requires `{"additionalContext": "..."}` and hard-fails with `Hook JSON output validation failed` if keys like `decision: allow` are emitted. Furthermore, `MAX_ARG_STRLEN` caps shell arguments at 128 KiB.
  - *Attack Scenario*: The hook script generates a formatted message and passes it via `jq --arg msg "$LONG_TEXT"`. If text exceeds 128 KiB, `jq` exits with an error and emits empty output. If the hook outputs Antigravity schema keys, Claude Code aborts the Bash command.
  - *Mitigation*: Specify the exact JSON output payload (`{"additionalContext": "..."}`), enforce fail-open semantics (`|| exit 0`), and stream context via stdin/temp files rather than CLI arguments.

---

## 3. Evidence Alignment Audit (E1–E5)

| Evidence ID | Spec Finding | Component Claim Supported | Adversarial Challenge & Rigor Gaps |
|---|---|---|---|
| **E1** | 943 MCP vs 7,948 CLI calls (~10% MCP) across 145 sessions for bathos. | Justifies C0 (tallying) and C5 (nudging bathos CLI verbs). | **OVERCLAIM**: Measured exclusively `bathos`. Generalizing a 10% MCP ratio to all tools and plugins is unverified. C5 assumes CLI is a "wrong action" without proving whether CLI was faster or necessary. |
| **E2** | 2,524 / 2,537 ToolSearch calls were `select:<exact name>`; 13 keyword. | Justifies scoping out global CLAUDE.md search rules; motivates C2. | **LEAP OF LOGIC**: Spec claims "Agents do not search; discovery is not the bottleneck". If agents default to CLI because they don't know MCP exists (E1), discovery *is* a bottleneck—keyword search is just the wrong solution. |
| **E3** | 113 / 225 bathos loads had name in deferred listing only; 112 had prior mention. | Falsifies the rule that tool names must appear in skills; updates C2 invariant. | **VALID EXISTENCE PROOF, BUT INCOMPLETE**: While 50.2% load from stubs disproves necessity of skill mentions, C0 is asked to track `select:` provenance without defining the provenance category schema. |
| **E4** | Same-verb CLI followed in 13/57 (23%) after error vs 15/664 (2%) after success. | Justifies C5 error suppression invariant; motivates error path fix. | **CIRCULAR RELIANCE**: Spec admits the 57 errors were detected via an unverified heuristic (`is_error` or `error_code`) and are unclassified, while A8 proved error shapes are heterogeneous. Citing 23% as hard justification while unclassified is circular. |
| **E5** | 27 enabled plugins; ~35 zero-use servers in transcripts are historical text. | Justifies C1 intersecting usage with current registration. | **PARTIAL**: Correctly prevents ghost pruning, but fails to distinguish standalone MCP servers from plugin-packaged MCP servers. |

---

## 4. Build Order and Dependency Graph Audit

### Current Spec Build Order (Line 60):
`C0 -> C1, C2 -> C3 -> C4 -> C6 -> C5 (C5 last: needs the error-path fix and the A/B)`

### Flaws in the Current Build Order:
1. **Missing Prerequisite 0 (External Repo Resolution)**:
   - C0 cannot begin until the decision to vendor `session_context_audit.py` from `praxia` into `cisternal` is formalized.
2. **Missing Prerequisite 1 (A8 Adapter Error Normalization Pass)**:
   - C0 claims to track "error-to-fallback (E4)". How can C0 track errors when `MyxcelAdapter` outputs `{error, message}` without `ok` or `error_code`, `XpeririAdapter` outputs strings, and `PassthroughAdapter` raises exceptions?
   - Adapter error normalization must precede C0's error-tracking and C5's error suppression.
3. **Monolithic C4 Dependency on C3**:
   - The spec blocks all of C4 on C3.
   - However, C4 consists of **Static Honesty Checks** ((a) no loss, (b) no overclaim, (c) scope header) and a **Behavioral Non-Inferiority Gate**.
   - Static checks ((a)-(c)) depend only on `src/cisternal/assets/skill_schema.py` and can be built immediately alongside C2. Only the behavioral gate depends on C3's frozen situation set.

### Recommended Corrected Dependency Graph:

```
               +-------------------------------------------------+
               |  Pre-0: Vendor session_context_audit to cisterna |
               +-------------------------------------------------+
                                       │
               +-----------------------▼-------------------------+
               | Pre-1: A8 Adapter Error Shape Normalization Pass|
               +-------------------------------------------------+
                                       │
               +-----------------------▼-------------------------+
               |           C0: Tracked Usage Counter             |
               |       (Paired Positive/Negative Controls)       |
               +-------------------------------------------------+
                                       │
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
   +-----------------------------------+ +-----------------------------------+
   |          C1: Prune List           | |     C2: Guidance-Coverage Lint    |
   | (Active Registration ∩ C0 Usage)  | |   (Tool Family Schema + Dangling) |
   | (Whitelist Hook & Skill Plugins)  | +-----------------------------------+
   +-----------------------------------+                 │
                     │                   ┌───────────────┴───────────────────┐
                     │                   ▼                                   ▼
                     │   +-------------------------------+   +-------------------------------+
                     │   |  C4a: Static Honesty Lint     |   |   C3: Skill Coverage Tooling  |
                     │   | (No loss, no overclaim, scope)|   |  (Mines Frozen Situation Set) |
                     │   +-------------------------------+   +-------------------------------+
                     │                   │                                   │
                     └───────────────────┼───────────────────────────────────┘
                                         │
                                         ▼
                         +-------------------------------+
                         | C4b: Behavioral Non-Inferior  |
                         | (Fire-rate on Frozen Set, δ)  |
                         +-------------------------------+
                                         │
                                         ▼
                         +-------------------------------+
                         |  C6: triage-tool Skill Build  |
                         | (Trigger <= 150c, References) |
                         +-------------------------------+
                                         │
                                         ▼
                         +-------------------------------+
                         |   C5: Verb-to-Tool Nudge Hook |
                         | (Session Error State Ledger)  |
                         | (Matched-Session A/B Harness) |
                         +-------------------------------+
```

---

## 5. Epistemic Humility and Framing Audit

### Flaw: Exploratory Numbers Treated as Certified Ground Truth
- Spec Line 19 correctly adds an exploratory disclaimer: `EXPLORATORY: untracked scripts over 145 main-session transcripts, subagents excluded; C0 must re-derive before anything cites it`.
- **However, the spec violates its own rule in subsequent sections**:
  1. *Line 45 (C2)*: Asserts `E3 falsifies "name must appear in a skill"`. An uncommitted, untracked exploratory probe cannot formally "falsify" an invariant; it serves as a preliminary counterexample motivating an invariant revision.
  2. *Line 55 (C5)*: Commands: `Fix the error path first: classify the 57 errors... before shipping.` Referring to "the 57 errors" frames an ad-hoc, heuristic-detected sample as a closed, certified truth set. A formal re-derivation under C0 will yield a different number.
  3. *Line 63 (Scope)*: Asserts `discovery is not the bottleneck` based solely on E2.
- **Required Remediation**: The spec must consistently frame E1–E5 as **Preliminary Motivating Probes**. All downstream decisions must cite the underlying design rationale rather than treating the exploratory numbers as frozen empirical benchmarks.

---

## 6. C2 Invariant Consistency Audit (E3 Alignment)

- **Audit Question**: Does C2 require tool names to appear in skills?
- **Finding**: **No.** C2 explicitly replaces the old "unreachable-tool lint" with:
  `Invariant: every tool family has a situation-matched skill trigger, and every tool name a skill quotes exists (dangling-name check).`
- **Consistency with E3**: This is conceptually consistent with E3 (which demonstrated that 50.2% of tool loads occurred from bare stubs without prior mention in any skill).
- **Adversarial Defect**: While conceptually consistent, the invariant is **operationally incomplete**:
  - The spec provides no definition, syntax, or registry for "tool families".
  - A static validator cannot verify "situation-matched" without either an explicit declaration (e.g. `covers_families = ["bathos_queries"]`) or an NLP judge.

---

## 7. Comprehensive Dispositions Matrix for Defender (Phase 3 Cycle 1)

The Defender has reviewed Challenger 1's findings with strict technical rigor. All 13 items (**GAP-01 through GAP-13**) represent genuine architectural, boundary, statistical, or runtime gaps and are **CONCEDED**. Each item is paired below with its definitive architectural answer and disposition.

| Item ID | Finding Summary | Spec Section | Challenger Recommendation | Defender Rebuttal / Answer | Disposition |
|---|---|---|---|---|---|
| **GAP-01** | C0 cannot wrap/move `session_context_audit.py` across repo boundaries. | C0 (line 41) | Vendor transcript parsing core into `src/cisternal/usage/` with attribution. | **Conceded**. Cross-repo importing violates packaging isolation and breaks standalone CI checkouts. We specify formal vendoring of the parsing core into `src/cisternal/usage/transcript.py` with upstream attribution to `praxia/scripts/context_audit/session_context_audit.py`. Praxia-specific `CLI_RE` is removed and replaced with generic CLI tool pattern matching. Designated as build prerequisite **Pre-0**. | **CONCEDED** |
| **GAP-02** | Assumption A8 is REFUTED; adapters have heterogeneous error shapes. | A8 (line 36), C0, C5 | Mark A8 as REFUTED; insert Adapter Error Normalization pass before C0 error tracking and C5. | **Conceded**. Direct code verification of `src/cisternal/adapters/base.py:278–388` proves adapters emit incompatible error formats (`MyxcelAdapter` returns `{error, message}`, `XpeririAdapter` returns JSON string, `PassthroughAdapter` raises exceptions, `BathosAdapter` returns dict with `error_code`). We mark A8 as **REFUTED** in the spec with code citations and establish **Pre-1 (Adapter Error Normalization Pass)** in `base.py` defining a canonical `(is_error, error_code, error_message)` inspection contract. | **CONCEDED** |
| **GAP-03** | C5 lacks session state transport to know if MCP errored earlier. | C5 (line 55) | Define session error ledger (`~/.cisternal/sessions/<id>/errors.jsonl`) emitted by adapters and read by hook. | **Conceded**. PreToolUse hook subshells are ephemeral processes without inter-invocation memory. We specify an on-disk ephemeral session error ledger at `~/.cisternal/sessions/<session_id>/errors.jsonl`. Cisternal server telemetry appends a JSON record on each tool error; the hook queries this file by session ID and target tool/family before deciding to emit a nudge. | **CONCEDED** |
| **GAP-04** | Negative controls in C0 and C3 test only zero-counts, risking silent masking. | C0, C3 (lines 42, 47) | Mandate paired positive and negative controls with planted calls and uncalled tools. | **Conceded**. Single-sided zero-count checks are trivially satisfied by broken parsers that exit early or return empty dicts (consistent with the Anthropic `run_eval.py` sandbox failure). We mandate **paired positive and negative controls** in C0 (asserting planted tool calls equal $N=5$ AND uncalled tools equal $0$, with `len(counts) > 0`) and in C3 (asserting detection of planted opportunities alongside zero false positives). | **CONCEDED** |
| **GAP-05** | C4 check (a) compares against a "long form" that does not exist on disk. | C4 (line 50) | Compare compressed trigger against `SKILL.md` body, or specify explicit git baseline ref flag. | **Conceded**. A compressed working-tree file lacks access to historical text without version control references. We specify check (a) as a two-level containment invariant: (1) all strings in `distinctive_strings` must appear in the listing description OR in the `SKILL.md` body; (2) provide an optional CLI flag `--baseline-ref <git-rev>` for differential CI checks against git history. | **CONCEDED** |
| **GAP-06** | C4 checks (b) and (c) lack deterministic static algorithms. | C4 (line 50) | Define deterministic rules: headings/code blocks for claims, explicit `## Scope` heading in first 50 lines. | **Conceded** (with defense of static feasibility). We establish deterministic AST grammar rules: check (b) (No Overclaim) requires all listing topic tokens to match a Markdown section heading (`#`, `##`, `###`) or code block identifier in `SKILL.md` or `references/`; check (c) (Scope Header) requires an explicit `## Scope` or `## When to Use` heading within the first 50 lines (2,000 characters). | **CONCEDED** |
| **GAP-07** | "Tool family" in C2 is undefined and unmodelled in cisternal assets. | C2 (line 45) | Define declarative `families` in `cisternal.toml` and `covers_families` in `SkillAsset`. | **Conceded**. Invariants on undeclared entities cannot be checked in CI. We define a declarative `[families]` manifest schema in `cisternal.toml` (and plugin manifests) mapping tool names/patterns to family identifiers, and add `covers_families: list[str]` to `SkillAsset` frontmatter. C2 verifies full family coverage and checks dangling tool names, retaining E3 consistency (individual tool names need not appear in skills). | **CONCEDED** |
| **GAP-08** | C1 prune list destroys hook-only and skill-only plugins that emit 0 MCP calls. | C1 (line 43) | Add whitelist rule: plugins providing `hook_specs`, `commands`, or standalone skills cannot be dropped. | **Conceded**. Intersecting registered plugins exclusively with MCP call volume would strip developer security hooks and authoring skills. We specify an active registration scanner that inspects plugin manifests for `hook_specs`, `commands`, and standalone skills, automatically whitelisting them from `drop` recommendations. | **CONCEDED** |
| **GAP-09** | C1 lacks retention time horizon, minimum session volume, and project-split rules. | C1 (line 43) | Define minimum threshold ($N \ge 20$ sessions or 14-day lookback) and project-specificity heuristic. | **Conceded**. Recommending pruning based on sparse sessions creates volatile recommendations. We establish a minimum sample threshold of $N \ge 20$ sessions or a 14-calendar-day lookback window before generating prune recommendations, annotating outputs with sample size and confidence intervals. | **CONCEDED** |
| **GAP-10** | Exploratory numbers in E1-E5 are cited as ground truth despite line 19 disclaimer. | Lines 19, 45, 55, 63 | Reframe E1-E5 as Preliminary Motivating Probes; rephrase "E3 falsifies" and "the 57 errors". | **Conceded**. The spec must preserve epistemic humility and avoid internal contradictions. We reframe E1–E5 consistently as **Preliminary Motivating Probes** throughout the document, replacing categorical assertions ("E3 falsifies", "the 57 errors", "discovery is not the bottleneck") with design rationale and parametric error classifications. | **CONCEDED** |
| **GAP-11** | C5 PreToolUse hook risks shell argument overflow and cross-surface schema failure. | C5 (line 55) | Specify Claude Code JSON schema (`{"additionalContext": "..."}`), fail-open semantics, and temp file streaming. | **Conceded**. Hook execution must respect host JSON schema and OS argument bounds (`MAX_ARG_STRLEN` 128 KiB). We specify the exact Claude Code PreToolUse output schema (`{"additionalContext": "<string>"}`), mandate fail-open semantics (`|| exit 0`), and stream context payloads via stdin or temporary files to prevent argument overflow. | **CONCEDED** |
| **GAP-12** | C4 behavioral gate lacks explicit non-inferiority margin $\delta$. | C4 (line 51) | Pre-register non-inferiority margin: $\delta \le 0.05$ at 95% confidence on frozen opportunity set. | **Conceded**. An automated evaluation gate without a pre-registered statistical threshold cannot be objectively evaluated. We pre-register the non-inferiority margin as $\delta \le 0.05$ (5 percentage points) at 95% confidence on the frozen opportunity set: $P(\text{fire} \mid \text{short}) - P(\text{fire} \mid \text{long}) \ge -0.05$. | **CONCEDED** |
| **GAP-13** | Subagent headless execution disparity (A9) unmeasured in C0. | A9 (line 37), C0 | Require C0 to stratify metrics by session type (`main_interactive` vs `subagent_headless`). | **Conceded**. Headless subagents operate with ~26k fewer standing context tokens and execute without user interaction. We specify that C0 must parse session metadata to stratify all metrics by session type: `session_type: "main_interactive" | "subagent_headless"`. | **CONCEDED** |

---

## 8. Defender Resolutions and Architectural Specification (Phase 3 Cycle 1)

This section details the concrete technical resolutions adopted by the Defender to address all 13 conceded gaps, establishing unambiguous implementation blueprints for the revised specification.

### 8.1 Executive Summary of Cycle 1 Resolutions
1. **Packaging & Isolation**: Cross-repository dependence on `praxia` is replaced by vendoring the transcript parsing core into `src/cisternal/usage/transcript.py` with upstream attribution (**Pre-0**).
2. **Error Normalization**: Codebase refutation of Assumption A8 (`base.py:278–388`) is acknowledged; an Adapter Error Normalization pass (**Pre-1**) is inserted to guarantee uniform error classification before C0 error tallies and C5 error suppression are built.
3. **Falsification Rigor**: All single-sided negative controls are upgraded to paired positive and negative controls with planted targets ($N=5$) and zero-expectation probes.
4. **Declarative Architecture**: "Tool families" are formalized via a declarative `[families]` manifest in `cisternal.toml` and a `covers_families` key in `SkillAsset`. The C2 invariant is maintained consistent with E3: tool names need not appear in skills.
5. **Decoupled Verification**: C4 is decomposed into **C4a (Static Honesty Lint)**—executable immediately—and **C4b (Behavioral Non-Inferiority Gate)**—executable once C3 provides the frozen opportunity set with pre-registered margin $\delta \le 0.05$.
6. **Stateless Hook State Bridge**: C5 implements an on-disk session error ledger (`~/.cisternal/sessions/<session_id>/errors.jsonl`), Claude Code PreToolUse output schema (`{"additionalContext": "..."}`), fail-open safety, and stdin/temp-file streaming under 128 KiB.
7. **Epistemic Humility**: Evidence E1–E5 is reframed consistently as Preliminary Motivating Probes.

---

### 8.2 Detailed Technical Blueprint

#### 1. Prerequisite Pre-0: Vendoring Core Parser (`src/cisternal/usage/transcript.py`)
- **Upstream Source**: `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`
- **Vendored Location**: `src/cisternal/usage/transcript.py`
- **Attribution**: Header docstring crediting Praxia `session_context_audit.py` (MIT License).
- **Refactoring Scope**:
  - Strip praxia-specific `CLI_RE = re.compile(r"^(?:rtk\s+)?praxia(?:\.py)?\s+([a-z0-9_-]+)")`.
  - Introduce generic CLI invocation parser: `parse_cli_command(cmd: str) -> tuple[str, str]` returning `(binary_name, subcommand)`.
  - Maintain transcript JSONL streaming reader supporting Claude Code session transcript schema (including `deferred_tools_*`, `tool_use`, `tool_result`, `skill_listing`, `invoked_skills`).

#### 2. Prerequisite Pre-1: Adapter Error Shape Normalization Pass (`src/cisternal/adapters/base.py`)
- **Refutation Evidence**: `src/cisternal/adapters/base.py:278–388`:
  - `BathosAdapter.shape_error`: returns `dict` with `{"ok": False, "error_code": "INTERNAL", ...}`.
  - `PassthroughAdapter.shape_error`: re-raises `exc` directly (`raise exc`).
  - `ContemplexAdapter.shape_error`: returns `contemplex.errors.err_envelope(...)`.
  - `XpeririAdapter.shape_error`: returns JSON string `json.dumps({"ok": False, "error": str(exc)}, sort_keys=True)`.
  - `MyxcelAdapter.shape_error`: returns `{"error": type(exc).__name__, "message": str(exc)}` (lacks `ok` and `error_code`).
- **Normalization Specification**:
  - Implement on `AdapterBase`:
    ```python
    @dataclass(frozen=True)
    class NormalizedError:
        is_error: bool
        error_code: str
        error_message: str
        resolution_hint: str | None = None

    class AdapterBase(ABC):
        ...
        @abstractmethod
        def normalize_error(self, raw_result: Any) -> NormalizedError:
            """Inspect raw adapter return and extract a normalized error representation."""
            ...
    ```
  - Subclasses must parse their respective formats:
    - `BathosAdapter`: parses `dict` keys `ok`, `error_code`, `error`.
    - `ContemplexAdapter`: unpacks `err_envelope` structure.
    - `XpeririAdapter`: deserializes JSON string before checking `ok` and `error`.
    - `MyxcelAdapter`: recognizes `{"error": ..., "message": ...}` as `is_error=True` with `error_code="MYXCEL_ERROR"`.
    - `PassthroughAdapter`: wraps caught exceptions into `NormalizedError(is_error=True, error_code=type(exc).__name__, error_message=str(exc))`.

#### 3. Component C0: Tracked Usage Counter
- **Source of Truth**:
  - Client side: Claude Code JSONL transcripts discovered under `~/.claude/projects/*/` and subagent run directories.
  - Server side: Cisternal JSONL logs (`~/.cisternal/logs/` or `CISTERNAL_LOG_DIR`).
  - Normalized error stream from Pre-1.
- **Session Type Stratification**:
  - Every session is parsed for session type: `session_type: "main_interactive" | "subagent_headless"`.
  - Reports output metrics split by stratum:
    - Main interactive sessions: user-facing command-line vs MCP tool ratios.
    - Subagent headless sessions: agent-to-agent dispatch tool usage under reduced standing context.
- **Paired Positive and Negative Controls**:
  - Fixture: `tests/fixtures/usage/synthetic_transcript.jsonl` with:
    - Exactly 5 planted calls to `mcp__bathos__run_sql`.
    - Exactly 3 calls to CLI `bth sql`.
    - Exactly 0 calls to uncalled tool `mcp__bathos__planted_uncalled`.
  - Invariant assertion:
    - Assert `counts["mcp__bathos__run_sql"] == 5`.
    - Assert `counts["bth sql"] == 3`.
    - Assert `counts.get("mcp__bathos__planted_uncalled", 0) == 0`.
    - Assert `len(counts) >= 2` (guards against silent empty dictionary returns).

#### 4. Component C1: Prune List
- **Source of Truth**:
  - Active registrations: `~/.claude/settings.json`, `~/.claude.json`, and plugin manifests in installed plugins directories.
  - Intersected with C0 usage counters.
- **Active Asset Whitelist**:
  - Registration scanner checks plugin manifests for:
    - `hook_specs` (active PreToolUse, PostToolUse, or commit hooks).
    - `commands` (CLI extensions).
    - `skills` (standalone prompt skills without MCP tools).
  - Rule: If a plugin exports any active hook, command, or skill, it **CANNOT** be classified as `drop`, regardless of whether MCP tool call volume is 0.
- **Sample Size Horizon**:
  - Minimum sample window: $N \ge 20$ sessions or 14 calendar days.
  - If $N < 20$, C1 outputs: `Sample size too low (N={N} < 20). Prune recommendations suppressed; reporting usage tallies only.`
- **Output Buckets**:
  - `keep`: High-usage MCP tools or plugins with active non-MCP assets (hooks/skills).
  - `drop`: 0 MCP calls over $N \ge 20$ sessions AND 0 non-MCP assets.
  - `enable-per-project`: MCP tools used exclusively in $\ge 80\%$ of sessions within a specific repository workspace.

#### 5. Component C2: Guidance-Coverage Lint
- **Declarative Family Manifest**:
  - In `cisternal.toml` (and plugin manifests):
    ```toml
    [families]
    bathos_query = ["mcp__bathos__run_sql", "mcp__bathos__get_run", "mcp__bathos__find_runs"]
    bathos_lineage = ["mcp__bathos__lineage_prov", "mcp__bathos__cite_run"]
    contemplex_brainstorm = ["brainstorm_start", "brainstorm_reply", "brainstorm_finalize"]
    ```
- **Skill Asset Schema Extension**:
  - In `src/cisternal/assets/skill_schema.py`:
    ```python
    covers_families: list[str] = Field(default_factory=list, description="Declared tool families guided by this skill")
    ```
- **Static Invariants Checked in `cisternal assets validate`**:
  1. *Complete Family Coverage*: Every tool declared in `[families]` must be covered by at least one skill having that family in `covers_families`.
  2. *Dangling Tool Name Check*: Any tool name explicitly quoted in skill text (e.g. `mcp__<server>__<tool>`) must exist in the registered tool portfolio.
  3. *E3 Consistency Preserved*: Individual tool names are **NOT** required to appear in skill text. Bare stub invocation via deferred listings remains supported.

#### 6. Component C3: Skill Coverage Tooling
- **Distinctive Strings Schema**:
  - In `src/cisternal/assets/skill_schema.py`:
    ```python
    distinctive_strings: list[str] = Field(
        default_factory=list,
        min_length=1,
        max_length=5,
        description="2 to 5 specific domain tokens or CLI triggers uniquely identifying opportunities for this skill"
    )
    ```
- **Opportunity Definition**:
  - A user turn or bash execution containing any string in `distinctive_strings` within a session.
- **Hand-Labelled Precision Threshold**:
  - Heuristic opportunity matching must achieve precision $\ge 0.80$ against a frozen hand-labelled evaluation sample of 50 session turns before opportunity counts are accepted as evaluation ground truth.
- **Frozen Situation Set**:
  - C3 outputs a serialized opportunity set (`tests/fixtures/eval/frozen_situations.jsonl`) pairing prompts/user contexts with the binary outcome of whether the skill was triggered.

#### 7. Component C4: Progressive-Disclosure Honesty Verification
Decomposed into C4a (Static Lint) and C4b (Behavioral Gate):

- **C4a: Static Honesty Lint** (Runs in `assets validate`, blocked only on schema):
  - **Check (a) (No Loss / Containment)**:
    - Every string in `distinctive_strings` must appear in the frontmatter description (`when_to_use` / `description`) OR in the Markdown body of `SKILL.md`.
    - Optional CLI flag: `assets validate --baseline-ref <git-commit>` checks that all distinctive strings present in git baseline frontmatter remain present in the current description or body.
  - **Check (b) (No Overclaim)**:
    - Extract candidate topic tokens from the listing description. Every topic token must match at least one section heading (`#`, `##`, `###`) or code block identifier in `SKILL.md` or a file under `references/`.
  - **Check (c) (Scope Header)**:
    - `SKILL.md` must declare an explicit `## Scope` or `## When to Use` section within the first 50 lines (2,000 characters).
- **C4b: Behavioral Non-Inferiority Gate** (Runs via C3 on frozen situation set):
  - Pre-registered non-inferiority margin: $\delta \le 0.05$ (5 percentage points) at 95% confidence.
  - For a shortened description versus baseline:
    $$P(\text{fire} \mid \text{short}) - P(\text{fire} \mid \text{long}) \ge -0.05$$
  - Evaluated via Wilson score confidence interval of the proportion difference on the C3 frozen opportunity set.

#### 8. Component C5: Verb-to-Tool Nudge Hook
- **State Bridge: Ephemeral Session Error Ledger**:
  - Location: `~/.cisternal/sessions/<session_id>/errors.jsonl`.
  - Emitted by: Cisternal server telemetry / `AdapterBase.normalize_error` upon any failed MCP tool execution.
  - Schema: `{"timestamp": "2026-11-06T19:00:00Z", "tool_name": "mcp__bathos__run_sql", "family": "bathos_query", "error_code": "INTERNAL", "message": "..."}`.
- **PreToolUse Hook Execution Protocol**:
  - Trigger: Bash tool invocation matching a mapped CLI verb (e.g. `bth sql`).
  - Step 1: Hook resolves active `session_id` from environment or process tree.
  - Step 2: Hook checks `~/.cisternal/sessions/<session_id>/errors.jsonl`. If any error record exists for the corresponding MCP tool or family within the current session, hook suppresses the nudge and exits immediately (`exit 0`).
  - Step 3: If no prior error, hook outputs Claude Code JSON:
    ```json
    {
      "additionalContext": "Recommendation: An equivalent MCP tool is available: 'mcp__bathos__run_sql'. Consider using it for structured telemetry and faster execution."
    }
    ```
- **Shell Limits & Safety**:
  - Hook must enforce fail-open semantics: any unexpected exception, missing ledger, or JSON failure must execute `exit 0` with no stdout.
  - To respect Linux `MAX_ARG_STRLEN` (128 KiB limit), all formatted guidance text is streamed via temporary files or stdin into `cat`, avoiding `jq --arg` overflow.

#### 9. Component C6: `triage-tool` Skill
- **Path**: Located in `src/cisternal/assets/skills/triage-tool/SKILL.md`.
- **Trigger**: $\le 150$ characters ("Use when auditing agent MCP/skill use or pruning unused tool servers before changing project settings.")
- **Safety Invariant**: Strictly non-destructive. Outputs human-readable recommendations; contains no commands or instructions modifying `~/.claude/settings.json` automatically.

---

### 8.3 Revised Build Order & Dependency Graph

```
               +-------------------------------------------------+
               | Pre-0: Vendor transcript parsing into cisternal |
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
                      └─────────────────┼───────────────────────────────────┘
                                        │
                                        ▼
                        +-------------------------------+
                        | C4b: Behavioral Non-Inferior  |
                        | (Fire-rate on Frozen Set, δ)  |
                        +-------------------------------+
                                        │
                                        ▼
                        +-------------------------------+
                        |  C6: triage-tool Skill Build  |
                        | (Trigger <= 150c, References) |
                        +-------------------------------+
                                        │
                                        ▼
                        +-------------------------------+
                        |   C5: Verb-to-Tool Nudge Hook |
                        | (Session Error State Ledger)  |
                        | (Matched-Session A/B Harness) |
                        +-------------------------------+
```

---

### 8.4 Epistemic Alignment & Reframing of E1–E5 Probes

To eliminate epistemic circularity, all references in the specification are aligned as follows:
1. **Preliminary Motivating Probes**: E1–E5 are explicitly designated as *preliminary motivating probes* derived from untracked exploratory scripts. They illustrate problem patterns but are not cited as immutable proof.
2. **Parametric Rationale**:
   - The phrase `E3 falsifies "name must appear in a skill"` is replaced with: `Motivated by probe E3, which observed 50.2% of tool loads occurring from bare stubs, C2 does not require tool names to appear in skills.`
   - The phrase `classify the 57 errors` is replaced with: `classify observed error paths (e.g. timeout/stdio vs validation error) before shipping.`
   - The assertion `discovery is not the bottleneck` is reframed to: `prioritize situation-matched triggers and CLI nudge hooks over unguided keyword search.`

---

### 8.5 Cycle 1 Spec Mutation Summary

All agreed resolutions have been directly incorporated into `/home/marielle/projects/cisternal/.claude/worktrees/261106-agy-spec-cycles/.praxia/docs/specs/261106_tool-surface-triage.md`:
- Added comprehensive `## Changelog` detailing Cycle 1 revisions.
- Updated Assumption A8 to **REFUTED** with verbatim code citations.
- Updated C0 with Pre-0 vendoring, paired positive/negative controls, and session-type stratification.
- Updated C1 with active registration scanner, non-MCP plugin whitelisting, and $N \ge 20$ lookback window.
- Updated C2 with declarative `[families]` manifest schema, `covers_families` frontmatter attribute, and E3 consistency.
- Updated C3 with `distinctive_strings` schema, precision $\ge 0.80$ threshold, and frozen situation set output.
- Split C4 into C4a (Static Honesty Lint) and C4b (Behavioral Non-Inferiority Gate with $\delta \le 0.05$).
- Updated C5 with Pre-1 adapter normalization dependency, session error ledger, Claude Code output schema, and temp-file streaming.
- Updated Section Order and Dependency Graph to reflect `Pre-0 -> Pre-1 -> C0 -> (C1, C2) -> (C4a, C3) -> C4b -> C6 -> C5`.

