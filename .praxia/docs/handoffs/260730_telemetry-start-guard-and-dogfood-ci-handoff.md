---
title: Telemetry start-event guard + export-dogfood CI repair — Session Handoff
task_id: 260730_telemetry-start-guard-and-dogfood-ci
session_id: ab832484-10bf-4222-a1f7-948e163292b4
status: in_progress
phase: both PRs merged; one deferred follow-up open (rust-parity re-enablement)
date: 2026-07-30
---

# Telemetry start-event guard + export-dogfood CI repair — Session Handoff

> NOTE: the praxia MCP `handoff(create)` and `transduction_log(append_daily)` calls
> could NOT be written — the `praxia` MCP server (core) is not connected in this
> session (only unrelated plugins matching "praxia" in the name, e.g.
> `nlm-praxia-adapter`, were reachable via ToolSearch; `mcp__praxia__*` /
> `mcp__plugin_praxia_core__*` returned no results). This filesystem doc is the
> handoff of record until that server is available again. (Same failure mode as
> the M1 foundation handoff at `260616_cisterna-m1-foundation-handoff.md`.)

## Summary

Two independent pieces of work landed on `main` this session, both merged:

1. **PR #12** — `span()`/`aspan()`/`CisternalMiddleware`/`traced_tool` all emitted
   their `.start` telemetry event *before* their local try/except, unlike the
   `.end` event. Fixed via `AdapterBase._safe_emit_event` (guards only the
   `emit_event()` call inside `emit_start`/`emit_end`/`emit_error`, deliberately
   leaving the `ALLOWED_NAMES`/`_swallow_name_error` check outside the guard so
   the AC-NAMEFREEZE-4 test escape hatch still propagates `AssertionError`
   normally) plus a shared `_emit_start()` helper in `telemetry/span.py`. Went
   through an independent reviewer + auditor subagent pass; both findings
   (missed `v2_decorator.py` parity gap, guard swallowing `AssertionError`,
   duplicated guard logic, missing regression tests) were addressed before merge.
   Merged as `cc9a3e9`.
2. **PR #13** — `export-dogfood` CI had failed on **every run in its visible
   history (25/25)**, across two unrelated pre-existing issues (neither
   introduced by PR #12): `examples/minimal_emitter` still referenced the
   project's pre-rename package name `cisterna` instead of `cisternal`
   (dependency, entry-point group, imports, README) so its install step could
   never resolve; and the `rust-parity` job checks out the *private*
   `maraxen/praxia` repo with the default `GITHUB_TOKEN`, which has no
   cross-repo access, so it always fails "Repository not found". Fixed the
   rename; disabled `rust-parity` via `if: false` with an explanatory comment
   per user direction ("just bypass the workflow for now and flag a note")
   rather than touching auth. Verified live: first fully-green `export-dogfood`
   run in the workflow's history (run 30546324947). Merged as `df0f0a6`.

## What's on `main` (HEAD `df0f0a6`)
- `src/cisternal/adapters/base.py` — `AdapterBase._safe_emit_event` guard.
- `src/cisternal/adapters/{v2_decorator,v3_middleware}.py` — plain
  `emit_start` calls (guard lives in base.py now).
- `src/cisternal/telemetry/span.py` — shared `_emit_start()` helper.
- `tests/test_core.py`, `tests/test_mcp.py` — 5 new regression tests forcing
  the leaf emission calls to raise and asserting the wrapped code still
  completes.
- `examples/minimal_emitter/{pyproject.toml,src/minimal_emitter/emitter.py,
  tests/test_emitter.py,README.md}` — renamed `cisterna.*` → `cisternal.*`.
- `.github/workflows/export-dogfood.yml` — `rust-parity` job gated `if: false`.

## Open / deferred (not done this session)
1. **(only real follow-up)** Re-enable `rust-parity`: needs a PAT or
   deploy-key with read access to `maraxen/praxia` wired in as a repo secret
   (used via `with: token:` on the second `actions/checkout@v4` step in that
   job), or `praxia` made public. This is an infra/auth decision for the repo
   owner — explicitly deferred, not blocking.
2. Cosmetic only, not touched: root-level `main.py` (`print("Hello from
   cisterna!")`) is an unreferenced `uv init` leftover from before the
   `cisterna`→`cisternal` rename. Harmless; not wired into `pyproject.toml` or
   CI. Low priority cleanup if anyone wants it gone.

## Failed attempts
None — both fixes worked on the first verified attempt (subagent review round
on PR #12 caught real gaps *before* merge, not after).

## Next steps
1. If/when cross-repo auth for `maraxen/praxia` is set up, flip
   `.github/workflows/export-dogfood.yml`'s `rust-parity.if` back from `false`
   and re-verify the job (it was passing via `rust-parity` before the repo
   went private / token scope changed — root cause of *when* it started
   failing wasn't dated further back than "always, in visible history").
2. Optional cleanup: delete or repurpose stray root `main.py`.
3. No action needed on the telemetry guard or the `minimal_emitter` rename —
   both are done, merged, and covered by regression tests.
