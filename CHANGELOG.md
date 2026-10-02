# Changelog

All notable changes to cisternal are recorded here. The project is alpha: APIs may change
without notice before `1.0`. Entries are written per change and grouped under the release
that ships them; unreleased work sits under "Unreleased".

## Unreleased

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
