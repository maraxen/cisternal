---
session_id: b8307550
topic: M3.2 (#2563): entry_point emitter plugin discovery and CLI dispatch registry — how to refactor without breaking golden digests
task_type: constrained-technical
winner: OPTION-C+E HYBRID: metadata entry_points with per-surface factory callables, unified export/registry.py get_emitter(surface, **kwargs), fail-closed CLI exit 2, golden zero-drift regression suite
created_at: 2026-06-23T20:34:35.031069+00:00
---

# Brainstorm: M3.2 (#2563): entry_point emitter plugin discovery and CLI dispatch registry — how to refactor without breaking golden digests

## Problem Frame
Frame correct: buildable spec with entry_point discovery, unified get_emitter registry, golden zero-drift gate. Fixed constraints as stated. Negotiable: register_emitter override API vs metadata-only; unknown surface exit 2 vs never-raise Result.

## Idea Pool
- [ai] OPTION-A METADATA-ONLY: [project.entry-points."cisterna.emitters"] registers 4 built-ins; export/registry.py loads via importlib.metadata.entry_points; no runtime register API.
- [ai] OPTION-B METADATA-PLUS-OVERRIDE: entry_points default + register_emitter(name, cls) for tests; metadata wins on conflict with warning.
- [ai] OPTION-C HYBRID-D (recommended): OPTION-A metadata + OPTION-D single dispatch module; fail-closed CLI exit 2 on unknown surface; register_emitter() test-only via _TEST_OVERRIDES dict not public API.
- [ai] OPTION-E FACTORY-ENTRY: entry points target factory callables get_claude_emitter(emit_command_bodies: bool) -> Emitter to preserve Claude flag without registry state.
- [user] PEGS: get_emitter(surface) → Emitter.emit → golden digest unchanged. Components: pyproject entry-points, registry.py, validate_golden, cli.py. Risk: ClaudeEmitter(emit_command_bodies=) needs factory or kwargs passthrough.
- [user] Converge on OPTION-C HYBRID with factory entry points: each built-in registers a zero-arg factory; get_emitter(surface, **kwargs) passes emit_command_bodies only to claude. Single registry module replaces _EMITTERS dict.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Pre-mortem: third-party emitter factory raised during export, breaking never-raise CLI contract. Mitigation: get_emitter catches load/instantiate errors, logs, returns None; CLI exits 2. Emitter.emit() never-raise unchanged.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Frame correct: buildable spec with entry_point discovery, unified get_emitter registry, golden zero-drift gate. Fixed constraints as stated. Negotiable: register_emitter override API vs metadata-only; unknown surface exit 2 vs never-raise Result.
**When** implementing OPTION-C+E HYBRID: metadata entry_points with per-surface factory callables, unified export/registry.py get_emitter(surface, **kwargs), fail-closed CLI exit 2, golden zero-drift regression suite
**Then**
  - [ ] _add specific measurable criteria_
