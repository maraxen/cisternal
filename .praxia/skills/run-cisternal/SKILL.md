---
name: run-cisternal
description: Build, run, and drive cisternal — the telemetry substrate + agent-asset export CLI/library. Use when asked to run cisternal, start its CLI, test the assets export/inspect/validate flow, exercise the telemetry API (init/tool/wire/span/emit_event), or verify a plugin bundle before publishing.
---

cisternal is a Python library + CLI (`cisternal` console script), not a
GUI/server app — it's driven by importing it directly and by invoking
its `assets`/`telemetry` subcommands. The primary agent handle is
`.praxia/skills/run-cisternal/driver.py`, which does both in one pass:
imports the library and calls `init()`/`@tool`/`wire()` against a real
`fastmcp.FastMCP()` server, then shells out to the real `cisternal`
console script for `telemetry doctor` and `assets export/inspect`.

All paths below are relative to the repo root (`cisternal/`), not to
this skill directory.

## Prerequisites

Python 3.13, managed entirely through `uv` — no system packages needed
beyond what's already on a standard Ubuntu box.

## Setup

```bash
uv sync --group dev
```

This installs `cisternal` itself (editable), `fastmcp`, `cyclopts`,
`opentelemetry-sdk`, and the dev toolchain (`pytest`, `ruff`, `ty`).

## Run (agent path)

```bash
uv run python .praxia/skills/run-cisternal/driver.py --out /tmp/cisternal_export
```

The driver runs three stages and prints one `PASS`/`FAIL` line per stage,
then a final `RESULT: PASS`/`RESULT: FAIL`:

| stage | what it does |
|---|---|
| library API | `cisternal.init()` into a temp log dir, registers a `@cisternal.tool`, calls `wire()` against a real `fastmcp.FastMCP()` server, asserts the tool shows up in `await server.list_tools()` (not just the registry snapshot — see Gotchas), then `span()`/`emit_event()`/`status()`. |
| cli telemetry doctor | Runs `uv run cisternal telemetry doctor --json`, parses the JSON report, asserts `schema_version == 1`. |
| cli assets export/inspect | Runs `uv run cisternal assets inspect --manifest .praxia/manifest.toml` and asserts this very skill (`run-cisternal`) is present in the reported bundle, then `uv run cisternal assets export ... --out <dir>` and asserts `skills/run-cisternal/SKILL.md` was actually written. |

`--out` is optional; omit it to use a throwaway temp dir. Exit code is
`0` iff all three stages pass.

### Driving the CLI directly (no driver script)

For a narrower check than the full driver, the individual commands work
standalone:

```bash
uv run cisternal telemetry doctor                       # human-readable
uv run cisternal telemetry doctor --json --strict        # CI-shaped, exit 1 on any warn/fail
uv run cisternal assets inspect --manifest .praxia/manifest.toml
uv run cisternal assets export --manifest .praxia/manifest.toml \
  --surface claude --out /tmp/cisternal_export
uv run cisternal assets validate --manifest .praxia/manifest.toml --surface claude
```

`assets export` always exits `0` — see Gotchas. Check stderr, not the
exit code, to know whether an export silently dropped something.

### Direct invocation (most PRs touch this layer)

Most changes to cisternal are library-level (registration/, telemetry/,
assets/, export/), not CLI-level. For those, skip the CLI/driver
entirely and import-and-call:

```python
import cisternal
cisternal.init(log_dir="/tmp/x")
@cisternal.tool
def f(x: int) -> int: return x * 2
from cisternal import wire          # NOT cisternal.wire — see Gotchas
import fastmcp
registry = wire(fastmcp.FastMCP("t"), expected=["f"])
```

## Run (human path)

There is no long-running server or GUI to leave open — `cisternal
telemetry doctor` and `cisternal assets ...` are one-shot commands that
exit immediately. Running them directly (`uv run cisternal <subcommand>`)
*is* the human path; nothing to Ctrl-C.

## Test

~490 test functions across `tests/` as of this writing. On a harness
with a whole-suite pytest guard (see Gotchas), run a subdirectory or
file instead of the bare suite:

```bash
uv run pytest tests/test_registration_init.py -q   # verified: 15 passed
uv run pytest tests/cli/ -q                         # a subdirectory
```

The `golden_matrix` and `integration` markers are for export-trust
digest parity and an OTLP collector respectively — exclude both if
running unguarded:

```bash
uv run pytest -m "not golden_matrix and not integration"
```

## Gotchas

- **A bare `uv run pytest` (no path/marker/`-k`) can be hard-blocked** on
  harnesses that run a whole-suite memory guard (this repo's own
  `~/.claude/rules/local-compute-limits.md` on the WSL2 dev box, e.g.)
  — it errors out before running anything, with a message pointing at a
  remote runner. Not a cisternal bug; run a subdirectory/file/`-k`
  selector locally instead, per the Test section.
- **`cisternal.wire` is not directly callable per the type checker (`ty`)** —
  `wire` and `WiredRegistry` are lazy re-exports via `cisternal.__init__`'s
  `__getattr__`, so `ty` infers `cisternal.wire` as type `object` and
  flags `cisternal.wire(...)` as `call-non-callable`. It works fine at
  runtime; use `from cisternal import wire` (as the test suite does) to
  avoid the false positive rather than suppressing it inline.
- **A tool registered via `@cisternal.tool` + `wire()` can look right in
  the registry and still be broken on the real FastMCP server.** The
  registry snapshot (`WiredRegistry.mcp_tools`) and the actual
  `server.add_tool(...)` call are two different code paths — a past bug
  (`wire()` name-override, cisternal#6) had the registry showing the
  correct tool name while FastMCP silently registered under the raw
  function's `__name__` instead. Always assert against
  `await server.list_tools()`, not just the registry object — the
  driver's library-API stage does this on purpose.
- **`cisternal assets export` always exits `0`, even when it silently
  drops assets.** A skill/agent with an empty `body` (unreadable file,
  bad manifest path) is dropped from the bundle with only a stderr
  warning — the exit code and the presence of *some* output files both
  look successful. Treat any non-empty stderr as a real failure; don't
  infer correctness from `$?` or from `ls` on the output dir.
- **Manifest `path = "..."` entries resolve relative to the plugin root
  (the directory that *contains* `.praxia/`), not the manifest file's own
  directory — `ManifestAssetSource` takes `.praxia/manifest.toml`'s
  parent-of-parent, not its parent (fixed praxia-conformant in #25,
  0.1.1a4; see `developing-cisternal-tools`'s `agent-asset-export.md`
  reference for the full rule).** This repo's own manifest declares
  `path = ".praxia/skills/run-cisternal/SKILL.md"` — **with** the
  `.praxia/` prefix, because paths are resolved from the plugin root
  down, the same as a skill outside `.praxia/` (e.g.
  `path = "agent_assets/skills/foo/SKILL.md"`). Do **not** climb out
  with `../` — that resolves *above* the plugin root under this
  convention, one level too far. A caller that still assumes the old
  manifest-directory-relative rule and works around it with a shallower
  symlink will get every asset silently dropped (see the Gotcha above)
  with no error above stderr — this bit contemplex's own
  `plugin_export.py` integration exactly this way.
- **`~/.cisternal/logs` can report `writable: no` in `telemetry doctor`
  purely from sandboxing, not a real permissions problem.** Under this
  harness's default Bash sandbox, `$HOME/.cisternal` isn't on the
  writable allowlist, so the doctor's writability probe fails even
  though the directory is genuinely writable outside the sandbox. Don't
  read a `log_dir_writable: fail` from an agent-run doctor check as a
  cisternal bug without first checking whether the check itself ran
  sandboxed.

## Troubleshooting

- **`python -m cisternal.cli ...` prints nothing and exits 0.** The
  `cisternal` console script works because `pip`/`uv` generate an entry
  point that calls `app()` on import; `cisternal/cli.py` itself has no
  `if __name__ == "__main__":` guard, so running the module directly
  with `-m` imports it and does nothing. Use `uv run cisternal ...` (the
  installed console script), not `uv run python -m cisternal.cli ...`.
- **`assets inspect`/`export` silently omit a skill you just added to
  `.praxia/manifest.toml`.** Re-check the `path` is relative to
  `.praxia/` (see Gotchas above) and that the target file actually has
  non-empty content — an empty or missing `SKILL.md` is dropped, not
  errored.
