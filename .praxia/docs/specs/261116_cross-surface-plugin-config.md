---
title: 'Cross-surface plugin configuration: what each surface can carry and the explicit fallback'
description: Which surfaces can carry a plugin's telemetry setting (spans, shadow), how cisternal renders it where a surface needs help, and what is said and done everywhere else.
status: draft
task_id: 261117_cross-surface-plugin-config
date: '261116'
backlog_ids: ''
adversarial_review: ''
---
# Cross-surface plugin configuration: what each surface can carry and the explicit fallback

## Goal

A user on any surface (claude, cursor, antigravity, copilot, jcode, opencode, pi) can set maraxiom's telemetry (`spans`, `shadow`) in the way that surface supports, no rendered option blocks an install or an enable, and `cisternal telemetry where` says which way applies on the surface in use.

## Non-goals

- A new typed-option mechanism for a surface that has none, or writing Cursor's dashboard values (confirmed 261116).
- Changing resolver layers other than how an unexpanded placeholder is read, or the Claude Code path (spec 261116_telemetry-config-layers).
- Rendering anything for Cursor or Antigravity (owner decisions D2 and D3).

## Prior art

- Sidecar `.praxia/docs/research/261116_surface-plugin-option-mechanisms.md`: per-surface Q1-Q4, probes P1 and P2, Cursor quotes C1.
- maraxiom spec `261116_telemetry-config-layers`, decisions D2 (a saved plugin option sits above the machine file and below the environment) and D3 (`inherit|on|off` pickers).

## Problem

Only Claude Code has a typed option with a saved value in a readable local file. Cursor's variable values are set by team admins in a web dashboard; Antigravity's `variables` are untyped and make the plugin install disabled until filled in (probe P1); Copilot, jcode, opencode and pi declare no plugin options. What reaches an MCP server differs: Antigravity's inherits the user's environment (P2's validator text), opencode's is documented to inherit it, Copilot's CLI documents that only `PATH` is inherited, and for pi and jcode the docs are silent. So the existing environment layer (`CISTERNAL_TELEMETRY_*`, highest rank) already reaches some servers and not others, and a placeholder that does not expand reaches the server as literal text, which today makes the resolver fail closed.

## Assumptions

| # | Assumption | Tag |
|---|---|---|
| A1 | Every exporter already writes the MCP server's `env` from `McpAsset.env` | **verified** (`export/claude.py:209`, `cursor.py:104`, `antigravity.py:150`, `jcode.py:104`, `pi.py:69`, `opencode.py:54`, `copilot.py:52,70`) |
| A2 | `_parse_switch` treats an empty value as no opinion and any other unrecognised value as an error; `CISTERNAL_TELEMETRY` (comma list) ignores unknown tokens | **verified** (`telemetry_setting.py:211-221`, `:224-234`) |
| A3 | An Antigravity plugin declaring `mcpServers.<s>.variables` installs disabled and `agy plugin enable` refuses; an undeclared `${X}` installs enabled; the validator says the server inherits the agent's environment | **verified** by probe (agy 1.5.9, scratch HOME; sidecar P1, P2). Runtime expansion in a live session: **unverified** (needs credentials) |
| A4 | Cursor documents only a team-admin dashboard path for plugin variables and says nothing on unset values or environment inheritance | **verified absence** in three pages (sidecar C1) |
| A5 | Copilot CLI inherits only `PATH` into an MCP server configured with `/mcp add`: "All other environment variables must be configured here." | **verified from docs** for `/mcp add`; for a plugin-provided server (`plugin.json`/`.mcp.json`) **unverified** |
| A6 | Copilot's portable MCP config expands `${NAME}` and `${NAME:-default}` in `command`, `args` and `env` | **verified from docs** (VS Code MCP configuration page, quoted in the sidecar); runtime **unverified** |
| A7 | opencode's local MCP server inherits the parent environment; pi's and jcode's behaviour is not documented | opencode: **docs-only, second-hand** (summarising fetch); pi, jcode: **not found** |
| A8 | A literal placeholder in `CISTERNAL_TELEMETRY_SHADOW` would today make `mrx telemetry where` exit 3 and make maraxiom's bridge resolve the behaviour off | **verified** by reading A2's raise path; the bridge's never-raises behaviour is from spec 261116 FR-10 |

## Functional requirements

- FR-1: An unexpanded placeholder means no opinion. In `_parse_switch`, a value that is entirely a placeholder in any of the forms `${NAME}`, `${NAME:-default}`, `{env:NAME}`, `$NAME` or `%NAME%` is treated like an empty value, and the decision records a one-time notice "ignored unexpanded placeholder in <VAR>". Any other unrecognised value still raises as today.
- FR-2: Copilot pass-through. When a bundle declares `[plugin.telemetry]`, the Copilot exporter adds `CISTERNAL_TELEMETRY`, `CISTERNAL_TELEMETRY_SPANS` and `CISTERNAL_TELEMETRY_SHADOW` to the `env` of every MCP server it writes, each with the value `${NAME:-}`, so the user's exported value (or empty) reaches the server. It never replaces an `env` entry of the same name that the manifest declares. A bundle with no `[plugin.telemetry]` renders byte-identical output.
- FR-3: No other exporter renders anything for telemetry options. The Claude exporter keeps `userConfig`; the Cursor, Antigravity, jcode, opencode and pi outputs are unchanged. An exported Antigravity plugin from a bundle with `[plugin.telemetry]` installs enabled and passes `agy plugin validate` with no placeholder warning.
- FR-4: `cisternal telemetry where` ends with a "How to set it" note, one line per surface: Claude Code (`/plugin configure`, saved plugin option), Antigravity and opencode (export `CISTERNAL_TELEMETRY_*` in the environment the agent runs in; documented to reach the server), Copilot (the exported variable reaches the server through the pass-through), Cursor (no per-user mechanism documented), jcode and pi (no documented mechanism; machine file), and everywhere (`mrx telemetry enable|disable` for the machine file). The note says "documented" where the claim is from docs, never "verified" for an unprobed surface.
- FR-5: Surface-native values, if a surface later supplies one, sit at the plugin-option position of the resolver and a value set for the running surface wins over Claude's saved option; the environment, `pyproject.toml` and the machine-file choices keep their rank. This is recorded as an ordering rule; no code reads such a value now.
- FR-6: The spike is durable: the sidecar and the probe scripts are in the repository.
- FR-7: The consumer follows: maraxiom regenerates its packaged snapshot if the export changed it, and its reference doc names the per-surface routes.

## Levels

| Level | Claude | Copilot | Antigravity, opencode | Cursor | jcode, pi |
|---|---|---|---|---|---|
| Manifest declares the setting | `[plugin.telemetry]` | same | same | same | same |
| Rendered plugin carries it | `userConfig` | env pass-through (FR-2) | nothing | nothing | nothing |
| User sets it | `/plugin configure` | export `CISTERNAL_TELEMETRY_*` | export `CISTERNAL_TELEMETRY_*` (inherited) | not documented | machine file |
| Every process agrees | yes (resolver reads `settings.json`) | MCP server and shell only if exported | same | no | no |

## Acceptance

- [FR-1] `pytest tests/test_telemetry_resolver.py -q -k placeholder`
- [FR-2] `pytest tests/test_export_copilot_telemetry_passthrough.py -q`
- [FR-3] `pytest tests/test_export_surfaces_no_telemetry_options.py -q`
- [FR-4] `pytest tests/test_telemetry_where.py -q -k surfaces`
- [FR-5] `rg -n 'plugin-option position' .praxia/docs/specs/261116_cross-surface-plugin-config.md`
- [FR-6] `test -s .praxia/docs/research/261116_surface-plugin-option-mechanisms.md`
- [FR-7] `pytest tests/maraxiom/test_agent_plugin.py -q`

Notes on the checks. Paths under `tests/maraxiom/` run in the maraxiom repository; the others run in cisternal. FR-3's antigravity half uses `agy plugin validate` when `agy` is installed and skips otherwise. There is no CI for maraxiom, so each PR body records the named-file run.

## Risks

- **R1** Copilot may not strip the environment for a plugin-provided server, or may not expand `${NAME:-}` there. If it does not expand, FR-1 reads the literal as no opinion, so the pass-through is harmless. If it inherits the full environment and does not expand, the literal placeholder would shadow the inherited value (the hazard Antigravity's validator names), and a user's exported setting would be lost. The build stage must probe Copilot offline (the CLI is installed) before FR-2 ships; if it cannot be probed, FR-2 is dropped.
- **R2** The design is smaller than the first scope: with no native rendering on Antigravity or Cursor, the only rendered change is Copilot's pass-through and the rest is explicit fallback. That is deliberate (D2, D3) because both native paths cost a user something (a disabled plugin, a team-admin dashboard).
- **R3** The environment route reaches MCP servers only. A shell or hook that never inherited the exported variable falls back to the machine file; `where` says so (FR-4).
- **R4** Surface docs change. Each row's evidence date is in the sidecar; re-probe on a new surface version.

## Decisions

- **D1 (owner, 261116)** Surface-native values sit at the plugin-option position, never at the environment layer, so a value typed by someone else cannot override the user's own environment, `pyproject.toml` or `mrx telemetry` choice.
- **D2 (owner, 261116)** Antigravity: render nothing. Declaring `variables` makes the plugin install disabled (A3).
- **D3 (owner, 261116)** Cursor: render nothing for now. Only a team-admin dashboard path is documented (A4).
- **D4 (owner, 261116)** When two surfaces both hold a value, the running process's own surface wins within the plugin-option position (FR-5).
- **D5 (orchestrator, 261116; owner may overturn)** The pass-through is limited to Copilot, the one surface whose docs state that the environment is not inherited (A5). pi and jcode are not rendered because their behaviour is undocumented; opencode and Antigravity inherit.
