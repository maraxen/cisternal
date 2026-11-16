---
title: 'Cross-surface plugin configuration: what each surface can carry and the explicit fallback'
description: Which surfaces can carry a plugin's telemetry setting (spans, shadow), what cisternal renders (nothing beyond Claude Code), and what it says and does everywhere else.
status: draft
task_id: 261117_cross-surface-plugin-config
date: '261116'
backlog_ids: ''
adversarial_review: 'round 1 (Sonnet, 6 blockers, all resolved in this revision)'
---
# Cross-surface plugin configuration: what each surface can carry and the explicit fallback

## Goal

cisternal tells a user on any surface (claude, cursor, antigravity, copilot, jcode, opencode, pi) how to set maraxiom's telemetry (`spans`, `shadow`) on it, never renders an option that blocks an install or an enable, and a placeholder that a surface fails to expand never turns a setting off. `cisternal telemetry where` prints the per-surface routes; it does not detect which surface it runs under.

## Non-goals

- A new typed-option mechanism for a surface that has none, or writing Cursor's dashboard values (confirmed 261116).
- Rendering anything for Antigravity, Cursor or Copilot (owner decisions D2, D3; D5).
- Changing resolver layers other than how an unexpanded placeholder is read, or the Claude Code path (spec 261116_telemetry-config-layers).
- Fixing the exporter defects found on the way (listed in the sidecar); they are filed as debt.

## Prior art

- Sidecar `.praxia/docs/research/261116_surface-plugin-option-mechanisms.md`: per-surface Q1-Q4, probes P1, P2 and P3, Cursor quotes C1.
- maraxiom spec `261116_telemetry-config-layers`, decisions D2 (a saved plugin option sits above the machine file and below the environment) and D3 (`inherit|on|off` pickers).

## Problem

Only Claude Code has a typed option with a saved value in a readable local file. Cursor's variable values are set by team admins in a web dashboard; Antigravity's `variables` are untyped and make the plugin install disabled until filled in (probe P1); Copilot, jcode, opencode and pi declare no plugin options. What reaches an MCP server differs, and is mostly undocumented: the Antigravity validator says its server inherits the agent's environment (P2), opencode's is described that way second-hand, Copilot's docs say only `PATH` is inherited for servers added with `/mcp add` and document no generic `${VAR}` expansion for plugin stdio servers, and for pi and jcode the docs are silent. Rendering a pass-through for the environment variables is therefore not supportable by evidence on any surface (D5). What is supportable: the existing layers (the environment variables, the machine file, `mrx telemetry`) are the cross-surface mechanism, and the user needs to be told so; and a placeholder that reaches the resolver unexpanded, which the Antigravity validator says happens ("starts with the placeholders as written"), must not fail the setting closed.

## Assumptions

| # | Assumption | Tag |
|---|---|---|
| A1 | Every exporter already writes the MCP server's `env` from `McpAsset.env`; the Claude exporter alone renders `config_options` | **verified** (`export/claude.py:209,230-240`, `cursor.py:104`, `antigravity.py:150`, `jcode.py:104`, `pi.py:69`, `opencode.py:54`, `copilot.py:52,70`) |
| A2 | `_parse_switch` treats an empty value as no opinion and any other unrecognised value as an error; `CISTERNAL_TELEMETRY` (comma list) already ignores unknown tokens | **verified** (`telemetry_setting.py:211-221`, `:224-234`) |
| A3 | An Antigravity plugin declaring `mcpServers.<s>.variables` installs disabled and `agy plugin enable` refuses; an undeclared `${X}` installs enabled; the validator says the server inherits the agent's environment and that an undeclared placeholder is "passed as is" | **verified** by probe (agy 1.5.9, scratch HOME; sidecar P1, P2). Runtime behaviour in a live session: **unverified** (needs credentials) |
| A4 | Cursor documents only a team-admin dashboard path for plugin variables and says nothing on unset values or environment inheritance | **verified absence** in three pages (sidecar C1) |
| A5 | Copilot's plugin docs show `command` as a string with a separate `args` array, never an array, and document `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` (not generic `${VAR}`) for stdio plugin servers | **verified from docs** (cli-plugin-reference and the VS Code agent-plugin reference, verbatim, sidecar P3). cisternal's Copilot exporter writes `command` as an array (`copilot.py:51,69`): a probable exporter defect |
| A6 | Copilot CLI plugin MCP servers cannot be inspected offline: a plugin installs, but `copilot mcp list` and `get` show no plugin servers, for an array `command` and for the documented string form alike | **verified** by probe (Copilot CLI 1.0.63 via bun, scratch HOME; sidecar P3) |
| A7 | opencode's local MCP server inherits the parent environment; pi's and jcode's behaviour is not documented | opencode: **docs-only, second-hand** (summarising fetch); pi, jcode: **not found** |
| A8 | A literal placeholder in `CISTERNAL_TELEMETRY_SHADOW` or `_SPANS` makes `mrx telemetry where` exit 3 and makes maraxiom's bridge resolve the behaviour off | **verified** by reading A2's raise path; the bridge's never-raises behaviour is from spec 261116 FR-10 |
| A9 | `TelemetryDecision` has no notice field; `_notice` prints once per process to stderr | **verified** (`telemetry_setting.py:126-135,199-203`) |
| A10 | `build_where_report` takes no surface argument | **verified** (`probe/telemetry_where.py`, `cli.py:214` passes none) |

## Functional requirements

- FR-1: An unexpanded placeholder means no opinion. In `_parse_switch`, a value that after stripping whitespace fully matches `${NAME}`, `${NAME:-text}`, `{env:NAME}`, `$NAME` or `%NAME%`, with NAME matching `[A-Za-z_][A-Za-z0-9_]*`, is treated like an empty value, and `_notice` prints once per process "ignored unexpanded placeholder in <VAR>". `where` and its exit code do not show the notice. Any other unrecognised value still raises as today. `_consumer_switch` needs no change (A2).
- FR-2: No exporter renders telemetry options except Claude (`userConfig`). For a bundle that declares `[plugin.telemetry]`, the cursor, antigravity, copilot, jcode, opencode and pi outputs are byte-identical to the same bundle without that table, and contain no `variables` key and no `${` placeholder that the baseline lacks. Where `agy` is installed, the exported Antigravity plugin also installs enabled and passes `agy plugin validate` with no placeholder warning.
- FR-3: `cisternal telemetry where` ends with a "How to set it" section that is the same for every surface (A10): Claude Code (`/plugin configure`, the saved plugin option); Antigravity (export `CISTERNAL_TELEMETRY_*` in the environment the agent runs in; the agy validator states that the server inherits it); opencode (same, docs-only second-hand); Copilot, Cursor, jcode and pi (no documented per-user plugin mechanism; use the environment variable where the shell and agent share it, or the machine file); and everywhere `mrx telemetry enable|disable` for the machine file. Wording says "the validator says", "docs say" or "not documented", never "verified" for an unprobed surface. The JSON report carries the same lines under `how_to_set`.
- FR-4: The spike is durable: the sidecar and the probe scripts are in the repository.
- FR-5: The consumer follows without code: maraxiom's reference doc `261016_cisternal-telemetry.md` names the per-surface routes. Its packaged snapshot `src/maraxiom/agent_plugin.json` is bundle data, not exporter output, so an exporter-only change cannot alter it; the parity test is a regression check.
- FR-6: The exporter defects found on the way are listed with their evidence under "Exporter side findings" in the sidecar, and filed as praxia debt (ids in the PR body): Copilot `command` as an array, opencode's legacy `mcp.<name>` form, pi's `.pi/mcp.json` inside a package, jcode's `plugin.json` that no documented loader reads, and Antigravity's `env` pass-through that the validator says to leave out.

## Levels

| Level | Claude | Antigravity, opencode | Copilot, Cursor, jcode, pi |
|---|---|---|---|
| Manifest declares the setting | `[plugin.telemetry]` | same | same |
| Rendered plugin carries it | `userConfig` | nothing | nothing |
| User sets it | `/plugin configure` | export `CISTERNAL_TELEMETRY_*` | environment variable where shared, else machine file |
| Every process agrees | yes (resolver reads `settings.json`) | MCP server and shell only if exported | no |

## Acceptance

- [FR-1] `pytest tests/test_telemetry_resolver.py -q -k placeholder`
- [FR-2] `pytest tests/test_export_surfaces_no_telemetry_options.py -q`
- [FR-3] `pytest tests/test_telemetry_where.py -q -k how_to_set`
- [FR-4] `test -s .praxia/docs/research/261116_surface-plugin-option-mechanisms.md`
- [FR-5] `pytest tests/maraxiom/test_agent_plugin.py -q`
- [FR-6] `rg -c 'Exporter side findings' .praxia/docs/research/261116_surface-plugin-option-mechanisms.md`

Notes on the checks. FR-5 runs in the maraxiom repository, the others in cisternal. FR-2's Antigravity install check skips when `agy` is absent, so the offline part is the byte comparison against the no-telemetry baseline. FR-6's command is a presence check of the sidecar list; the praxia debt records live in its database and the PR body lists their ids.

## Risks

- **R1** FR-1 removes a loud failure: a shell-quoting slip such as `CISTERNAL_TELEMETRY_SHADOW='$FOO'` now means no opinion with a one-time stderr notice instead of exit 3. Accepted: a placeholder that a surface failed to expand is the case the rule exists for, and the notice names the variable.
- **R2** The design is small and says so: no surface other than Claude Code gets a rendered option. That is deliberate (D2, D3, D5): the native paths cost a user a disabled plugin (Antigravity) or a team-admin dashboard (Cursor), and the Copilot pass-through rests on undocumented expansion that cannot be probed offline (A5, A6).
- **R3** The environment route reaches only processes that inherit the exported variable. `where` says so (FR-3). Antigravity's and opencode's inheritance is evidence from a validator message and a second-hand docs summary, not a live-session probe.
- **R4** Surface docs change; each sidecar row carries its source and date. Re-probe on a new surface version.

## Decisions

- **D1 (owner, 261116)** Surface-native values, if a surface later supplies one, sit at the plugin-option position of the resolver (spec 261116 D2), never at the environment layer, so a value typed by someone else cannot override the user's own environment, `pyproject.toml` or `mrx telemetry` choice; when two surfaces both hold a value, the running process's own surface wins within that position (D4). No code reads such a value now.
- **D2 (owner, 261116)** Antigravity: render nothing. Declaring `variables` makes the plugin install disabled (A3).
- **D3 (owner, 261116)** Cursor: render nothing for now. Only a team-admin dashboard path is documented (A4).
- **D4 (owner, 261116)** When two surfaces both hold a value, the running process's own surface wins within the plugin-option position (see D1).
- **D5 (orchestrator, 261116; owner may overturn)** No Copilot pass-through. The first draft's FR-2 added `${NAME:-}` entries to the Copilot MCP env. Dropped: Copilot's plugin docs document no generic `${VAR}` expansion for stdio plugin servers (A5), the exporter writes `command` in a form the docs never show, and plugin servers cannot be inspected offline (A6), so the rendering could not be verified and could shadow an inherited value with literal text.
