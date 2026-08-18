---
title: graph_annotate/graph_query designated canonical Praxia-family corpus/KG tool
description: Ratifies praxia's existing graph_annotate/graph_query rig-run flows (backed by graphify-praxia-adapter, wrapping upstream graphify) as the canonical static content/code knowledge-graph tool across the Praxia family, in lieu of building a separate cisternal-packaged plugin. Logs two hardening gaps as praxia backlog items.
status: accepted
task_id: 260817_graphify-cisternal-survey
date: '260817'
supersedes: ''
backlog_ids: '4273, 4274'
---
# graph_annotate/graph_query designated canonical Praxia-family corpus/KG tool

## Context

The question that opened this: should any Praxia-family project (cisternal, bathos, myxcel,
contemplex, etc.) ship its own searchable knowledge graph and corpus so agents can do different
kinds of search and procedural recall over it — and is `graphify`, used inside this session as a
Claude Code skill, worth promoting into its own first-class tool?

Two premises in the original framing turned out to be wrong and are corrected here:

1. **`graphify` is not our fork.** It's upstream open source (Graphify-Labs, YC S26; PyPI
   `graphifyy`, MIT), portable across Claude Code/Aider/Copilot/etc. What we actually own is
   `graphify-praxia-adapter` (`github.com/maraxen/graphify-praxia-adapter`), a substantial
   (14-module) pinned-version wrapper package with real feature work tracked up through FR-014.
2. **This isn't a "should we build a tool" question — it already has an answer.** praxia already
   exposes `graph_annotate` and `graph_query` as registered rig-run flows (backlog #3775/FR-007,
   #3779/FR-008), backed by `graph_build.rs`/`graph_query.rs` (`crates/praxia-tools/src/`), which
   shell out to the adapter's `graphify-adapter-build`/`graphify-adapter-query` console scripts
   via `uv run`. These are `LIGHT_TOOLS` — they run in-process inside praxia-mcp/CLI, not routed
   through `praxia-tool-host`, so they sidestep that binary's staleness failure class entirely.

Prior art directly on point: spec `260728_graphify-docs-codebase-rig-workflow.md` (in the praxia
repo) already deliberately decided **against** an adapter-owned cisternal-wired MCP server for
MVP — *"a possible future extension with no FR/AC attached to it now... mandating it would
violate this spec's own defer-what-lacks-a-driving-use-case pattern."* This decision doc ratifies
that choice explicitly rather than re-litigating it, and closes the gap audit that choice implied
but never completed.

## Decision

**`graph_annotate`/`graph_query` (praxia rig-run flows) + `graphify-praxia-adapter` is the
canonical corpus/code-knowledge-graph tool for the Praxia family.** No new cisternal-packaged
plugin surface is being built for this. Any Praxia-family project that needs static
content/code-graph search (community detection, god nodes, shortest-path, node/neighbor lookup)
should call these flows via `praxia rig-run --flow graph_annotate|graph_query`, not stand up a
separate graph engine.

**Scope boundary — read together with
[[260817_procedural-recall-layer-graphiti-et-al-defer-adoption-pre-registered-revisit-criteria]]:**
this tool covers *static content* (code, docs, papers, images, video) via Leiden/Louvain
community detection and tree-sitter/LLM extraction. It has **no notion of time-varying agent task
history** — no episodic/procedural "what did we do before and does it still hold." That is a
structurally different axis (bi-temporal memory), deliberately deferred as its own decision, not
an oversight in this one.

## Gap audit (260817)

A read-only recon of `crates/praxia-tools/src/graph_build.rs`/`graph_query.rs` and their tests
found:

- **Test coverage is solid but partial.** Command-construction and deserialization are tested
  against *real captured adapter stdout* (not hand-written fixtures — a prior bug, #3962, silently
  dropped 6 fields because a hand-built fixture couldn't reveal the struct's gaps; the fix added a
  forward-compat `extra` catch-all plus a regression test). **Gap:** no test spawns the actual
  `uv run` subprocess end-to-end — the live call, its timeout path, and its non-zero-exit path are
  untested. Filed as praxia backlog **#4273** (P2, standard).
- **Single-machine assumption.** The adapter project path defaults to the literal absolute path
  `/home/marielle/customized_tools/graphify-praxia-adapter`, overridable only via
  `GRAPHIFY_ADAPTER_PROJECT`. "Any Praxia-family project can call this" is true today only on this
  machine or with the env var set — it is not yet a portable, installable capability. Filed as
  praxia backlog **#4274** (P2, quick).
- No other open bugs found against `graph_annotate`/`graph_query` specifically. One known, already
  -tracked scaling trigger exists (category-subdirectory splitting of `scan_root` at 450+ files,
  `260813_docs-category-subdirectory-split-scheme.md`) — explicitly deferred pending threshold,
  not a gap this doc needs to reopen.

## Consequences

- Sibling projects should treat `praxia rig-run --flow graph_annotate|graph_query` as the default
  entry point for corpus/code-graph queries, not `graphify` the skill directly (which remains
  useful standalone/outside the Praxia family, e.g. in non-praxia-enabled repos).
- Cross-project consumability still requires a working praxia install on the calling machine
  (confirmed: not tool-host-routed, so no `praxia-tool-host` dependency) — closing backlog #4274
  is what actually makes "any Praxia-family project, any machine" true rather than aspirational.
- No cisternal `assets export` / `.praxia/manifest.toml` work is needed for graphify itself as a
  result of this decision.
