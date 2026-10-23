# Changelog

All notable changes to cisternal are recorded here. The project is beta: the public API
(`wire`, `tool`, the telemetry functions, the assets manifest and CLI) is expected to hold,
but may still change before `1.0`. Entries are written per change and grouped under the release
that ships them; unreleased work sits under "Unreleased".

## Unreleased

## 0.1.4 (2026-10-23)

`<tool> plugin install|update` can now install into Antigravity.

### Added

- **`plugin install antigravity` / `plugin update antigravity`** (#63). The Antigravity
  bundle is emitted into a temporary directory named after the plugin and handed to
  `agy plugin install <dir>`, which copies it to `~/.gemini/config/plugins/<name>/`,
  replacing any earlier copy. `--agy-bin` picks the binary. Antigravity plugins carry no
  version, so every run reinstalls; `update` refuses when `agy plugin list --json` does
  not show the plugin. `--scope` (other than `user`), `--marketplace` and
  `--prune-shadowed` are Claude-only and are refused for antigravity.

### Fixed

- **Sub-app cache no longer stale-hits when `id(app)` is reused** (#62). A
  garbage-collected `App`'s id could be reused and short-circuit the "already a command,
  not a group" check; each cache key now tracks a weakref to its parent.

### Changed

- **`customizing-tools` skill listing text trimmed** (#61) to concrete triggers; the
  skill body is unchanged.

## 0.1.3 (2026-10-17)

Skill export now follows the SKILL.md frontmatter schema Claude Code actually reads.

### Changed

- **`triggers` is no longer exported.** Claude Code ignores a `triggers` key (unknown
  frontmatter keys are dropped silently), so the field never influenced skill selection. A
  skill's legacy trigger phrases are folded into `when_to_use` as a trailing
  `Triggers: a, b, c.` sentence, which Claude Code appends to `description` in the skill
  listing. `triggers` stays accepted as a deprecated manifest and frontmatter input.
- **Fold cost.** Folding makes those phrases count against Claude Code's skill-listing
  budget (1% of the context window by default, `skillListingBudgetFraction`) and the
  1,536-character per-skill cap, where the ignored `triggers` key cost nothing. Across
  seventy-two skills in ten projects the fold adds about 10,200 characters.
- **Rust-parity emitters are unchanged** and still write only `name` and `description`.

### Added

- **`SkillAsset` models the documented frontmatter keys**: `when_to_use`, `paths`,
  `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`,
  `disallowed-tools`, `model`, `effort`, `context`, `agent`, `shell`, `license`,
  `compatibility`. Keys at their absent value are omitted, so a skill that sets none exports as
  before. Read from the manifest entry (which wins) and from the SKILL.md frontmatter, parsed
  with a real YAML parser. Not yet modelled: `hooks`, `background`, `metadata`.
- **Loader warnings** for invalid YAML in a SKILL.md frontmatter (Claude Code loads such a
  skill with empty metadata), for source keys the export does not carry, for
  `description` + `when_to_use` over 1,536 characters, and for forbidden characters in a name.
- **`cisternal assets skillmod --manifest <path>... [--apply]`** migrates a plugin's sources
  from `triggers` to `when_to_use`. Dry run by default; edits are textual, and a skill is only
  written after a re-parse shows every other key unchanged and the exported listing text
  identical.

### Fixed

- A `---` inside a frontmatter value no longer ends the block early when a SKILL.md is split.

## 0.1.2 (2026-10-16)

First non-prerelease. Promotes 0.1.1a15 unchanged in code.

### Changed

- **Development status is now Beta** (`Development Status :: 4 - Beta`), and this release is
  published as a regular release rather than a pre-release, so consumers can depend on
  `cisternal>=0.1.2` without opting their resolver into prereleases.

## 0.1.1a15 (2026-10-02)

### Added

- **`wire()` rich CLI contract (#30).** A declarative `CliContract` gives the CLI side of
  `wire()` its own behaviour without touching the MCP surface. Fields: `exit_codes`
  (exception type to an int 1..255 or an `(exc, ctx) -> int | None` handler, resolved along
  the exception's MRO), `format_success`, `options` (CLI-only options, never passed to the
  tool), `prepare` (runs before dispatch, may mutate `ctx.arguments`), `help` and `show`.
  Attach it per `wire()` call (`wire(cli_contract=...)`), per tool
  (`@cisternal.tool(cli_contract=...)`) or per tool name from the wiring site
  (`wire(cli_contracts={name: contract})`); a tool contract refines the wire-level one
  field by field (`CliContract.merged_over`).
- New public names, exported from `cisternal` and `cisternal.registration`:
  `CliContract`, `CliOption`, `CliContext`, `json_option`, `default_report`,
  `exit_code_attr`, `cli_command` and `cli_group`. `cli_command(fn, ...)` builds the same
  CLI callable `wire()` would, for hand-written composite commands. `exit_code_attr` covers
  int-valued attributes only; string or enum codes need a handler with a lookup table.
- **Nested and pre-existing command groups.** `cli_group` accepts a path
  (`"flow visuals"` or `("flow", "visuals")`); `wire(cli_group_help={...})` gives each
  level help text; a user-constructed `App` already mounted at a group name is adopted
  instead of raising `CommandCollisionError`; `cisternal.cli_group(app, path, help=None)`
  returns the same sub-App `wire()` uses.
- `ToolEntry.cli_contract` and `register(..., cli_contract=)` / `tool(..., cli_contract=)`.
- **Onboarding guide:** `docs/guides/wire-onboarding.md` (linked from the README). Its
  worked examples are executed by `tests/test_docs_examples.py`.

### Fixed

- A tool module with `from __future__ import annotations` that annotates a parameter with a
  name `wired.py` does not import (`Annotated`, `Path`, `Parameter`, ...) no longer raises
  `NameError` from `wire(..., app)`. CLI annotations are resolved per parameter against the
  tool module's globals, also through `functools.wraps` decorators such as `timed_command`.
  A return type imported only under `TYPE_CHECKING` no longer matters. Verified on CPython
  3.13. bathos' post-`def` `__annotations__` workaround keeps working and is no longer
  needed.

### Changed

- With no contract, `wire()` behaves as before (same stderr bytes, exit codes, return
  values, telemetry and `app.command(name=...)` arguments), with these observable edges:
  the registered CLI callable's `__annotations__` no longer carries a `return` key (its
  `__signature__` still does); and `wire()` now validates every CLI callable and name
  before its first `add_tool` / `app.command` call, so a name planned twice at one level,
  or already present on the App, raises `CisternalWireError` up front instead of
  `CommandCollisionError` partway through registration. A failed `wire()` leaves the server
  and the App untouched.
- Whitespace in a `cli_group` string now separates path segments.
- `pyproject.toml` bounds `cyclopts` to `>=4.18.0,<5`: the contract builder uses a few
  cyclopts internals (`default_name_transform`, `Parameter.get_negatives`,
  `Parameter.combine`).
