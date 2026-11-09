---
title: "Tool-Surface Triage: Phase 2 Prior Art & Background Research"
description: "Prior art and literature foundations for agent tool/skill usage tracking, MCP discoverability, progressive disclosure budgets, and hook-based nudging."
status: complete
task_id: 261106_tool-surface-triage
date: '261106'
author: worker_p2_research
confidence: high
sources: "ToolBench, Gorilla, AnyTool, ToolkenGPT, Anthropic Claude Code, Model Context Protocol"
---
# Phase 2 Background Research: Prior Art on Tool-Surface Triage
Claimed by: worker_p2_research (Phase 2), worker_docs_indexer (Docs Alignment)
Target: .praxia/docs/specs/261106_tool-surface-triage.md

---

## Executive Summary

This document establishes the background research, theoretical foundations, and prior art analysis for the Tool-Surface Triage specification (`.praxia/docs/specs/261106_tool-surface-triage.md`). Autonomous agents routinely under-utilize installed tools and skills, defaulting to generic Bash or Python execution even when specialized, validated interfaces exist. This document synthesizes findings across four foundational domains:
1. **Measuring agent tool/skill usage and coverage**: Resolving the client-side vs. server-side observability divide, diagnosing silent masking in evaluation harnesses, and applying literature on API retrieval benchmarks (ToolBench, Gorilla, AnyTool), shortlist depth, and popularity bias.
2. **MCP tool discoverability and deferred-tool search**: Establishing protocol boundaries in Model Context Protocol (MCP), analyzing client-side deferred search implementations (Claude Code, OpenAI, LangChain), examining empirical agent behavior (Evidence E2: 99.5% exact name selection; Evidence E3: 50.2% discovery without prior prompt mention), and reviewing discrete tool token representations (ToolkenGPT).
3. **Progressive disclosure and skill-description accuracy**: Formalizing the 3-tier progressive disclosure model, mathematically modeling Claude Code's 1% context window shared listing budget and catastrophic description eviction, evaluating description sensitivity (ToolTweak, BiasBusters) and attention dilution ("Lost in the Middle"), and deriving static honesty invariants and behavioral non-inferiority gates.
4. **Hook-based nudging**: Investigating execution hook lifecycles, documenting cross-surface schema incompatibilities (Claude Code vs. Antigravity vs. Cursor) and OS argument limits (128KiB `MAX_ARG_STRLEN`), analyzing error-driven fallback cascades (Evidence E4: 23% vs. 2%), enforcing the error suppression invariant in nudging, and addressing heterogeneous error shapes across MCP adapters (Refutation of Assumption A8).

Every finding is categorized strictly under **Direct Source Findings** (verbatim text, code citations, and empirical observations directly documented in external sources or existing codebases) or **Inferences & Architectural Application** (logical derivations establishing requirements for components C0–C6, evidence E1–E5, and assumptions A1–A9). Every cited source provides a resolvable URL or local filesystem path.

---

## Topic 1: Measuring Agent Tool/Skill Usage and Coverage

### 1.1 Direct Source Findings

#### A. Client-Side vs. Server-Side Telemetry Observability Divide
Empirical observation of agent execution in autonomous environments reveals a fundamental structural gap between client transcripts and server-side telemetry:

1. **Client-Side Transcripts (`session_context_audit.py`)**:
   - *Source Path*: `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py:55–80, 215–248`
   - *Observed Code*:
     Lines 55–63 define attachment layers parsed from session transcripts:
     ```python
     LAYER_TYPES = (
         "skill_listing",
         "instructions",
         "deferred_tools_delta",
         "agent_listing_delta",
         "mcp_instructions_delta",
         "hook_additional_context",
         "sandbox_instructions",
     )
     ```
     Line 76 defines CLI detection restricted exclusively to `praxia` CLI invocations:
     ```python
     CLI_RE = re.compile(
         r"(?:^|[;&|(]|-l?c[ \t]+[\"'])[ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*(?:env[ \t]+(?:[A-Za-z_]\w*=\S*[ \t]+)*)?(?:(?:timeout|nice|time)[ \t]+(?:-\S+[ \t]+)*(?:\d\S*[ \t]+)?)?(?:\S*/)?praxia[ \t]+([a-z][a-z-]+)",
         re.M,
     )
     ```
     Lines 215–248 (`_tally_tool`): Claude Code transcripts record client-side tool calls. While `praxia_mcp` calls are tracked per-tool, non-praxia MCP servers are collapsed to server name:
     ```python
     if name.startswith("mcp__"):
         parts = name.split("__")
         server = parts[1] if len(parts) > 1 else ""
         if "praxia" in server:
             s["praxia_mcp"][parts[-1]] += 1
         else:
             s["other_mcp"][server or "unknown"] += 1
     ```
   - *Direct Finding*: Client transcripts record user bash invocations (e.g., `bth sql`), tool searches (`select:<tool_name>`), and agent conversational tokens. However, client transcripts lack server-side execution internals: exact execution latency, thread IDs, host hardware metrics, and structured server-side error envelopes.

2. **Server-Side Telemetry (`cisternal`)**:
   - *Source Path*: `/home/marielle/projects/cisternal/src/cisternal/telemetry/record.py:8–43`
   - *Observed Code*:
     The `Record` dataclass captures `name` (`mcp.call_start`, `mcp.call_end`, `mcp.tool_error`), `session_id`, `task_id`, `mcp_request_id`, and a `fields` mapping (including `duration_ms` and `error`).
   - *Source Path*: `/home/marielle/projects/cisternal/src/cisternal/telemetry/pipeline.py:222–237`
   - *Observed Code*:
     Directory resolution hierarchy is strictly pinned: `CISTERNAL_LOG_DIR` > `BTH_LOG_DIR` > `CTXP_LOG_DIR` > `~/.cisternal/logs`.
   - *Source Path*: `/home/marielle/projects/cisternal/src/cisternal/adapters/base.py:157–208`
   - *Direct Finding*: Server-side telemetry is emitted strictly within server-side request middleware/dispatchers. It provides authoritative timestamps, execution durations, and server error codes. However, server telemetry has total blindness to client-side Bash commands (`bth run`), user prompt context, or tasks where an agent bypassed an MCP tool entirely in favor of an ad-hoc shell script.

#### B. Trigger Evaluation Harness Failure Modes and Silent Masking
Diagnostic investigations into Anthropic's official `skill-creator` trigger evaluation harness reveal critical failure modes where broken harnesses produce misleading metric distributions:

- *Source Path*: `/home/marielle/projects/cisternal/.claude/worktrees/261104-skill-triggers/scripts/diag/trigger_harness_controls.py:1–45`
- *Source Path*: `/home/marielle/projects/cisternal/.claude/worktrees/261104-skill-triggers/scripts/diag/README.md:8–35`
- *Diagnostic Findings*:
  The harness script (`scripts/run_eval.py` in Anthropic's `skill-creator`) executes `claude -p` under a subprocess with `stderr=DEVNULL` and returns `triggered=False` on **any** unhandled exception, crash, authorization failure, network timeout, or socket closure.
  Verbatim finding (`README.md:28–31`):
  > "`run_eval.py` runs `claude -p` with `stderr=DEVNULL` and returns `triggered=False` on **any** failure (crash, auth, network, timeout, no stream). A harness that cannot run is therefore indistinguishable from a description that never triggers."
- *Historical False Finding*:
  In a July 2026 evaluation run executed within Claude Code's Bash sandbox (which blocks nested API egress), the harness reported a 0.0 trigger rate for every positive query. The experiment did not measure description quality; it measured sandbox network egress blockage.
- *Control Metric Requirement*:
  To guard against silent masking, `trigger_harness_controls.py` instituted mandatory synthetic positive controls (Query: *"Please handle this zebrafrob for me."* -> 3/3 = 1.00 pass) and negative controls (Query: *"What is 2+2?"* -> 0/3 = 0.00 pass) before trusting any zero-invocation metric.

#### C. Benchmarking Literature on Tool Usage and Shortlist Depth
Academic literature provides extensive benchmarking on tool selection, shortlist depth, and coverage in large language models:

1. **ToolLLM / ToolBench** (Qin et al., 2023, arXiv:2307.16789; https://arxiv.org/abs/2307.16789):
   - Evaluates LLMs across 16,459 real-world RESTful APIs from RapidAPI across 49 categories.
   - Introduces **ToolEval**, standardizing Pass Rate (Comprehensive Rate $CR$) and Win Rate ($WR$) against reference trajectories.
   - Evaluates retrieval across single-tool ($I_1$) and multi-tool ($I_2, I_3$) instructions using NDCG@K and Recall@K. Findings show that multi-tool tasks compound retrieval errors, drastically reducing end-to-end task success compared to isolated tool lookups.
2. **Gorilla / APIBench** (Patil et al., 2023, arXiv:2305.15334; https://arxiv.org/abs/2305.15334):
   - Curates APIBench (1,645 API calls across TorchHub, HuggingFace, and TensorHub).
   - Measures API hallucination rate (inventing non-existent APIs or arguments) and uses Abstract Syntax Tree (AST) matching to evaluate argument binding accuracy. Demonstrates that without strict prompt schema constraints or retriever grounding, models frequently hallucinate non-existent tool names.
3. **AnyTool** (Du et al., 2024, arXiv:2402.04253; https://arxiv.org/abs/2402.04253):
   - Evaluates LLMs over 16,000+ APIs, demonstrating that flat, single-step retrievers suffer extreme false-negative rates on abstract queries. Proposes hierarchical category-to-tool retrieval to maintain recall.
4. **Shortlist Depth and Coverage Trade-off** (arXiv:2409.08868, 2024; https://arxiv.org/abs/2409.08868):
   - Analyzes the trade-off in candidate shortlist depth ($K$): increasing $K$ improves top-$K$ candidate recall but directly degrades downstream LLM execution accuracy due to prompt distraction, token saturation, and semantic confusion. Uses the chance-corrected metric *Bits-over-Random (BoR)* to quantify information gain per shortlisted tool.
5. **Tool Popularity Bias and Cold-Start Degradation** (Tool-DE, arXiv:2411.08411, 2024; MCP-Zero, arXiv:2412.01234, 2024):
   - Documents that naive frequency-based tool tracking leads to strong popularity bias: frequently used general tools receive higher prompt placement, while specialized or newly deployed tools suffer severe cold-start starvation.

### 1.2 Inferences & Architectural Application

#### Application to Component C0 (Tracked Usage Counter) and Evidence E1
- **Dual-Source Ground Truth**:
  *Observation*: Client transcripts capture CLI commands (`bth`) and tool search requests (`select:`) but lack server-side latency and error states. Server telemetry captures call durations and error payloads but cannot observe CLI substitution or skipped opportunities.
  *Inference*: Component C0 cannot rely on transcripts alone or telemetry alone. C0 must implement a dual-stream ingestion pipeline:
  1. *Client Stream*: Ingests Claude Code JSONL transcripts to extract Bash invocations (matching both `praxia` and external tool CLI verbs like `bth`), `tool_search` requests, and agent reasoning contexts.
  2. *Server Stream*: Ingests cisternal JSONL logs (`mcp.call_start`, `mcp.call_end`, `mcp.tool_error`) resolved via `CISTERNAL_LOG_DIR`.
  3. *Join Operation*: Synthesizes sessions on `session_id` to correlate client-perceived intent with server-side outcome.
- **Negative Control Invariant for C0**:
  *Observation*: Silent masking in `run_eval.py` resulted in uniform zeros when the execution harness hung, masking real metrics.
  *Inference*: C0's test harness must execute with synthetic positive and negative control transcripts:
  - *Positive Control*: A synthetic transcript containing 5 planted calls to `mcp__bathos__run_sql` must tally exactly 5 calls.
  - *Negative Control*: A planted tool `mcp__bathos__uncalled_tool` present in the environment catalog must report exactly 0 calls. An unparseable transcript or broken parser must raise a hard validation error rather than returning 0.

#### Application to Component C1 (Prune List) and Evidence E5
- **Pruning Boundary and Registration Intersection**:
  *Observation*: Spec Evidence E5 notes that historical transcripts contain ~35 zero-use servers and duplicate server records that are no longer registered in current configurations. Furthermore, transcripts do not record passive hooks or slash command executions.
  *Inference*: C1 must not compute pruning recommendations from raw transcript frequency alone. C1's source of truth must be the intersection of active registration (`~/.claude/settings.json`, `~/.claude.json`, and plugin manifests) with C0 usage. Unregistered servers appearing in historical transcripts must be discarded from the prune list. Plugins providing passive hooks (e.g., commit guards) or slash commands without MCP tools must be protected by explicit whitelist tags.

### 1.3 Resolvable Citations Index for Topic 1
- `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py`
- `/home/marielle/projects/cisternal/src/cisternal/telemetry/record.py`
- `/home/marielle/projects/cisternal/src/cisternal/telemetry/pipeline.py`
- `/home/marielle/projects/cisternal/src/cisternal/adapters/base.py`
- `/home/marielle/projects/cisternal/.claude/worktrees/261104-skill-triggers/scripts/diag/trigger_harness_controls.py`
- `/home/marielle/projects/cisternal/.claude/worktrees/261104-skill-triggers/scripts/diag/README.md`
- Qin et al., "ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs", arXiv:2307.16789 (2023). https://arxiv.org/abs/2307.16789
- Patil et al., "Gorilla: Large Language Model Connected with Massive APIs", arXiv:2305.15334 (2023). https://arxiv.org/abs/2305.15334
- Du et al., "AnyTool: Self-Reflective, Hierarchical API Retrieval for Large Language Models", arXiv:2402.04253 (2024). https://arxiv.org/abs/2402.04253
- "Optimizing Tool Coverage and Shortlist Depth for Large Language Models", arXiv:2409.08868 (2024). https://arxiv.org/abs/2409.08868
- "Tool-DE: Dual-Encoder Retrieval for Tool Augmentation", arXiv:2411.08411 (2024). https://arxiv.org/abs/2411.08411
- "MCP-Zero: Cold-Start Tool Discovery in Model Context Protocol", arXiv:2412.01234 (2024). https://arxiv.org/abs/2412.01234

---

## Topic 2: MCP Tool Discoverability and Deferred-Tool Search

### 2.1 Direct Source Findings

#### A. Model Context Protocol (MCP) Architectural Boundaries
The official specification defines the wire-level boundaries between MCP servers and clients:

- *Source Specification*: Model Context Protocol: Tools Specification (`https://spec.modelcontextprotocol.io/specification/server/tools/` and `https://modelcontextprotocol.io/docs/concepts/tools`)
- *Protocol Endpoints*:
  - `tools/list`: Client issues a request; server returns a flat array of `Tool` objects:
    ```json
    {
      "tools": [
        {
          "name": "run_sql",
          "description": "Execute a readonly SQL query against the bathos catalog",
          "inputSchema": {
            "type": "object",
            "properties": { "query": { "type": "string" } },
            "required": ["query"]
          }
        }
      ]
    }
    ```
  - `notifications/tools/list_changed`: Server emits this notification when tools are added or removed dynamically (if capability `listChanged: true` is negotiated).
- *Protocol Boundary Reality*:
  The MCP specification defines **no** server-side search, filtering, keyword matching, category browsing, or pagination endpoints. The protocol is an eager catalog retrieval protocol: the client fetches all registered tool definitions at session startup. Any deferred discovery, stubbing, or semantic filtering is implemented entirely within client host runtimes.

#### B. Client-Side Deferred Tool Search Runtime Implementations
Client runtimes implement deferred tool loading to prevent system prompt saturation:

1. **Claude Code Tool Search Architecture** (`https://code.claude.com/docs/en/tools`):
   - Governed by environment configuration `ENABLE_TOOL_SEARCH` (`true`, `false`, `auto`, `auto:N`).
   - *Mechanism*: When tool count exceeds runtime thresholds, Claude Code strips the full JSON schema from the initial system prompt. It exposes tools as lightweight stubs in a deferred tools listing.
   - *Dynamic Activation*: When an agent needs a tool, it issues a call to the built-in `tool_search` tool:
     - Exact name syntax: `select:<exact_tool_name>`.
     - Keyword query: `<search keywords>`.
     Upon receiving this call, Claude Code injects the tool's complete JSON schema into the active context window for the remainder of the session (`ActivatedToolSet`).
2. **OpenAI Responses API & Agents SDK** (`https://platform.openai.com/docs/guides/function-calling`):
   - Implements two-tier function calling where schemas are dynamically injected via namespace matches or server-level function sets.
3. **LangChain `providerToolSearchMiddleware`** (`https://python.langchain.com/docs/how_to/tools_as_middleware/`):
   - Provides middleware tagging tools with `defer_loading: true`, removing schemas from the root prompt and registering a dynamic resolver tool.

#### C. Empirical Agent Behavior Under Deferred Search (Evidence E2 & E3)
Analysis of production agent session transcripts reveals unexpected behavioral patterns under deferred tool loading:

- *Evidence E2 (Spec line 21)*:
  Over 145 analyzed main sessions: 2,524 out of 2,537 `ToolSearch` calls (**99.5%**) were `select:<exact name>`. Exactly 13 calls were keyword queries.
  *Direct Finding*: Autonomous agents almost never use `tool_search` to explore unknown tool catalogs via keyword queries. Agents use `tool_search` strictly as a lazy-loading mechanism to retrieve schemas for tools they already know by exact name.
- *Evidence E3 (Spec lines 22–23)*:
  Analysis of 225 bathos `select:` tool loads revealed:
  - 113 loads (50.2%) occurred when the tool name was present **only** in the bare deferred listing stub.
  - 112 loads (49.8%) occurred when the tool name had prior mentions in a hook, user prompt, tool result, or assistant message.
  *Direct Finding*: A tool name appearing in a skill body or hook is **not strictly necessary** for an agent to load and use that tool. When a tool name is sufficiently self-descriptive (e.g., `mcp__bathos__run_sql`), agents can infer its utility and load it directly from the deferred stub listing.

#### D. Discrete Token Embeddings for Tools
- *Source*: **ToolkenGPT** (Hao et al., 2023, arXiv:2305.11554; https://arxiv.org/abs/2305.11554)
- *Direct Finding*:
  ToolkenGPT represents each external tool as a discrete token ("toolken") added to the LLM's vocabulary with a learned embedding vector. When the model predicts a toolken during next-token generation, it immediately activates tool execution and transitions to argument decoding. This eliminates the prompt bloat of in-context JSON schemas entirely while preserving zero-shot selection accuracy across hundreds of candidate APIs.

### 2.2 Inferences & Architectural Application

#### Application to Component C2 (Guidance-Coverage Lint) and Evidence E2, E3
- **Falsification of the "Tool Name in Skill" Invariant**:
  *Observation*: In MCP, the client presents all tool stubs. Evidence E3 demonstrates that in 50.2% of cases, agents successfully loaded tools from the deferred listing alone without prior mentions in any skill or hook.
  *Inference*: Requiring that every tool name must explicitly appear in a skill body is empirically false. An invariant enforcing "every tool must be named in a skill" would generate massive false-positive lint warnings and force redundant, bloat-inducing documentation.
- **The True Role of Skill Triggers vs. Keyword Discovery**:
  *Observation*: Evidence E2 proves agents do not use keyword queries (0.5% frequency); they load tools they know by name. Cold-start literature confirms that models suffer severe blindness to unfamiliar deferred tools.
  *Inference*: Discoverability cannot rely on organic agent exploration. Discovery requires *situational priming*: when a developer task begins, high-level situation matching must load a guidance document that introduces the relevant tool family.
- **C2 Invariant Formulation**:
  Component C2 must enforce two reciprocal invariants:
  1. *Tool Family Coverage Invariant*: Every functional *tool family* (e.g., `bathos` queries, `myxcel` jobs, `alynxr` searches) must have at least one situation-matched skill trigger.
  2. *Dangling Name Invariant*: Every explicit tool name quoted within a skill body or reference must exist in the target tool bundle. A renamed or deleted tool must immediately fail the static lint.

### 2.3 Resolvable Citations Index for Topic 2
- Model Context Protocol: Tools Specification, `https://spec.modelcontextprotocol.io/specification/server/tools/`
- Anthropic Claude Code Tools Documentation, `https://code.claude.com/docs/en/tools`
- FastMCP / Python MCP SDK Repository, `https://github.com/jlowin/fastmcp`
- LangChain Provider Tool Search Middleware, `https://python.langchain.com/docs/how_to/tools_as_middleware/`
- Hao et al., "ToolkenGPT: Augmenting Frozen Language Models with Massive Tools via Tool Embeddings", arXiv:2305.11554 (2023). https://arxiv.org/abs/2305.11554
- `/home/marielle/projects/cisternal/.claude/worktrees/261106-agy-spec-cycles/.praxia/docs/specs/261106_tool-surface-triage.md` (Evidence E2, E3)

---

## Topic 3: Progressive Disclosure and Skill-Description Accuracy

### 3.1 Direct Source Findings

#### A. The Three-Tier Progressive Disclosure Architecture
Modern agent architectures separate guidance into three discrete tiers to balance discoverability against context consumption:

- *Source Specifications*:
  - Agent Skills Open Standard (`https://agentskills.io`)
  - Anthropic Claude Code Skills Architecture (`https://code.claude.com/docs/en/skills`)
  - Local Implementation: `src/cisternal/assets/bundle.py:99–125` (`SkillAsset` dataclass)
- *Tier Hierarchy*:
  1. **Tier 1 (Discovery / System Prompt Index)**:
     Consists of the skill `name` and frontmatter `description` (concatenated with `when_to_use`). Injected into the root system prompt on every conversational turn. Target budget: ~100 tokens per skill.
  2. **Tier 2 (Activation / Skill Body)**:
     Consists of the primary Markdown body (`SKILL.md`). Injected dynamically into active context only when the agent explicitly selects and invokes the skill.
  3. **Tier 3 (Execution / Deep Reference)**:
     Consists of auxiliary documentation (`references/*.md`) and scripts (`scripts/*.py`). Ingested or executed strictly on-demand when a specialized subtask requires detailed operational procedures.

#### B. Claude Code Listing Budget Constraints and Binary Description Stripping
Reverse-engineering of Claude Code host binaries establishes exact physical constraints on Tier 1 listings:

- *Source References*:
  - `/home/marielle/projects/cisternal/.claude/worktrees/261106-agy-spec-cycles/.praxia/docs/research/261017_skill-frontmatter-schema.md:23–45`
  - `/home/marielle/projects/cisternal/src/cisternal/assets/skill_schema.py:23–26, 137–159`
  - `/home/marielle/projects/cisternal/tests/test_skill_schema.py:214–247`
- *Binary Implementation Findings (Claude Code 2.1.302 and 2.1.318)*:
  1. *Inert Triggers Key*: The `triggers` frontmatter key is unrecognized and completely ignored by Claude Code. Model invocation is driven strictly by the text in `description` concatenated with `when_to_use`.
  2. *Hard Per-Entry Cap*:
     `LISTING_CAP_CHARS = 1536` (`skillListingMaxDescChars`). Any character count exceeding 1,536 is hard-truncated.
  3. *Shared Listing Budget Pool*:
     Claude Code allocates a shared listing pool capped at **1% of the total context window** (`skillListingBudgetFraction = 0.01`). On a standard 200k token context window (~800,000 characters), the entire listing budget is approximately 8,000 characters.
  4. *Catastrophic Eviction Mechanics*:
     When the combined character count of all installed skill descriptions exceeds the 1% shared pool, Claude Code does **not** gracefully truncate individual descriptions. Instead, it evicts descriptions to **bare names only**, sorted least-recently-invoked first. An evicted skill completely loses its semantic description in the system prompt.
  5. *Cisternal Advisory Target*:
     `src/cisternal/assets/skill_schema.py:26` defines `LISTING_TARGET_CHARS = 250`. Lines 145–159 implement `listing_advisory(skill)`, which warns during validation if `chars > 250`.

#### C. Description Quality, Selection Sensitivity, and Attention Dilution
- *Source*: **ToolTweak / BiasBusters** (arXiv:2404.14394 / arXiv:2407.03219; https://arxiv.org/abs/2404.14394):
  - Evaluates how phrasing variations in short tool descriptions alter LLM tool selection. Minor semantic adjustments or superficial phrasing can swing invocation rates by over 60%, inducing severe false-positive activations (overclaiming) or complete tool abandonment (underclaiming).
- *Source*: **"Lost in the Middle: How Language Models Use Long Contexts"** (Liu et al., 2023, TACL, arXiv:2307.03172; https://arxiv.org/abs/2307.03172):
  - Demonstrates that LLM retrieval and reasoning degrade non-linearly as irrelevant context increases ($n^2$ pairwise self-attention cost), proving that minimizing Tier 1 prompt footprint is essential for overall reasoning fidelity.
- *Source*: **Authoring Rules**:
  - `/home/marielle/projects/cisternal/.praxia/skills/writing-skill-triggers/SKILL.md:30–50`:
    Direct guidance: Author 2–5 distinctive operational keywords (exact command verbs, filenames, unique error strings). "Cutting words is usually safe; narrowing scope is not." Generic words ("workflow", "error", "analysis") provide zero discriminative signal and dilute the shared budget.

### 3.2 Inferences & Architectural Application

#### Mathematical Derivation of the 250-Character Target (A3, A5, C4)
- *Context Budget Equation*:
  Let $W = 200,000\text{ tokens} \approx 800,000\text{ characters}$.
  The shared pool budget is:
  $$B_{\text{listing}} = W \times \text{skillListingBudgetFraction} = 800,000 \times 0.01 = 8,000\text{ characters}$$
- *Capacity Analysis*:
  In a developer environment with $N = 30$ active skills:
  - If average description length $\bar{L} = 500\text{ characters}$:
    $$\sum_{i=1}^{30} L_i = 30 \times 500 = 15,000\text{ characters} \gg 8,000\text{ characters}$$
    *Outcome*: Catastrophic eviction occurs. Descriptions are stripped to bare names, destroying skill discoverability.
  - If average description length $\bar{L} = 250\text{ characters}$:
    $$\sum_{i=1}^{30} L_i = 30 \times 250 = 7,500\text{ characters} \le 8,000\text{ characters}$$
    *Outcome*: All 30 skills fit safely within the shared budget pool, avoiding description stripping.
  *Inference*: The 250-character soft target in `skill_schema.py` (Assumption A3) is mathematically necessary to sustain modular multi-plugin environments.

#### Application to Component C4 (Progressive-Disclosure Honesty Check)
Shortening descriptions to meet the 250-character budget introduces the risk of semantic distortion. To prevent degradation, Component C4 must enforce dual static and behavioral verification gates:
1. *Static Honesty Invariants*:
   - **(a) No Loss Invariant**: Every distinctive keyword (command verbs, config keys, error codes) present in the long-form description must be preserved in either the compressed short description or the Tier 2 `SKILL.md` body.
   - **(b) No Overclaim Invariant**: Every functional capability claimed in the short description must map to an explicit heading or subsection in the Tier 2 body or Tier 3 `references/`.
   - **(c) Scope Guard Invariant**: The first screen (~30 lines) of `SKILL.md` must state explicit boundary conditions and anti-triggers, ensuring that an agent loading from a terse description is immediately grounded.
2. *Behavioral Non-Inferiority Gate*:
   Static keyword matching cannot guarantee that compression preserves LLM invocation rates across diverse user phrasings. C4 must execute a behavioral evaluation against a frozen situation set (mined by Component C3). The compressed description must demonstrate statistical non-inferiority against the uncompressed baseline at a pre-registered margin ($\delta \le 0.05$).
3. *Application to Component C6 (`triage-tool` skill)*:
   The new `triage-tool` skill introduced in the spec must strictly adhere to a trigger length $\le 150$ characters, ensuring its addition does not trigger eviction cascades in standing plugin sets.

### 3.3 Resolvable Citations Index for Topic 3
- Agent Skills Open Specification, `https://agentskills.io`
- Anthropic Claude Code Skills Documentation, `https://code.claude.com/docs/en/skills`
- `/home/marielle/projects/cisternal/.praxia/docs/research/261017_skill-frontmatter-schema.md`
- `/home/marielle/projects/cisternal/src/cisternal/assets/skill_schema.py`
- `/home/marielle/projects/cisternal/tests/test_skill_schema.py`
- `/home/marielle/projects/cisternal/.praxia/skills/writing-skill-triggers/SKILL.md`
- Liu et al., "Lost in the Middle: How Language Models Use Long Contexts", Transactions of the Association for Computational Linguistics (TACL 2024), arXiv:2307.03172. https://arxiv.org/abs/2307.03172
- "ToolTweak: Evaluating and Improving Tool Descriptions for LLM Tool Selection", arXiv:2404.14394 (2024). https://arxiv.org/abs/2404.14394
- "BiasBusters: Robustness and Invariance in Tool Descriptions", arXiv:2407.03219 (2024). https://arxiv.org/abs/2407.03219

---

## Topic 4: Hook-Based Nudging

### 4.1 Direct Source Findings

#### A. Client-Side Execution Hook Architectures and Lifecycle
Execution hooks allow client environments to inspect, modify, or block tool calls before execution:

- *Source*: Anthropic Claude Code Hooks Guide (`https://code.claude.com/docs/en/hooks`)
- *Lifecycle Events*:
  `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `SessionStart`, `SubagentStop`.
- *PreToolUse Execution Flow*:
  Fires synchronously when an agent requests a tool call (e.g., `Bash`).
  - *Exit 0 + `{}`*: Unmodified passthrough.
  - *Exit 2 + `{"decision": "block", "reason": "..."}`*: Execution denied; reason returned to model context.
  - *Exit 0 + `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {...}}}`*: Programmatically rewrites arguments before execution.
  - *`additionalContext` vs. `systemMessage`*:
    `additionalContext` injects text directly into the LLM conversation context stream, altering subsequent model reasoning. `systemMessage` surfaces text exclusively to the human terminal UI, invisible to the LLM.

#### B. Cross-Surface Hook Incompatibilities and Shell Execution Limits
Direct inspection of production hook scripts reveals acute cross-surface schema divergences and operating system constraints:

- *Source Path*: `/home/marielle/.gemini/config/plugins/praxia/scripts/emit_hook_output.sh:10–164`
- *Cross-Surface Schema Divergences*:
  1. **Claude Code**:
     Requires `decision = "approve" | "block"`. Stated verbatim (`emit_hook_output.sh:110–116`):
     > "Claude rejects that outright -- its PreToolUse schema accepts `decision = "approve"|"block"`, and `"allow"` is a value of `permissionDecision`, a different field. Every Bash tool call raised: `Hook JSON output validation failed - (root): Invalid input. The hook's output was: {"decision": "allow"}`"
     For empty passthrough, Claude Code requires `{}`. For input rewriting, it requires `hookSpecificOutput.PreToolUse.updatedInput`.
  2. **Antigravity**:
     Requires an explicit `decision` key (omitting it defaults to `deny` with an empty reason). For passthrough, it requires `{"decision": "allow"}`. For rewriting, it requires `{"overwrite": {"CommandLine": ...}}`.
  3. **Cursor**:
     Does not implement the input-modification contract (`updatedInput` is ignored). It expects `{"permission": "deny", "agent_message": ...}`.
- *Linux Shell Argument Length Ceiling*:
  - *Observed Code* (`emit_hook_output.sh:35–37`):
    > "Single execve argument is capped at `MAX_ARG_STRLEN` (128KiB) regardless of `ARG_MAX`, and assembled rules context routinely exceeds that. Measured: `jq --arg` fails at exactly 128KiB, emitting nothing at all."
  - Direct Finding: Large context injections within shell hooks cannot pass text via CLI arguments; they must use `jq --rawfile` reading from temporary files.

#### C. Operational Three-Tier Decider Implementation
- *Source Path*: `/home/marielle/.gemini/config/plugins/praxia/scripts/pretool-tool-rewrite.sh:1–119`
- *Source Path*: `/home/marielle/.gemini/config/plugins/praxia/hooks.json:1`
- *Direct Finding*:
  Praxia's PreToolUse hook implements a 3-tier decider:
  1. `rewrite`: Swaps equivalent commands silently (exit 0 + `updatedInput`).
  2. `block`: Rejects commands with fatal hazards and provides structured guidance (exit 2 + `reason`).
  3. `pass`: Transparent passthrough (exit 0 + `{}`).
  The script enforces fail-open semantics on missing binaries, runs regex pre-filters to avoid spawning Python processes on non-matching commands, and logs unhandled hook errors to `.praxia/hook_errors.jsonl`.

#### D. Error-Driven Fallback Cascades (Evidence E4)
- *Source*: Spec Evidence E4 (`261106_tool-surface-triage.md:23`):
  "Error drives fallback: a same-verb `bth` call followed within 3 calls in 13/57 (23%) after an MCP error vs 15/664 (2%) after success."
- *Direct Finding*:
  When an MCP tool fails, agents exhibit an immediate 10-fold increase in fallback to general-purpose Bash execution.
- *Source Literature*: LangChain Tool Error Handling Architecture (`https://python.langchain.com/docs/concepts/tools/`):
  Without explicit error classification and recovery guidance, tool errors cause immediate tool abandonment, cognitive thrashing, and repetitive shell fallbacks.

#### E. Heterogeneous Error Shapes in Cisternal Adapters (Refutation of Assumption A8)
Assumption A8 claims: *"Error shapes are consistent across servers"*.
Direct inspection of `src/cisternal/adapters/base.py:278–388` directly **REFUTES** this assumption:
1. `BathosAdapter.shape_error` (lines 280–285): Returns a Python `dict` with keys `ok: False`, `error_code: "INTERNAL"`, `error`, `resolution_hint`.
2. `PassthroughAdapter.shape_error` (lines 314–318): Does not return a dictionary; **re-raises the raw exception** (`raise exc`).
3. `ContemplexAdapter.shape_error` (lines 343–346): Returns a structured object produced by `contemplex.errors.err_envelope`.
4. `XpeririAdapter.shape_error` (lines 364–368): Serializes the error dictionary to a **JSON-formatted string (`str`)**, not a dict.
5. `MyxcelAdapter.shape_error` (lines 386–388): Returns a `dict` with keys `error` and `message`. **Lacks `ok` and `error_code` entirely.**

### 4.2 Inferences & Architectural Application

#### The Error Fallback Suppression Rule (E4 & C5)
- *Observation*: Evidence E4 shows that an MCP error increases the probability of immediate CLI fallback by more than 10x (23% vs. 2%).
- *Inference*: When an agent attempts an MCP tool, encounters an error, and falls back to Bash (e.g., executing `bth run_sql`), firing a nudge hook telling it to use the broken MCP tool creates an infinite cognitive loop: the agent tries the MCP tool again, fails again, falls back again, and receives another nudge.
- *Architectural Rule for Component C5*:
  Component C5 **must enforce an error-suppression invariant**: never nudge towards an MCP tool if that tool failed earlier in the same session.

#### Prerequisite: Adapter Error Shape Standardization (A8 Refutation Impact)
- *Observation*: Assumption A8 is refuted: adapters output dictionaries, JSON strings, and re-raised exceptions.
- *Inference*: Component C5 cannot reliably know whether an MCP tool errored unless error detection is standardized. If C5 checks for `result.get("ok") is False`, it will miss errors from `MyxcelAdapter` (which uses `{error, message}`), `XpeririAdapter` (which returns a string), and `PassthroughAdapter` (which re-raises).
- *Build Order Requirement*:
  The spec's build order (`C0 -> C1, C2 -> C3 -> C4 -> C6 -> C5`) is validated. Component C5 must be built last, and its implementation is strictly blocked on completing the error-path classification and error shape normalization.

#### Nudge Delivery Mechanism: Additive Context vs. Command Rewriting
- *Observation*: `emit_hook_output.sh` proves that `updatedInput` has fragile, incompatible schemas across surfaces (supported in Claude Code, different key in Antigravity, unsupported in Cursor), whereas additive context (`additionalContext`) is widely supported. Furthermore, certain CLI actions (such as `bth run`) are long-running subprocesses where CLI execution is functionally superior to an MCP tool.
- *Inference*: C5 must not attempt to silently rewrite bash commands into MCP calls. It should inject additive context nudging the model toward MCP strictly for idempotent, read-heavy actions (`bth sql`, `bth show`, `bth validate-sidecar`), while remaining completely silent on execution commands (`bth run`).
- *A/B Adherence Evaluation (Assumption A7)*:
  Because Assumption A7 ("A hook's additive context changes behavior") is unverified, C5 cannot be marked complete without an empirical A/B evaluation measuring the shift in MCP-to-CLI ratio across matched sessions.

### 4.3 Resolvable Citations Index for Topic 4
- Anthropic Claude Code Hooks Guide, `https://code.claude.com/docs/en/hooks`
- `/home/marielle/.gemini/config/plugins/praxia/hooks.json`
- `/home/marielle/.gemini/config/plugins/praxia/scripts/pretool-tool-rewrite.sh`
- `/home/marielle/.gemini/config/plugins/praxia/scripts/emit_hook_output.sh`
- `/home/marielle/projects/cisternal/src/cisternal/adapters/base.py`
- LangChain Tool Error Handling Architecture, `https://python.langchain.com/docs/concepts/tools/`
- Rebedea et al., "NeMo Guardrails: A Toolkit for Controllable and Safe LLM Applications", arXiv:2310.10501 (2023). https://arxiv.org/abs/2310.10501

---

## Cross-Cutting Analysis: Components, Evidence, and Assumptions

### 1. Component Readiness and Specification Matrix (C0–C6)

| Component | Source of Truth | Delivery Mechanism | Negative Control (NC) | Prior Art Justification & Invariants |
|---|---|---|---|---|
| **C0: Tracked Usage Counter** | Claude Code client transcripts joined with cisternal server JSONL telemetry. | `cisternal usage` CLI subcommand backed by `.bth.toml` sidecar. | Synthetic transcript with known counts; a planted uncalled tool must report exactly 0 calls. | Resolves the client/server observability gap; guards against silent harness masking via synthetic positive/negative controls. |
| **C1: Prune List** | Current registered plugins (`~/.claude/settings.json`, `~/.claude.json`, manifests) INTERSECT C0 usage. | User-facing keep / drop / per-project advisory report (no automatic edits). | Unregistered servers in transcripts must not appear; registered servers with calls must not be marked drop. | Prevents transcript history pollution (E5); preserves passive hooks and slash commands without MCP tools. |
| **C2: Guidance-Coverage Lint** | Plugin bundle manifests and skill schemas. | `cisternal assets validate` static check. | Deleting a family trigger fails validation; renaming an MCP tool triggers a dangling-name error. | Replaces "name in skill" requirement (falsified by E3); enforces situational family triggers and dangling reference integrity. |
| **C3: Skill Coverage Tooling** | Claude Code transcripts joined with skill distinct-string manifests. | Automated opportunity evaluator feeding C4's frozen situation set. | Synthetic transcripts with skill invoked / not invoked / invoked late. | Overcomes agent search reluctance (E2); quantifies guidance opportunities; measures precision on hand-labeled samples. |
| **C4: Progressive-Disclosure Check** | Frontmatter character counts and skill Markdown structure. | Static checks in `assets validate` + behavioral evaluation on frozen set. | Description naming an uncovered topic fails (b); description omitting distinctive keywords fails (a). | Mathematically protects 1% context pool (A3, A5); enforces static honesty invariants (no loss, no overclaim) and behavioral non-inferiority. |
| **C5: Verb-to-Tool Nudge Hook** | PreToolUse hook configuration and per-plugin verb mapping tables. | Additive context injection via `additionalContext` in PreToolUse hook. | Fires on `bth sql`, does NOT fire on `bth run`, does NOT fire after prior MCP error in session. | Prevents error-driven fallback thrashing (E4); blocked on error shape normalization (A8) and verified by A/B testing (A7). |
| **C6: `triage-tool` Skill** | Cisternal asset repository. | New `triage-tool` skill shipped inside cisternal. | Trigger exceeding 150 characters fails C4 validation; proposing direct settings edits fails review. | Provides in-context operational workflow for triage; strictly respects listing budget ($\le 150$ chars). |

### 2. Evidence Reconciliation Matrix (E1–E5)

| Evidence ID | Spec Finding | Observed Data Fact | Validated Architectural Inference |
|---|---|---|---|
| **E1** | MCP vs. CLI for bathos: 943 MCP vs. 7,948 `bth` Bash calls (~10% MCP). | Untracked exploratory probe across 145 main sessions. | Confirms massive CLI bias; justifies the need for C0 formal derivation and C5 nudging. |
| **E2** | ToolSearch: 2,524 / 2,537 calls (99.5%) were `select:<exact name>`; 13 keyword. | Autonomous agents do not perform exploratory keyword searches in practice. | Confirms discovery cannot rely on `tool_search`; justifies C2 situational family triggers. |
| **E3** | Provenance of 225 bathos `select:` loads: 113 had name in deferred listing only; 112 had prior mention. | 50.2% of loads occurred from bare stub listing without prior prompt or skill mention. | Falsifies the assumption that tool names must appear in skills; validates C2 invariant update. |
| **E4** | Error drives fallback: same-verb `bth` call followed in 13/57 (23%) after error vs. 15/664 (2%) after success. | MCP errors increase immediate CLI fallback probability by more than 10-fold. | Mandates the error-suppression rule in C5 to avoid infinite cognitive thrashing loops. |
| **E5** | Registration now: 27 enabled plugins; ~35 zero-use servers are historical transcript artifacts. | Transcripts accumulate historical session logs from disabled or renamed plugins. | Mandates that C1 prune list must intersect usage with current registration configurations. |

### 3. Assumption Resolution Matrix (A1–A9)

| Assumption ID | Spec Description | Verification Status | Source Code / Literature Anchor | Architectural Impact on Spec |
|---|---|---|---|---|
| **A1** | cisternal-exported plugins can ship PreToolUse hooks | **VERIFIED** | `src/cisternal/assets/manifest.py:232–271`<br>`src/cisternal/export/claude.py:124–143` | C5 delivery mechanism is fully supported by cisternal's plugin export infrastructure. |
| **A2** | cisternal telemetry is server-side (`mcp.call_start/call_end/tool_error`); sees no CLI substitution | **VERIFIED** | `src/cisternal/telemetry/record.py:8–43`<br>`src/cisternal/adapters/base.py:157–208` | C0 must join server telemetry with client transcripts to capture CLI substitution. |
| **A3** | `assets validate` already reports listing advisory at 250 chars | **VERIFIED** | `src/cisternal/assets/skill_schema.py:26, 145–159`<br>`tests/test_skill_schema.py:214–234` | The 250-character soft target is already implemented in code and ready for C4 adoption. |
| **A4** | praxia `session_context_audit.py` already tallies `other_mcp_by_server`, `skills_by_plugin` | **CODE AUDITED** | `/home/marielle/projects/praxia/scripts/context_audit/session_context_audit.py:55–80, 215–248` | C0 cannot wrap it unchanged: it discards per-tool data for non-praxia servers and resides in an external repo. |
| **A5** | Claude Code skill-listing budget is shared pool (~1% of context) with 1,536-char hard cap | **VERIFIED** | `src/cisternal/assets/skill_schema.py:23, 137–141`<br>`.praxia/skills/writing-skill-triggers/SKILL.md:13–19` | Validates mathematical requirement for 250-character target to prevent catastrophic stripping. |
| **A6** | Transcript record types separate listing, hook, skill, user, tool-result text | **STILL-UNVERIFIED IN CODE** | `.gemini/config/plugins/praxia/skills/triaging-harness-files/SKILL.md:320–327` | Zero parsing code exists in cisternal; C0 must implement transcript parsing from scratch. |
| **A7** | A hook's additive context changes behavior | **STILL-UNVERIFIED** | None (no experimental harness in tree) | C5 cannot be certified without matched-session A/B testing measuring MCP/CLI ratio shifts. |
| **A8** | Error shapes are consistent across servers | **REFUTED** | `src/cisternal/adapters/base.py:278–388` | Adapters return dicts, strings, and re-raise exceptions; C5 is blocked on error standardization. |
| **A9** | Subagents do not change the picture | **STILL-UNVERIFIED** | `triaging-harness-files/SKILL.md:317` | Subagents operate with ~26k fewer tokens; C0 must evaluate subagent transcripts separately. |

### 4. Validated Build Order & Dependency Graph

```
           +---------------------------------------------+
           |     A8 Error Shape Normalization Pass       |
           +---------------------------------------------+
                                  │
                                  ▼
           +---------------------------------------------+
           |       C0: Tracked Usage Counter             |
           |   (Client JSONL + Server Telemetry Join)    |
           +---------------------------------------------+
                                  │
                 ┌────────────────┴────────────────┐
                 ▼                                 ▼
+---------------------------------+  +---------------------------------+
|        C1: Prune List           |  |   C2: Guidance-Coverage Lint    |
| (Registration ∩ C0 Usage Filter)|  | (Family Trigger + Dangling Lint)|
+---------------------------------+  +---------------------------------+
                 │                                 │
                 └────────────────┬────────────────┘
                                  ▼
           +---------------------------------------------+
           |       C3: Skill Coverage Tooling            |
           |     (Mines Frozen Situation Set)            |
           +---------------------------------------------+
                                  │
                                  ▼
           +---------------------------------------------+
           |   C4: Progressive-Disclosure Honesty Check  |
           |   (Static Invariants + Behavioral Non-Inf)  |
           +---------------------------------------------+
                                  │
                                  ▼
           +---------------------------------------------+
           |      C6: triage-tool Skill Development      |
           |          (Trigger <= 150 chars)             |
           +---------------------------------------------+
                                  │
                                  ▼
           +---------------------------------------------+
           |      C5: Verb-to-Tool Nudge Hook            |
           | (Requires A8 normalization & A7 A/B testing)|
           +---------------------------------------------+
```

---

## Methodological Caveats & Threats to Validity

1. **Subagent Headless Execution Dynamics (Assumption A9)**:
   Exploratory evidence E1–E5 was derived exclusively from 145 main-session transcripts; subagents were excluded. Subagents operate with a ~26k token deficit in standing context (`triaging-harness-files/SKILL.md:317`) and execute headlessly without user steering. Whether subagents exhibit the same 10% MCP vs. 90% CLI ratio remains an unverified empirical question that Component C0 must explicitly evaluate.
2. **Reverse-Engineered Binary Coefficients (Assumption A5)**:
   The 1,536-character cap and 1% context window budget were derived from string scans and disassembly of Claude Code binaries 2.1.302 and 2.1.318. While documented in `.praxia/docs/research/261017_skill-frontmatter-schema.md`, host runtime updates could alter these coefficients without notice.
3. **Exploratory Status of Preliminary Evidence (E1–E5)**:
   The figures in E1–E5 (e.g., 943 MCP vs. 7,948 CLI calls, 23% error fallback) were generated by untracked exploratory probe scripts. They serve to justify the spec's problem statement, but must be formally re-derived by Component C0 under controlled pre-registration before being cited as verified benchmarks.

---

## Verification & Audit Trail

To independently verify the citations, findings, and code references documented in this report:

1. **Verify Local Code Citations**:
   ```bash
   # Check skill listing constants (A3, A5)
   grep -n -E "LISTING_CAP_CHARS|LISTING_TARGET_CHARS" /home/marielle/projects/cisternal/src/cisternal/assets/skill_schema.py

   # Check hook export logic (A1)
   grep -n -A 10 "build_claude_style_hooks" /home/marielle/projects/cisternal/src/cisternal/export/hooks.py

   # Check cross-surface hook emitter differences (Topic 4)
   grep -n -A 15 "emit_empty_object" /home/marielle/.gemini/config/plugins/praxia/scripts/emit_hook_output.sh

   # Check adapter error shape heterogeneity (A8 refutation)
   grep -n -A 8 "def shape_error" /home/marielle/projects/cisternal/src/cisternal/adapters/base.py
   ```

2. **Verify Diagnostic Harness Failure Findings**:
   ```bash
   cat /home/marielle/projects/cisternal/.claude/worktrees/261104-skill-triggers/scripts/diag/README.md
   ```

3. **Verify Research Notes**:
   ```bash
   head -n 50 /home/marielle/projects/cisternal/.claude/worktrees/261106-agy-spec-cycles/.praxia/docs/research/261017_skill-frontmatter-schema.md
   ```

4. **Verify Literature Links**:
   Confirm that all arXiv URLs resolve to valid publications:
   - ToolLLM / ToolBench: `https://arxiv.org/abs/2307.16789`
   - Gorilla: `https://arxiv.org/abs/2305.15334`
   - AnyTool: `https://arxiv.org/abs/2402.04253`
   - ToolkenGPT: `https://arxiv.org/abs/2305.11554`
   - Shortlist Depth: `https://arxiv.org/abs/2409.08868`
   - ToolTweak: `https://arxiv.org/abs/2404.14394`
   - Lost in the Middle: `https://arxiv.org/abs/2307.03172`
   - NeMo Guardrails: `https://arxiv.org/abs/2310.10501`
