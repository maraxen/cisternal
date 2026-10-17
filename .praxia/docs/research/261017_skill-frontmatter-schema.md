---
title: Skill frontmatter schema and the cisternal exporter
description: What Claude Code reads from SKILL.md frontmatter, why triggers is inert, the listing budget, and what cisternal export now carries
status: draft
task_id: 261017_skill-frontmatter-schema
date: '261017'
confidence: medium
sources: code.claude.com/docs/en/skills (fetched 2026-10-17 by a claude-code-guide subagent); Claude Code 2.1.302 binary string scan; cisternal source at origin/main 04c6b25
---
# Skill frontmatter schema and the cisternal exporter

## Question

A maraxiom skill (`maraxiom-schematics`) showed no description in the session's skill list although
its published frontmatter matched skills that did. Does Claude Code read the `triggers` key every
cisternal-exported skill carries, and what does the exporter need to emit?

## Findings

Tags: **verified** = read in code or the binary here; **docs** = stated on the skills docs page;
**unconfirmed** = not stated there, not probed.

1. **`triggers` is not a Claude Code key.** *verified*: absent from the 2.1.302 frontmatter schema
   list (`name, description, model, allowed-tools, argument-hint, arguments,
   disable-model-invocation, user-invocable, effort, shell, version, when_to_use, paths, hooks,
   context, agent, ...`); the only `.triggers` hits in the binary are unrelated (a memory-attachment
   counter, a session idle state). *docs*: "Claude Code ignores a field it doesn't recognize without
   reporting an error." So all ~55 cisternal-exported skills carry an inert key, and the phrases in it
   never influenced skill selection. The `SkillAsset` docstring claiming otherwise was an unverified
   assumption.
2. **Valid keys** (*docs*, all optional): `name`, `description`, `when_to_use`, `paths`,
   `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`,
   `disallowed-tools`, `model`, `effort`, `context`, `agent`, `background` (v2.1.218+), `hooks`,
   `shell`; accepted but inert: `metadata`, `license`, `compatibility`. `version`, `created_by`,
   `improved_by`: **unconfirmed** (in the binary's list, absent from the docs table).
3. **What drives model-invoked loading:** `description` plus `when_to_use` only. They are
   concatenated and capped at **1,536 characters** per entry (*docs*; setting
   `skillListingMaxDescChars`).
4. **Listing budget** (*docs*): the whole listing is limited to **1% of the context window**. Past
   that, descriptions are dropped to names only, **least-recently-invoked first**; names are always
   listed. Knobs: `skillListingBudgetFraction`, env `SLASH_COMMAND_TOOL_CHAR_BUDGET`,
   `skillOverrides: {"x": "name-only"}`; `/doctor` and `/context` show the cost.
   This is the likely cause of the original symptom (shown vs missing descriptions did not track
   length, quoting or key shape across 55 skills; all 55 frontmatters parse as YAML). *Inferred, not
   measured*: the session list was never compared with the budget.
5. **`paths`** (*docs*): globs; the skill auto-loads only when working with matching files.
   **Unconfirmed:** whether a path-gated skill is hidden from the listing until a match, and what
   counts as "working with" a file.
6. **YAML failure mode** (*docs*): on a parse error the skill still loads, but with *empty metadata*
   (`/name` works, description matching does not). An unquoted `: ` in a description is such an error.
   `claude plugin validate <skills-dir>` (v2.1.233+) finds these.
7. **Stricter consumers** (*docs*): claude.ai upload and the Skills API accept only `name`,
   `description`, `license`, `compatibility`, `metadata`, `allowed-tools`; any other key errors there.

## What the exporter did (verified, `cisternal` origin/main 04c6b25)

`SkillAsset` had `name, description, body, triggers, resources`. `_load_skills` stripped the source
frontmatter and kept only a single-line `description`; `format_skill_markdown` wrote `name`,
`description`, `triggers`. Every other key a skill author set was dropped. `_split_frontmatter` split
on the first `---` anywhere, so a value containing `---` truncated the block.
`_rust_emit.skill_markdown_rust` (praxia-agent-assets byte parity) writes only `name` and
`description`, and is unchanged.

## Change (branch `wt/261017-skill-frontmatter-schema`)

- `SkillAsset` gains the modelled keys (defaults = absent, so skills that set none export
  byte-identically). `triggers` stays as a deprecated input.
- Export never writes `triggers`; phrases are folded into `when_to_use` as a trailing
  `Triggers: a, b, c.` (`SkillAsset.effective_when_to_use`).
- The loader parses source frontmatter with a real YAML parser, merges manifest entry (wins) over
  source, unions manifest and source `triggers`, and warns on: invalid YAML, a key the export does
  not carry, description + `when_to_use` over 1,536 chars, a forbidden character in `name`.
- `_split_frontmatter` matches whole-line `---` delimiters.
- `cisternal assets skillmod --manifest <path>... [--apply]` rewrites each skill's source frontmatter
  and manifest entry (textual edits; comments and key order survive) and refuses to write unless a
  re-parse shows every other key unchanged and the exported description + `when_to_use` identical.

## Dry-run survey (2026-10-17, main checkouts, which may be behind origin)

72 skills in 10 projects would migrate (xtrax 5, gemini-notebook-mcp 1, jaxlint 8, myxcel 7, bathos 9,
alynxr 6, aminx 6, maraxiom 12, praxia 14, affigit 4). Skipped, with the reason `skillmod` reports:

- 3 contemplex and 1 praxia `SKILL.md` have no frontmatter (their description lives in the manifest;
  export-time folding still covers them, only source cleanup is skipped).
- alynxr-fold-campaigns, praxia processing-praxia-traces and developing-fast-frugal-trees have
  **invalid YAML in the source frontmatter** (unquoted `: `): used straight from the repo they would
  load with empty metadata. The exported copy is re-quoted by `_yaml_scalar`, so installed plugins
  are fine.
- alphex's manifest points at a SKILL.md that does not exist.
- Over the 1,536 cap: alynxr-fold-campaigns (2,632), praxia teacher-panel-eval (1,629).

## Trade-off to watch

Folding adds **10,218 characters** (mean 150, max 531 per skill) to the always-loaded listing across
these 72 skills. Those characters were free while `triggers` was ignored; they now count against the
1% budget, so descriptions of rarely-invoked skills may drop to names sooner. Mitigations: shorten
trigger lists when migrating, raise `skillListingBudgetFraction`, or pin low-use skills with
`skillOverrides`. Not measured: how much of the budget the current plugin set uses.

## Not done (tech debt, filed as praxia debt 2822 to 2827)

- `hooks`, `background`, `metadata` frontmatter keys are not modelled (reported as "not carried").
- A string-form `allowed-tools` / `arguments` is kept as one list item (the docs accept a
  space-separated string).
- Agents (`AgentAsset`) still carry only `tools` and `model`; the agent frontmatter schema was not
  researched.
- `_rust_emit` parity emitters ignore the new keys.
- Non-Claude exporters (cursor, opencode, pi, jcode, copilot, antigravity) share
  `format_skill_markdown`, so they now receive Claude-only keys; their schemas were not checked.
- The 1,536 cap is warned about, not enforced or auto-shortened; truncation by Claude Code is
  silent.
- No test against `claude plugin validate`; no probe of how `paths` affects the listing.
- Open check: does a fresh session load `maraxiom-schematics` from a plain request, given its
  description is missing from the list?
