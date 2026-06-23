# Epic closeout audit — M3.1a (#2486)

**task_id:** `260623_epic-audit_m31a`  
**closed_epic:** #2486 M3.1a — manifest source + validate + capability layer  
**next_epic:** #2487 M3.1b — Cursor + Copilot emitters  
**parent_epic:** #2326 M3.1 (remains open until #2487 completes)  
**date:** 2026-06-23

## Shipped vs claimed

| Acceptance criterion | Status | Evidence |
|---------------------|--------|----------|
| AC-M31a-1 | PASS | `tests/test_assets_manifest.py::test_manifest_loads_skills_agents_hooks_commands` |
| AC-M31a-2 | PASS (nit) | `tests/test_assets_manifest.py::test_composite_manifest_wins_on_command_conflict`; validate exits 1 on conflicts in `cli.py:validate_assets` but no dedicated CLI test |
| AC-M31a-3 | PASS | `tests/test_assets_capability.py::test_resolve_tools_read_search_claude_code` |
| AC-M31a-3b | PASS | `tests/test_assets_manifest.py::test_manifest_agent_default_tools_from_frontmatter` |
| AC-M31a-4 | PASS | `tests/test_export_claude_bodies.py::test_default_emitter_matches_names_only_mode`; M3 suite `tests/test_export_claude.py` still green |
| AC-M31a-5 | PASS | `tests/test_export_claude_bodies.py::test_emit_command_bodies_writes_md_and_name_strings` |
| AC-M31a-6 | PASS | `tests/test_cli_assets_validate.py` (names_only + with_command_bodies golden) |
| AC-M31a-7 | PASS | `tests/test_cli_assets_inspect.py::test_inspect_prints_json_no_writes` |
| AC-M31a-8 | PASS | `tests/test_cli_assets_validate.py::test_validate_missing_command_path_exits_one` |
| AC-M31a-9 | PASS | `tests/test_assets_manifest.py::test_registry_bundle_commands_only` |
| AC-M31a-10 | PASS | `tests/test_cli_assets_inspect.py::test_inspect_resolve_tools_enriches_agents` |

**Spec scope note (L14):** Workflows/pipelines/snippets are not parsed in M3.1a manifest loader (`src/cisterna/assets/manifest.py`). Spec marks these as validate-only and not loaded into IR — deferred; file as debt if validate-only parsing is required before M3.1b.

## Git delta (M3.1a execution)

Commits `20d231e` → `c554294` (5 waves W1–W5):

- +1701 / −48 lines across 28 files
- New modules: `manifest.py`, `composite.py`, `capability.py`, `load.py`, `inspect_json.py`, `validate_golden.py`
- CLI: `assets inspect`, `assets validate`, `export --manifest`, `--emit-command-bodies`
- Golden harness: `tests/golden/claude/{names_only,with_command_bodies}/`

## Regression status

```
uv run pytest -q  → 253 passed (2026-06-23)
uv run ruff check .  → All checks passed!
```

Baseline at M3 closeout: 220 tests (`daily.jsonl` 260619_m3-complete). Net +33 tests for M3.1a.

## Open risks for next epic (#2487 M3.1b)

1. **Surface parity** — Cursor/Copilot emitters must not break Claude golden defaults (AC-M31a-4 regression).
2. **Vendor maps** — `vendor_tools.toml` has structure for cursor/copilot but only claude_code is exercised; M3.1b must extend maps and golden per-surface.
3. **Hook/skill/agent emission** — IR loads kinds in M3.1a but Claude emitter still names-only for non-commands; M3.1b emits agents/skills per spec L13 note.

## Debt / lessons

| Item | Severity | Recommendation |
|------|----------|----------------|
| AC-M31a-2 validate-on-conflict CLI test | nit | Add `test_validate_conflict_exits_one` in follow-up or M3.1b hygiene |
| L14 workflow validate-only parsing | deferred | `debt add` if PI wants pre-M3.1b validate depth |
| Parent #2326 | tracking | Complete #2486 now; close #2326 after #2487 |
| Untracked `.praxia` spec/sprint artifacts | housekeeping | Commit or `.gitignore` per project policy |

## Verdict

**VERIFY: APPROVE** — M3.1a sprint DoD satisfied; safe to mark #2486 complete and route to M3.1b (#2487) triage.
