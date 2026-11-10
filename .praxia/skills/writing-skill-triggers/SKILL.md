---
name: writing-skill-triggers
description: Use `writing-skill-triggers` when writing or shortening a skill's description or when_to_use, when a skill fails to fire or fires on the wrong task, or when `cisternal assets validate` warns about listing length.
covers_families: []
distinctive_strings:
  - "writing-skill-triggers"
  - "when_to_use"
  - "skillListingMaxDescChars"
  - "listing length"
---

# Writing skill triggers

## When to Use

Use `writing-skill-triggers` when writing or shortening a skill's description or when_to_use, when a skill fails to fire or fires on the wrong task, or when `cisternal assets validate` warns about listing length.

## Scope

A trigger is the `description` plus `when_to_use`: the only text a model sees when deciding whether
to load a skill. Its job is to match a moment, not to explain the skill.

## The budget is shared

Read from the Claude Code 2.1.318 binary, 2026-11-04:

- Each listing entry is `description - when_to_use`, cut at 1,536 characters (`skillListingMaxDescChars`).
- All skills share a pool of `context window × 4 × skillListingBudgetFraction` characters (default
  0.01). At the default on a 200k window that is 8,000 characters, about 72 per skill across 111 skills.
- Over the pool, the lowest-priority skills lose their whole description and show as a bare name.

So a long trigger can cost a different skill its trigger. `cisternal assets validate` prints an
advisory above 250 characters without failing. Aim shorter.

## The shape

Write these parts, in this order:

1. **The full scope.** `Use when <every kind of task the skill serves>`. Keep the broadest true
   statement: "writing or modifying JAX code", not "JAX code that hits a tracer error". If the skill
   is a gate, say `before` the action it guards.
2. **Distinctive strings.** The 2–5 terms only this skill would claim: commands, file names, error
   text, the user's own phrasing.
3. **The sibling boundary, only if another skill could take the same task.** `Not for X (use Y).`

Everything else belongs in the body: what the skill covers, its steps, its history.

```yaml
# Before, 761 characters (shortened here): what it covers, then every synonym
description: Use when cluster storage is full or filling — Disk quota exceeded, No space left on device, a file-count or inode cap... Covers reading byte AND inode limits per tier, flash vs HDD placement... - Triggers: disk quota exceeded, EDQUOT, ENOSPC, no space left, inode, file count, file cap, quota, df -i, du...

# After, 149 characters
description: Use when Engaging storage is full or filling ("Disk quota exceeded", "No space left on device", inode cap), before deleting or moving anything there.
```

## What shortening can break

Cutting words is usually safe; narrowing scope is not. A rewrite that listed only symptoms sent
"write a JAX function" to no skill. Remove words freely, but keep every kind of task the skill serves.

Generic words such as `error`, `cleanup` and `workflow` match everything, so they earn nothing.

## Editing

- In a cisternal plugin, edit the source SKILL.md or manifest. A rendered copy is overwritten at the
  next export.
- Run `cisternal assets skillmod --manifest .praxia/manifest.toml` to preview folding a legacy
  `triggers` manifest key into `when_to_use`, then add `--apply` to write it. Legacy triggers already
  count toward the listing length either way: they are emitted as a `Triggers: a, b, c.` sentence.

## Checking it fires

Write about five prompts that should fire the skill and five near misses that should not, including
a prompt for its closest sibling. Give fresh agents the skill listing and each prompt, and ask which
skill they would load. A shorter trigger passes only if it picks the same skills as the longer one.
For a repeatable check, put the prompts in an eval suite and run `claude plugin eval` on the plugin.
