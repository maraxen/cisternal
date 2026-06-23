# Epic closeout audit — M3.1 (#2326)

**task_id:** `260623_epic-audit_m31`  
**closed_epic:** #2326 M3.1 — file/manifest AssetSource + four-surface export + capability + validate  
**child sprints:** #2486 M3.1a, #2487 M3.1b, #2559 M3.1c (all completed)  
**next_epic:** M3.2 — entry_point emitter plugins (+ deferred rev2 items)  
**date:** 2026-06-23

## Shipped vs claimed

### M3.1a (#2486) — 10 ACs

| AC | Status | Evidence |
|----|--------|----------|
| AC-M31a-1 | PASS | `tests/test_assets_manifest.py::test_manifest_loads_skills_agents_hooks_commands` |
| AC-M31a-2 | PASS | `tests/test_assets_manifest.py::test_composite_manifest_wins_on_command_conflict`; `tests/test_cli_assets_validate_conflict.py::test_validate_conflict_exits_one` |
| AC-M31a-3 | PASS | `tests/test_assets_capability.py::test_resolve_tools_read_search_claude_code` |
| AC-M31a-3b | PASS | `tests/test_assets_manifest.py::test_manifest_agent_default_tools_from_frontmatter` |
| AC-M31a-4 | PASS | `tests/test_export_claude_bodies.py::test_default_emitter_matches_names_only_mode` |
| AC-M31a-5 | PASS | `tests/test_export_claude_bodies.py::test_emit_command_bodies_writes_md_and_name_strings` |
| AC-M31a-6 | PASS | `tests/test_cli_assets_validate.py::test_validate_names_only_golden` |
| AC-M31a-7 | PASS | `tests/test_cli_assets_inspect.py::test_inspect_prints_json_no_writes` |
| AC-M31a-8 | PASS | `tests/test_cli_assets_validate.py::test_validate_missing_command_path_exits_one` |
| AC-M31a-9 | PASS | `tests/test_assets_manifest.py::test_registry_bundle_commands_only` |
| AC-M31a-10 | PASS | `tests/test_cli_assets_inspect.py::test_inspect_resolve_tools_enriches_agents` |

### M3.1b (#2487) — 8 ACs

| AC | Status | Evidence |
|----|--------|----------|
| AC-M31b-1 | PASS | `tests/test_export_cursor.py::test_cursor_emit_manifest_minimal` |
| AC-M31b-2 | PASS | `tests/test_export_copilot.py::test_copilot_emit_manifest_minimal` |
| AC-M31b-3 | PASS | `tests/test_export_hooks_surface.py::test_cursor_only_hook_not_in_copilot_export` |
| AC-M31b-4 | PASS | `tests/test_cli_assets_validate.py::{test_validate_cursor_golden,test_validate_copilot_golden}` |
| AC-M31b-5 | PASS | `tests/test_export_regression_m31b.py::test_claude_golden_unchanged_after_m31b` |
| AC-M31b-6 | PASS | `tests/test_export_cursor.py::test_cursor_omits_agents_key_when_no_bodies` |
| AC-M31b-7 | PASS | `tests/test_cli_assets_validate.py::test_validate_cursor_missing_skill_path_exits_one` |
| AC-M31b-8 | PASS | `tests/test_cli_assets_export_surface.py::test_export_surface_cursor_writes_layout` |

### M3.1c (#2559) — 6 ACs

| AC | Status | Evidence |
|----|--------|----------|
| AC-M31c-1 | PASS | `tests/test_export_antigravity.py::test_antigravity_emit_manifest_minimal` |
| AC-M31c-2 | PASS | `tests/test_export_hooks_surface.py::test_antigravity_only_hook_not_on_cursor_export` |
| AC-M31c-3 | PASS | `tests/test_cli_assets_validate.py::test_validate_antigravity_golden` |
| AC-M31c-4 | PASS | `tests/test_export_regression_m31c.py::test_prior_surface_goldens_unchanged` |
| AC-M31c-5 | PASS | `tests/test_cli_assets_export_surface.py::test_export_surface_antigravity_writes_layout` |
| AC-M31c-6 | PASS | `tests/test_assets_capability.py::test_resolve_tools_read_search_antigravity_cli` |

**Total:** 24/24 acceptance criteria have cited test evidence.

## Git delta (M3.1 epic execution)

Commits `20d231e` → `9e7a144` (15 commits across M3.1a/b/c):

- +2649 / −50 lines across 44 files under `src/` and `tests/`
- New emitters: `cursor.py`, `copilot.py`, `antigravity.py`, `hooks.py`, `_markdown.py`
- New assets layer: `manifest.py`, `composite.py`, `capability.py`, `validate_golden.py`, `inspect_json.py`
- CLI: `assets inspect`, `assets validate`, `export --surface`, `--emit-command-bodies`, `--manifest`
- Golden harness: `tests/golden/{claude,cursor,copilot,antigravity}/`

## Regression status

```
uv run pytest -q  → 275 passed (2026-06-23)
uv run ruff check .  → All checks passed!
```

Baseline at M3 closeout: 220 tests. Net +55 tests for full M3.1 epic.

## Spec / doc drift

| Item | Severity | Resolution |
|------|----------|------------|
| rev2 L10 lists AntigravityEmitter as M3.2 deferred | doc drift | Amended in W2 — shipped M3.1c #2559 |
| Debt #235 validate-on-conflict CLI test | **resolved** | `test_cli_assets_validate_conflict.py` shipped M3.1b W4 — close debt |
| L14 workflows/pipelines/snippets validate-only | deferred M3.2+ | No IR load; no validate parser yet |
| rev2 Deferred M3.2 still lists entry_point, WriterSink, snapshot API | accurate | Gates M3.2 brainstorm |

## Open risks for M3.2

1. **Packaging backend** — `pyproject.toml` uses `setuptools.build_meta` (not hatchling). Entry-point group `[project.entry-points."cisterna.emitters"]` must be validated with setuptools before spec lock (pre-mortem 93eb820f).
2. **Emitter dispatch** — `cli.py` hard-codes surface→emitter map; M3.2 plugins must not break default four-surface golden regression (AC-M31c-4).
3. **API surface** — `registration._snapshot()` is private; public accessor deferred — M3.2 should clarify Composite vs registry-only paths before plugin discovery.
4. **L14 validate depth** — workflow/snippet validate-only parsing may expand validate scope; keep separate from entry_point sprint unless PI merges.

## Debt / lessons

| Action | Item |
|--------|------|
| close | Debt #235 — satisfied by `test_cli_assets_validate_conflict.py` |
| backlog | M3.2 parent epic — entry_point emitter plugins |
| lesson | Inter-sprint audits (M3.1a) caught validate-on-conflict gap before M3.1b close |
| lesson | OPTION-C Antigravity split (M3.1c) avoided schema bet blocking Cursor/Copilot |

## Verdict

**VERIFY: APPROVE** — M3.1 epic DoD satisfied (24/24 ACs cited, 275 tests green). Safe to route `loop.current_phase` → **TRIAGE** for M3.2.
