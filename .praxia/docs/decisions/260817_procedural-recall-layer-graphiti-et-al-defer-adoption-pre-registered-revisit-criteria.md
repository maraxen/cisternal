---
title: Procedural recall layer (Graphiti et al.) — defer adoption, pre-registered revisit criteria
description: 'Fresh 3-lens customizing-tools jury on adopting a temporal/episodic agent-memory dependency (Graphiti vs mem0 vs cognee vs Letta) to complement graphify''s static content graph. Verdict: defer, no driving use case yet; pre-registers Graphiti (pinned >=0.28.2, FalkorDB Lite backend) as the default if/when one emerges, with mem0 as the faster fallback for non-temporal needs.'
status: accepted
task_id: 260817_graphify-cisternal-survey
date: '260817'
supersedes: ''
backlog_ids: ''
---
# Procedural recall layer (Graphiti et al.) — defer adoption, pre-registered revisit criteria

## Context

Companion to
[[260817_graph_annotate-graph_query-designated-canonical-praxia-family-corpus-kg-tool]]. That
decision designated `graph_annotate`/`graph_query` as the canonical tool for *static content*
knowledge graphs. A landscape survey run alongside it found agent-memory tooling splits into
three genuinely distinct axes, and no single tool covers all three:

1. **Static content/code knowledge graph** — GraphRAG, LlamaIndex PropertyGraphIndex, and
   graphify itself. Covered by the companion decision.
2. **Agent episodic/temporal memory** — "what did we do before, when, and does it still hold."
   Zep/Graphiti's whole design is bi-temporal edge validity; this is what "procedural recall"
   actually means, and graphify has zero machinery for it.
3. **Vector-only corpus search** — a commodity substrate (txtai etc.), not a differentiator.

This doc addresses axis 2: should the Praxia family adopt a dependency for it, and if so, which
one and how?

Per the `cisternal:customizing-tools` skill, this qualifies as a **novel/high-stakes** decision
(a new dependency shaping cross-family agent-memory architecture, expensive to reverse) rather
than a fast-path decision-matrix match — no prior docs in `.praxia/docs/decisions/` addressed
this axis before today. A fresh 3-lens jury was run per the skill's workflow, using independent
Claude subagents (the skill's documented fallback path when reasoning quality matters more than
the zero-token `rig_run flow="jury"` primitive's local-model execution) rather than pattern-
matching stale examples.

## Jury verdicts

**Security/maintenance lens — Accept dependency (Graphiti + FalkorDB Lite), confidence 0.68.**
Graphiti is actively maintained (107 releases, ~14k stars, Zep-backed, active PRs through 2026-07)
and **supports FalkorDB Lite** — an embedded, zero-config, no-server backend, which directly
answers the maintenance-burden question a mandatory-Neo4j story would raise for a single-developer
team. Hard condition: **pin `graphiti-core>=0.28.2`** — CVE-2026-32247 is a disclosed Cypher-
injection vulnerability via unsanitized `node_labels`, fixed in 0.28.2, and the advisory
specifically flags it as exploitable *through prompt injection against an LLM client in MCP
deployments* — exactly the shape any future integration here would take. Avoid the Kuzu backend
(upstream unmaintained, being dropped by Graphiti). Explicitly scoped: this lens can only say "if
adopted, this is how to adopt it safely," not "should we adopt it now."

**Delivery-speed lens — Defer, no driving use case yet, confidence 0.82 (highest of the three).**
This harness's own Claude Code memory-file system (markdown + frontmatter + `MEMORY.md`) is
already a real, zero-integration-cost procedural/feedback/project-memory capability, in active use
this session. No concrete task has yet demonstrated that system's ceiling. Standing up Graphiti
means a new operational dependency (Neo4j/FalkorDB/Kuzu) for a family whose current graph tool is
deliberately DB-free and in-process — a real infrastructure-weight jump. The family's own
precedent (the companion doc's spec `260728_graphify-docs-codebase-rig-workflow.md`, which
deferred a cisternal MCP surface for graphify itself for the identical "no driving use case"
reason) argues the same way here, on a larger infrastructure bill. Also: the family's *first*
graph tool isn't fully hardened yet (backlog #4273/#4274) — taking on a second, heavier dependency
before finishing the first is sequencing the harder, less-certain work ahead of the already-
committed one. If/when a need materializes, **mem0** (Apache-2.0, Docker-only, no dedicated graph
DB) is the faster/cheaper path *unless* the need is specifically bi-temporal fact-superseding
reasoning, which mem0's plain-vector mode cannot do (and mem0's own graph-mode add-on measured
~2x LLM token cost, ~3x slower search, for thin accuracy gains — not a free upgrade).

**License/IP lens — Accept dependency, confidence 0.8; no lens-based reason to defer.**
Graphiti (Apache-2.0), mem0 (Apache-2.0), and cognee (MIT) are all confirmed current and clean —
web-verified against live license files and repo state, not training-data priors. Zep discontinued
its separate open-core "Community Edition" product and pivoted to make Graphiti its sole OSS
focus, explicitly disclaiming future feature-gating — materially lower relicensing risk than the
"loss-leader OSS core" pattern this lens was checking for. Neo4j Community Edition's GPLv3 is not
a copyleft trigger here: GPLv3 (unlike AGPL) has no network-copyleft clause, and a client that only
talks to a separately-deployed, self-hosted Neo4j/FalkorDB process over its network protocol
incurs no obligation to open-source the client — the same pattern MySQL Community has supported
for proprietary clients for decades, confirmed directly on Graphiti's own tracker for its
Apache-2.0/HTTP-sidecar boundary. Hard condition if ever adopted: never bundle/redistribute
Neo4j binaries inside a Praxia-family installable artifact — require a user-provisioned, self-
hosted instance, exactly as Graphiti's own docs already assume.

## Aggregate synthesis

The two lenses that ask *"if adopted, is it safe"* (security, license) both say yes,
conditionally. The one lens that asks *"should we adopt it now"* (delivery-speed) — and it is the
**highest-confidence verdict of the three** — says no. Per the skill's aggregation guidance
("disagreement usually marks a genuine tradeoff, not noise to average away"): this isn't actually
disagreement about whether Graphiti is a good choice. It's agreement, scoped to different
questions the jury design deliberately kept separate.

## Decision

**Defer.** No procedural/episodic-recall dependency is being adopted now. The existing harness
memory-file system remains the de facto axis-2 capability until a concrete task demonstrates its
ceiling.

**Pre-registered revisit criteria** — when a task specifically needs "was X true at time T,
superseded by Y at time T+1" reasoning that the memory-file system cannot answer:

1. Default to **Graphiti**, `graphiti-core>=0.28.2` pinned, **FalkorDB Lite** backend (not Neo4j,
   not Kuzu) — acquisition mode: **accept_dependency**.
2. If the actual need is plain "remember this fact happened," not bi-temporal supersession,
   prefer **mem0** instead — faster, cheaper, no graph database.
3. Either way: deploy any graph-database backend as a separate, self-hosted, network-connected
   process. Never bundle/redistribute it inside a Praxia-family package.
4. Finish backlog #4273/#4274 (the companion doc's hardening gaps) before or alongside taking on
   this second dependency — don't stack an unfinished tool under a new one.

Recorded via `cisternal.telemetry` (`customizing-tools/scripts/record_decision.py`) as a
low-confidence conditional `accept_dependency` targeting "Graphiti as procedural-recall layer,"
reflecting the deferred-but-pre-registered nature of this verdict — the six-option vocabulary has
no literal "defer" value, so the decision is recorded at the confidence that best reflects "not
now, but this is the answer when it's needed."
