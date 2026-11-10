# 261106-agy-spec-cycles Internal Docs
Claimed by: defender_c4 (Docs Index Alignment), worker_docs_indexer, cycle5_reviser (cycle 5 audit entry), cycle5_rereviewer (cycle 5 re-review, superseded notes), challenger_c6 / defender_c6 (cycle 6 audit entry), challenger_c7 / defender_c7 (cycle 7 audit entry), challenger_c8 / defender_c8 (cycle 8 audit entry), worker_m6 (implemented status update), worker_remediation (independent audit entry)

## Daily

## Handoffs
- [260730_telemetry-start-guard-and-dogfood-ci-handoff](handoffs/260730_telemetry-start-guard-and-dogfood-ci-handoff.md) — Telemetry start-event guard + export-dogfood CI repair — Session Handoff
- [260616_cisterna-m1-foundation-handoff](handoffs/260616_cisterna-m1-foundation-handoff.md) — Cisterna M1 — Session Handoff (Sprint 1 / Foundation complete)

## Plans

## Specs
- [261106_tool-surface-triage](specs/261106_tool-surface-triage.md) — Specification for cisternal tooling that measures MCP/skill use and coverage, prunes dead surface, checks short-description accuracy, and nudges CLI-to-MCP at the moment of the wrong action. (implemented)
- [261001_wire-cli-contract](specs/261001_wire-cli-contract.md) — Declarative CLI contract with exception mapping, rich formatters, and group interop for cisternal #30
- [260929_sidecar-tree-manifest-verification](specs/260929_sidecar-tree-manifest-verification.md) — Stop the provenance reader from presenting an unverified sidecar/env git sha as authoritative; add one shared tree-manifest writer+verifier for no-.git hosts
- [260827_git-provenance-telemetry](specs/260827_git-provenance-telemetry.md) — Adds git SHA/branch/dirty-state capture as a first-class cisternal telemetry field, consumed consistently by bathos and myxcel
- [260624_hmw-inter-epic-audit-of-m12-export-rust](specs/260624_hmw-inter-epic-audit-of-m12-export-rust.md)
- [260624_m10-1-telemetry-doctor-cli-for-cisterna](specs/260624_m10-1-telemetry-doctor-cli-for-cisterna.md)
- [260624_m10-2-telemetry-doctor-json-exit-codes-e](specs/260624_m10-2-telemetry-doctor-json-exit-codes-e.md)
- [260624_m10-4-doctor-consumer-filter-add-optiona](specs/260624_m10-4-doctor-consumer-filter-add-optiona.md)
- [260624_m10-operator-runbook-for-cisterna-docume](specs/260624_m10-operator-runbook-for-cisterna-docume.md)
- [260624_m11-1-native-validate-promotion-for-cist](specs/260624_m11-1-native-validate-promotion-for-cist.md)
- [260624_m11-export-hardening-ii-for-cisterna-exp](specs/260624_m11-export-hardening-ii-for-cisterna-exp.md)
- [260624_m12-export-rust-bridge-buildable-spec-rev1](specs/260624_m12-export-rust-bridge-buildable-spec-rev1.md) — M12 Export Rust bridge — buildable spec rev1
- [260624_m12-export-rust-bridge-praxia-agent-asse](specs/260624_m12-export-rust-bridge-praxia-agent-asse.md)
- [260624_m6-bathos-telemetry-cutover-buildable-spec-rev1](specs/260624_m6-bathos-telemetry-cutover-buildable-spec-rev1.md) — M6 Bathos Telemetry Cutover — buildable spec rev1
- [260624_m7-2-otlp-collector-ci-promotion-promote](specs/260624_m7-2-otlp-collector-ci-promotion-promote.md)
- [260624_m7-otlp-egress-buildable-spec-rev1](specs/260624_m7-otlp-egress-buildable-spec-rev1.md) — M7 OTLP Egress — buildable spec rev1
- [260624_m7.1-otlp-http-buildable-spec-rev1](specs/260624_m7.1-otlp-http-buildable-spec-rev1.md) — M7.1 OTLP HTTP + collector CI — buildable spec rev1
- [260624_m8-xperiri-adapter-buildable-spec-rev1](specs/260624_m8-xperiri-adapter-buildable-spec-rev1.md) — M8 XpeririAdapter — buildable spec rev1
- [260624_m9-myxcel-adapter-buildable-spec-rev1](specs/260624_m9-myxcel-adapter-buildable-spec-rev1.md) — M9 MyxcelAdapter — buildable spec rev1
- [260623_ci-promotion-status](specs/260623_ci-promotion-status.md)
- [260623_cisterna-m3-1b-2487-cursor-copilot-emitt](specs/260623_cisterna-m3-1b-2487-cursor-copilot-emitt.md)
- [260623_hmw-audit-closed-epic-m3-1-2326-before-m](specs/260623_hmw-audit-closed-epic-m3-1-2326-before-m.md)
- [260623_hmw-audit-closed-epic-m3-2-2563-before-n](specs/260623_hmw-audit-closed-epic-m3-2-2563-before-n.md)
- [260623_hmw-select-cisterna-m4-milestone-after-m](specs/260623_hmw-select-cisterna-m4-milestone-after-m.md)
- [260623_hmw-select-cisterna-m5-milestone-after-m](specs/260623_hmw-select-cisterna-m5-milestone-after-m.md)
- [260623_m12-epic-audit_spec](specs/260623_m12-epic-audit_spec.md)
- [260623_m3-2-2563-entry-point-emitter-plugin-dis](specs/260623_m3-2-2563-entry-point-emitter-plugin-dis.md)
- [260623_m3-3-2581-triage-which-deferred-rev2-chi](specs/260623_m3-3-2581-triage-which-deferred-rev2-chi.md)
- [260623_m31-buildable-spec](specs/260623_m31-buildable-spec.md) — Cisterna M3.1 — Agent-Asset Export — Buildable Spec (rev2, adversarially reconciled)
- [260623_m31b-buildable-spec-rev3](specs/260623_m31b-buildable-spec-rev3.md) — Cisterna M3.1b — Cursor + Copilot emitters — Buildable Spec (rev3, adversarially reconciled)
- [260623_m31c-buildable-spec-rev1](specs/260623_m31c-buildable-spec-rev1.md) — Cisterna M3.1c — Antigravity CLI emitter — Buildable Spec (rev1)
- [260623_m32-buildable-spec-rev1](specs/260623_m32-buildable-spec-rev1.md) — Cisterna M3.2 — entry_point emitter registry — Buildable Spec (rev1)
- [260623_m33a-snapshot-api-rev1](specs/260623_m33a-snapshot-api-rev1.md) — Cisterna M3.3a — public registration.snapshot() API — Buildable Spec (rev1)
- [260623_m33b-writersink-rev1](specs/260623_m33b-writersink-rev1.md) — M3.3b — WriterSink ABC — rev1
- [260623_m33c-vendor-export-command-rev1](specs/260623_m33c-vendor-export-command-rev1.md) — M3.3c — vendor path-array export_command — rev1
- [260623_m33d-l14-validate-rev1](specs/260623_m33d-l14-validate-rev1.md) — M3.3d — L14 validate-only extensions — rev1
- [260623_m4-export-trust-buildable-spec-rev1](specs/260623_m4-export-trust-buildable-spec-rev1.md) — M4 Export Trust — buildable spec rev1
- [260623_m5-telemetry-adoption-buildable-spec-rev1](specs/260623_m5-telemetry-adoption-buildable-spec-rev1.md) — M5 Telemetry Adoption — buildable spec rev1
- [260623_m6-milestone-for-cisterna-after-m5-telem](specs/260623_m6-milestone-for-cisterna-after-m5-telem.md)
- [260623_m7-milestone-for-cisterna-after-m6-batho](specs/260623_m7-milestone-for-cisterna-after-m6-batho.md)
- [260623_m8-milestone-for-cisterna-after-m7-otlp](specs/260623_m8-milestone-for-cisterna-after-m7-otlp.md)
- [260623_m9-milestone-for-cisterna-after-m8-xperi](specs/260623_m9-milestone-for-cisterna-after-m8-xperi.md)
- [260618_cisterna-m3-milestone-agent-asset-export](specs/260618_cisterna-m3-milestone-agent-asset-export.md)
- [260618_m3-buildable-spec](specs/260618_m3-buildable-spec.md) — Cisterna M3 — Agent-Asset Export — Buildable Spec (rev2, adversarially reconciled)
- [260616_cisterna-m1-telemetry-spec](specs/260616_cisterna-m1-telemetry-spec.md) — Cisterna Milestone 1 — Telemetry Core
- [260616_cisterna-mission-and-roadmap](specs/260616_cisterna-mission-and-roadmap.md) — Cisterna — Mission, Recon Findings & Telemetry-First Roadmap
- [260616_design-the-cisterna-m2-registration-surf](specs/260616_design-the-cisterna-m2-registration-surf.md)
- [260616_design-the-implementation-spec-for-ciste](specs/260616_design-the-implementation-spec-for-ciste.md)

## Actuation Surfaces

## Audits
- [261110_independent_swarm_audit](audits/261110_independent_swarm_audit.md) — Independent swarm forensic audit and zero-trust verification of tool-surface triage implementation: Tracks A–D, adversarial probes, anti-facade checks, and completed remediations.
- [261106_cycle1_audit](audits/261106_cycle1_audit.md) — Sequential adversarial audit of tool-surface triage spec: 13 gaps conceded by defender and resolved with architectural specifications.
- [261106_cycle2_audit](audits/261106_cycle2_audit.md) — Sequential adversarial audit of tool-surface triage spec cycle 2: 6 operational gaps resolved, achieving structural coherence.
- [261106_cycle3_audit](audits/261106_cycle3_audit.md) — Sequential adversarial audit of tool-surface triage spec cycle 3: resolution of dependency ordering, A8 client hook consistency, and sandbox boundary clarity.
- [261106_cycle4_audit](audits/261106_cycle4_audit.md) — Sequential adversarial audit of tool-surface triage spec cycle 4: final verification of structural coherence yielding zero open genuine gaps. *Superseded by cycle 5: the probes were argued, not tested, and the zero-gap and termination claims are withdrawn.*
- [261106_cycle5_audit](audits/261106_cycle5_audit.md) — Cycle 5: spec revised per revision brief A1-A16 and decisions R1-R5, status back to draft; challenger/defender pass plus second-agent re-review found 12 new genuine gaps (GAP-23..34; 3 fixed in spec, 9 open) and 2 unverified risks.
- [261106_cycle6_audit](audits/261106_cycle6_audit.md) — Cycle 6: resolves open Cycle 5 gaps (GAP-23..27, 29, 30, 33, 34) and risks (RISK-01, RISK-02); sequential challenger/defender pass against cisternal source identifies and resolves 4 codebase-integration gaps (GAP-35..38).
- [261106_cycle7_audit](audits/261106_cycle7_audit.md) — Cycle 7: sequential challenger/defender pass on the post-Cycle-6 draft spec against plugin/config.py, export/claude.py, and shipped .praxia/skills/; identifies and resolves 3 codebase-integration gaps (GAP-39..41).
- [261106_cycle8_audit](audits/261106_cycle8_audit.md) — Cycle 8: sequential challenger/defender verification pass on the post-Cycle-7 draft spec; all Cycle 5, Cycle 6, and Cycle 7 gaps (GAP-23..41) verified resolved in spec text and aligned with cisternal source code, yielding no new genuine spec gaps while remaining in draft status pending implementation tests.
- [261106_final_report](audits/261106_final_report.md) — Executive summary and synthesis of 3-phase spec drive: recon, research, 4 adversarial audit cycles, final verdict, open gaps, and unverified elements. *Superseded by cycle 5: its acceptance and zero-gap verdict are withdrawn.*

## Research
- [261106_recon_findings](research/261106_recon_findings.md) — Static code audits of assumptions A1-A9 and survey of existing precursors C0-C6 across cisternal, praxia, and bathos.
- [261106_research_findings](research/261106_research_findings.md) — Prior art and literature foundations for agent tool/skill usage tracking, MCP discoverability, progressive disclosure budgets, and hook-based nudging.
- [261017_skill-frontmatter-schema](research/261017_skill-frontmatter-schema.md) — What Claude Code reads from SKILL.md frontmatter, why triggers is inert, the listing budget, and what cisternal export now carries
- [260624_m10-1-epic-closeout-audit](research/260624_m10-1-epic-closeout-audit.md)
- [260624_m10-2-adversarial-review](research/260624_m10-2-adversarial-review.md)
- [260624_m10-2-epic-closeout-audit](research/260624_m10-2-epic-closeout-audit.md)
- [260624_m10-3-epic-closeout-audit](research/260624_m10-3-epic-closeout-audit.md)
- [260624_m10-4-adversarial-review](research/260624_m10-4-adversarial-review.md)
- [260624_m10-epic-closeout-audit](research/260624_m10-epic-closeout-audit.md)
- [260624_m11-1-epic-closeout-audit](research/260624_m11-1-epic-closeout-audit.md)
- [260624_m11-epic-closeout-audit](research/260624_m11-epic-closeout-audit.md)
- [260624_m12-1-epic-closeout-audit](research/260624_m12-1-epic-closeout-audit.md)
- [260624_m12-adversarial-review](research/260624_m12-adversarial-review.md)
- [260624_m12-hash-parity-spike](research/260624_m12-hash-parity-spike.md)
- [260624_m33-epic-closeout-audit](research/260624_m33-epic-closeout-audit.md)
- [260624_m5-epic-closeout-audit](research/260624_m5-epic-closeout-audit.md)
- [260624_m6-epic-closeout-audit](research/260624_m6-epic-closeout-audit.md)
- [260624_m7-2-adversarial-review](research/260624_m7-2-adversarial-review.md)
- [260624_m7-2-epic-closeout-audit](research/260624_m7-2-epic-closeout-audit.md)
- [260624_m7-epic-closeout-audit](research/260624_m7-epic-closeout-audit.md)
- [260624_m8-epic-closeout-audit](research/260624_m8-epic-closeout-audit.md)
- [260624_m9-epic-closeout-audit](research/260624_m9-epic-closeout-audit.md)
- [260623_2712-docs-hygiene-closeout](research/260623_2712-docs-hygiene-closeout.md)
- [260623_2713-native-validate-closeout](research/260623_2713-native-validate-closeout.md)
- [260623_m12-3-adversarial-review](research/260623_m12-3-adversarial-review.md)
- [260623_m12-3-epic-closeout-audit](research/260623_m12-3-epic-closeout-audit.md)
- [260623_m12-3-recon](research/260623_m12-3-recon.md)
- [260623_m12-4-adversarial-review](research/260623_m12-4-adversarial-review.md)
- [260623_m12-4-epic-closeout-audit](research/260623_m12-4-epic-closeout-audit.md)
- [260623_m12-5-rust-parity-slugs-closeout](research/260623_m12-5-rust-parity-slugs-closeout.md)
- [260623_m12-epic-audit-adversarial-review](research/260623_m12-epic-audit-adversarial-review.md)
- [260623_m12-epic-audit](research/260623_m12-epic-audit.md)
- [260623_m31-epic-closeout-audit](research/260623_m31-epic-closeout-audit.md)
- [260623_m31-research](research/260623_m31-research.md) — M3.1 Agent-Asset Export — Research Synthesis
- [260623_m31a-epic-closeout-audit](research/260623_m31a-epic-closeout-audit.md)
- [260623_m31b-antigravity-scope](research/260623_m31b-antigravity-scope.md)
- [260623_m32-entry-point-packaging](research/260623_m32-entry-point-packaging.md)
- [260623_m32-epic-closeout-audit](research/260623_m32-epic-closeout-audit.md)
- [260623_m4-epic-closeout-audit](research/260623_m4-epic-closeout-audit.md)
- [260618_m3-agent-asset-export-research](research/260618_m3-agent-asset-export-research.md) — M3 Agent-Asset Export — Research Synthesis

## Decisions
- [260817_graph_annotate-graph_query-designated-canonical-praxia-family-corpus-kg-tool](decisions/260817_graph_annotate-graph_query-designated-canonical-praxia-family-corpus-kg-tool.md) — Ratifies praxia's existing graph_annotate/graph_query rig-run flows (backed by graphify-praxia-adapter, wrapping upstream graphify) as the canonical static content/code knowledge-graph tool across the Praxia family, in lieu of building a separate cisternal-packaged plugin. Logs two hardening gaps as praxia backlog items.
- [260817_procedural-recall-layer-graphiti-et-al-defer-adoption-pre-registered-revisit-criteria](decisions/260817_procedural-recall-layer-graphiti-et-al-defer-adoption-pre-registered-revisit-criteria.md) — Fresh 3-lens customizing-tools jury on adopting a temporal/episodic agent-memory dependency (Graphiti vs mem0 vs cognee vs Letta) to complement graphify's static content graph. Verdict: defer, no driving use case yet; pre-registers Graphiti (pinned >=0.28.2, FalkorDB Lite backend) as the default if/when one emerges, with mem0 as the faster fallback for non-temporal needs.

## Preregistration

## Reference

## Roadmaps

## Archive

## Misc

## Superpowers
> Skill outputs live in `.praxia/docs/superpowers/plans/` and `.praxia/docs/superpowers/specs/.
- [plans](superpowers/plans/) — brainstorming + writing-plans outputs
- [specs](superpowers/specs/) — specification outputs

