---
title: "Tool-Surface Triage: Cycle 5 Reconciliation Audit"
description: "Cycle 5: spec revised per revision brief A1-A16 and decisions R1-R5, status back to draft; challenger/defender pass plus second-agent re-review found 12 new genuine gaps (GAP-23..34; 3 fixed, 9 open) and 2 unverified risks."
status: complete
task_id: 261106_tool-surface-triage
date: '261106'
author: "cycle5_reviser (challenger_c5 / defender_c5, same agent); cycle5_rereviewer (Part 4)"
verdict: OPEN_GAPS
---
# Cycle 5 Reconciliation Audit: Tool-Surface Triage Spec
Claimed by: cycle5_reviser (revision, challenger_c5, defender_c5), cycle5_rereviewer (Part 4 re-review)

- **Target spec**: `.praxia/docs/specs/261106_tool-surface-triage.md` (post-cycle-5 revision, `status: draft`)
- **Input**: `/tmp/claude-1000/spec_revision_brief.md` (sections A1–A16 and resolved decisions R1–R5)
- **Date**: 2026-11-06

## Limits of this audit
- The challenger and the defender were the same agent, one after the other, and that agent also wrote the revision. This is not an independent review; a separate agent should repeat it.
- No code was executed against the spec's claims. Only these were checked by reading code: line references for `SkillAsset` (`bundle.py:98`), `FIELD_KINDS` (`skill_schema.py:29`), `listing_advisory` (`skill_schema.py:153`), `resolve_log_dir_from_env` (`pipeline.py:222`), and the absence of any `session_id_var.set` in `src/`. The E1 and E4 arithmetic and Wilson intervals were computed.
- `~/.claude/projects/` is not readable from this sandbox, so the transcript path (A3) is taken from the brief.

## Part 1: Revision applied
Every item A1–A16 and R1–R5 is applied; the spec's Cycle 5 changelog maps each one to the section changed. The brief's A15 said "C4b delta also registered", which R2 supersedes: the spec registers C4b's descriptive quantities and has no delta. The cycle 4 probe conclusions, the `accepted` status, the gap-count claim and the loop-termination claim are removed. The Cycle 4 changelog entry now records the probes as argued, not tested.

## Part 2: Challenger findings (new, against the revised text)

### GAP-23: C5 depends on C1's registration scanner, and nobody owns cache rebuilds
C5 step 4 reads `active_servers.json`, "written by the C1 registration scanner and rebuilt when ... mtime is newer". The spec does not say who rebuilds it. C1 is a manual CLI, so the hook would have to rebuild. That puts a registration scan inside the 150 ms budget. Otherwise the cache stays missing, which means "inactive" and no nudge ever fires. The graph also lacks a C1 (scanner) → C5 edge.

### GAP-24: The dangling-name check fails validate, but "a tool name a skill quotes" is undefined
R3 makes the dangling check a hard failure now. The spec does not define which tokens in a skill body count as quoted tool names: `mcp__...__...` forms only, `server/tool`, or bare words like `run_sql`. Bare words would give false failures (ordinary identifiers read as tools). A loose definition would fail `assets validate` on shipped skills.

### GAP-25: The CLI tokenizer does not handle compound shell commands
`parse_cli_command` handles prefix wrappers and global flags only. Agent Bash calls are often compound: `cd x && bth sql ...`, `bth sql ... | head`, `a; bth show`, `$(...)`. The spec does not say whether each segment is tokenized, so C0 undercounts CLI calls (E1 re-derivation) and C5 misses nudges. There is no control for it.

### GAP-26: The PostToolUse writer and the PreToolUse reader can resolve different sessions dirs
The derived-data resolver includes a `pyproject.toml` layer, which depends on the working directory. The two hooks run as separate processes, and the working directory can differ between calls. If the writer and reader resolve different directories, suppression fails silently: the nudge fires right after an MCP error, which is the case E4 is about. The spec does not say which project root hooks use.

### GAP-27: The C3 precision criterion is ambiguous for a registered threshold
"Precision ≥ 0.80 on a 50-turn sample, reported with its Wilson 95% interval" does not say whether the point estimate or the lower bound must reach 0.80. At n = 50 the two differ by about 0.1 (a point estimate of 0.80 has a lower bound of about 0.67). A pre-registered threshold has to fix this before the first run.

### RISK-01: Errored MCP calls may not reach `PostToolUse`
If Claude Code sends failed tool calls to a separate hook event instead of `PostToolUse`, protocol-level errors (server crash, timeout) never reach the ledger.

## Part 3: Defender dispositions

| id | disposition | reasoning |
|---|---|---|
| GAP-23 | **Conceded** | The text names a writer (the C1 scanner) that does not run on any schedule. The fix is a decision: either the hook rebuilds with a bounded scan counted in the latency budget, or C5 ships an install-time or `SessionStart` step that writes the cache. Either way the graph needs a scanner → C5 edge. |
| GAP-24 | **Conceded** | A hard failure needs a defined input. A minimal fix: quoted tool names are only tokens matching `mcp__<...>__<...>` or `<server>/<tool>` where `<server>` is a registered server; bare words are never checked. Add a control where a bare identifier matching no tool does not fail. |
| GAP-25 | **Conceded** | E1 counts came from an untracked script that may have handled this, but the spec's tokenizer interface does not. Fix: split on `&&`, `||`, `;`, `|` outside quotes and tokenize each segment; skip command substitution; add tokenizer cases for each form. |
| GAP-26 | **Conceded (narrow)** | Only the `pyproject` layer can differ; the arg, env and XDG layers agree across hook processes. Fix: hooks resolve the project root from `CLAUDE_PROJECT_DIR` (or the payload's `cwd` from the first call of the session, if that variable is not provided; both UNVERIFIED), and a test runs writer and reader from different working directories. |
| GAP-27 | **Conceded (needs a user decision)** | Both readings are defensible. The user should choose point estimate vs lower bound before the sidecar is committed. |
| RISK-01 | **Not a gap; unverified risk** | Cisternal adapters return errors in-band (A8), so the main error path reaches `PostToolUse` with a success flag and is classified by the envelope rules. The per-adapter error fixtures, captured "as delivered to the hook", will show whether a separate event is needed. Stays under A6. |

## Part 4: Re-review by a second agent (challenger then defender)
Claimed by: cycle5_rereviewer

A second agent, which did not write the revision, re-read the brief and the revised spec and checked them against the worktree source. It confirmed Parts 1–3 and found the issues below. The source checks were: `bundle.py:98`, `skill_schema.py:20–45, 98–153`, `export/_markdown.py:77` (`format_skill_markdown`), `adapters/base.py:248–388`, `pipeline.py:222`, `cli.py:517, 809`, `.praxia/manifest.toml`, and `git ls-files | grep SKILL.md`. It also recomputed E1, the E4 Wilson intervals and the GAP-27 figure (40/50 → Wilson 95% 0.670–0.888). This is still not a test run: nothing in the spec was executed.

### Challenger findings
- **GAP-28 (prior revision's error, fixed in spec):** C5 printed the hard-coded name `mcp__bathos__run_sql`. When bathos is installed as a plugin, the registered tool is `mcp__plugin_bathos_bathos__run_sql` (Shared Definitions' own example), so the nudge pointed at a tool that does not exist in that session. The canonical key cannot be turned back into a raw name.
- **GAP-29 (open):** The C0 source glob `~/.claude/projects/<slug>/*.jsonl` is not recursive. On this machine, Claude Code subagent transcripts live at `~/.claude/projects/<slug>/<session-id>/subagents/agent-<id>.jsonl`; the evidence is the task-output symlinks under `/tmp/claude-1000/-home-marielle-projects-cisternal/*/tasks/*.output`. As written, the `subagent_headless` stratum is always empty and A9 cannot be decided. Cycle 4's "subagent transcript segregation" probe argued the opposite and is withdrawn.
- **GAP-30 (open):** C1 does not define "repository" for `enable-per-project` or per-repo N. Worktree sessions get their own slug (seen: `-home-marielle-projects-cisternal--claude-worktrees-agy-plugin-install`). Keying on slug splits one repository across its worktrees, which lowers per-repo N (fewer recommendations clear the floor) and changes the 80% concentration.
- **GAP-31 (factual error, fixed in spec):** The migration target and the C6 path were `src/cisternal/assets/skills/`, which does not exist. Shipped skills are `[[plugin.skills]]` entries in `.praxia/manifest.toml` pointing at `.praxia/skills/<name>/SKILL.md`.
- **GAP-32 (prior revision's error, fixed in spec):** The C0 synthetic fixture planted `bathos/run_sql` "in all three raw forms" inside a transcript. Shared Definitions says a bare name resolves only inside a manifest that gives the server, so a bare `run_sql` tool_use in a transcript has no server. The fixture contradicted the definition it tests.
- **GAP-33 (open):** The C2 dangling-name check (a hard fail under R3) checks against "registered tools". Active registrations are machine-local (`~/.claude.json`, `~/.claude/settings.json`), and in CI or a sandbox they are absent or different. So `assets validate` would pass on one machine and fail on another. The reference set must be hermetic, for example the tool names declared in manifests (`[families]` members plus `[verbs]` targets) or a committed tool inventory. This is separate from GAP-24, which asks which tokens count as quoted.
- **GAP-34 (open, needs a decision):** `format_skill_markdown` (`export/_markdown.py:77`) writes only the documented Claude Code keys, so `covers_families` and `distinctive_strings` are dropped from exported `SKILL.md`. C3 and C4a therefore work only where the source manifest is present. Skills from installed plugins (the bathos and other plugin skills that motivate this spec) carry no `distinctive_strings`, and C3 reports no opportunities for them. The spec does not say which skill sources C3 reads. Options: export the two keys (Claude Code ignores unknown frontmatter keys, per the `SkillAsset` docstring; other surfaces are unchecked), or limit C3 to skills with a source manifest and say so.
- **RISK-02 (unverified):** The C5 envelope rules for contemplex (`ok is False`) and myxcel (keys exactly `{error, message}`) are not checked against those servers. `contemplex.errors.err_envelope` is not importable here. `MyxcelAdapter.shape_ok` passes myxcel's own in-band errors through unchanged, and their keys may be more than `{error, message}`. The per-adapter fixtures will settle this; until then the rules are hypotheses.

### Defender dispositions
| id | disposition | reasoning |
|---|---|---|
| GAP-28 | **Conceded; fixed** | The cache now maps canonical key → registered raw name, and the nudge prints that raw name. |
| GAP-29 | **Conceded; open** | The path layout was observed (symlink targets), not assumed. Fix: C0 also reads `<slug>/<session-id>/subagents/*.jsonl` as the subagent stratum, and the Pre-0 probe confirms the layout. Left open because it extends the brief's A3 path. |
| GAP-30 | **Conceded; open** | Fix: key the repository on the git common dir of the record's `cwd` (worktrees fold into their main repository). The slug-to-repo mapping needs the Pre-0 probe. |
| GAP-31 | **Conceded; fixed** | Factual path error, checked with `git ls-files`. |
| GAP-32 | **Conceded; fixed** | The fixture uses both `mcp__` forms (3 + 2 = 5). The bare form stays in the canonical-key test. |
| GAP-33 | **Conceded; open** | Pairs with GAP-24. Both define the input of a check that R3 makes fatal, and both should be fixed before C2 ships. |
| GAP-34 | **Conceded; needs user decision** | Exporting the keys changes every surface's output. Limiting C3 narrows the stated goal. |
| RISK-02 | **Not a gap; unverified risk** | Already covered by the fixture requirement (A8). |

## Verdict
**OPEN_GAPS**. The first pass found 5 new genuine gaps (GAP-23 to GAP-27) and 1 unverified risk. The re-review (Part 4) found 7 more (GAP-28 to GAP-34) and 1 more risk. GAP-28, GAP-31 and GAP-32 were errors in how the revision applied the brief, and they are fixed in the spec. Still open: GAP-23 to GAP-27, GAP-29, GAP-30, GAP-33 and GAP-34. The user needs to decide GAP-27, the GAP-23 fix choice, and GAP-34. The spec stays `draft`.
