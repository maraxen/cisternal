# Onboarding: one function, an MCP tool and a CLI command with `wire()`

`cisternal.wire(server, app, registry=...)` puts every `@cisternal.tool()` function on a
FastMCP server and on a `cyclopts.App`, with telemetry and recovery. This guide covers when
to use it instead of a hand-written CLI/MCP pair, the rules a tool body has to follow, and
the `CliContract` recipes that give the CLI side its own exit codes, rich output,
CLI-only options and help text, without touching the MCP surface.

Every Python example in the "worked example" sections is executed by
`tests/test_docs_examples.py`, against stubs for the consumer packages it imports
(`redsox`, `alphex`, `myxcel`, `maraxiom`, `contemplex`). Those names are consumer code;
the stubs live in `tests/fixtures/docs_prelude.py`. Blocks the tests do not execute say so.

## 1. Why

A tool that is written once as a plain function becomes four things at once:

- an MCP tool (`wire(server)`),
- a CLI command (`wire(server, app)` or `wire(None, app)`),
- telemetry on both (`cli.cmd_start` / `cli.cmd_end` on the CLI path, the middleware
  events on the MCP path),
- the optional recovery hook (`recovery=(is_recoverable, recover)`).

Without it, each consumer writes the function twice, once as a typer or cyclopts command
and once as an MCP tool, and the two drift. alphex and redsox show the pattern: alphex
wires only its MCP side and hand-writes a parallel CLI with the same five operations, and
redsox is CLI-only and hand-writes every command and its error handling.

The migration is not always right, and the guide does not pretend it is. alphex keeps its
parallel CLI **deliberately**: alphex supports Python 3.11 and its CLI must work without
cisternal and fastmcp, whose `mcp` extra installs only on Python 3.13 and later. `wire()`
does not remove that duplication on its own; for a project with that constraint the example
in section 3 is a pattern to read, not a migration to run.

Use `@tool` + `wire()` when the CLI command and the MCP tool are the same operation. Use
plain cyclopts when they are not (section 6).

## 2. Rules for tool bodies

The same function runs under MCP (no terminal, stdout is the protocol channel) and under
the CLI, so:

1. **Return data and raise domain exceptions.** The CLI side turns the return value into
   output (through `format_success` or cyclopts' `result_action`) and a raised exception
   into an exit code (through `exit_codes`). MCP turns a raised exception into a tool error.
2. **Never print or prompt in the body.** MCP has no TTY, and a prompt blocks the call
   forever. Prompts belong in a `prepare` hook (section 3, "Prepare and prompt").
3. **Never print a banner to stdout from a body.** It would corrupt `--json` output and
   MCP stdio. See "Banner" in section 3.
4. **Raise, do not catch-and-return an error envelope, unless you also plan for it.** A body
   that returns `{"error": ...}` exits 0 on the CLI because nothing raised. See the
   gotchas in section 5.

## 3. `CliContract` recipes

A `CliContract` is a frozen, declarative bundle with six optional fields:

| Field | What it does |
|---|---|
| `exit_codes` | `{ExceptionType: int \| handler}`: map a raised exception to an exit code (and optionally render its own report) |
| `format_success` | `(result, ctx) -> Any`: render the tool's return value |
| `options` | CLI-only options (`CliOption`, `json_option()`), injected into the CLI signature and never into the tool |
| `prepare` | `(ctx) -> None`: runs before dispatch and may mutate `ctx.arguments` (prompts, `chdir`, derived arguments) |
| `help` | `--help` text override for the command |
| `show` | `False` hides the command from `--help` |

With no contract anywhere, behaviour is byte-identical to a `wire()` without this feature.

**Precedence.** A contract attaches in two places: `wire(cli_contract=...)` (W, the default
for every command of the call) and a per-tool contract (T). T comes from
`@cisternal.tool(cli_contract=...)` on the tool, or from
`wire(cli_contracts={tool_name: contract})` at the wiring site. The effective contract is
`T.merged_over(W)`, field by field:

| Field | Effective value |
|---|---|
| `format_success`, `prepare`, `help`, `show` | T's if it is not `None`, otherwise W's. Hooks do not chain: a tool-level `prepare` replaces the wire-level one, and a tool that needs both calls W's from its own |
| `exit_codes` | `{**W.exit_codes, **T.exit_codes}`, T wins on an equal key. Resolution then runs over the merged map by the exception's MRO, so a T entry for a superclass does **not** shadow a W entry for a more specific subclass |
| `options` | `(*W.options, *T.options)`. A duplicate option name raises `CisternalWireError` |

A tool with both a decorator contract and a `cli_contracts` entry raises
`CisternalWireError`. So does a `cli_contracts` key that names no tool of the registry
(also when `app=None`). A contract on a tool wired with `app=None` is inert.
`merged_over` is public, so a consumer can compose contracts by hand.

### The exit map

`exit_codes` maps an exception class to either an `int` in 1..255 or a handler
`(exc, ctx) -> int | None`.

- An `int` prints the usual one-line report, `Error (<Type>): <message>` on stderr, and exits
  with that code. `{ValueError: 3}` is enough for many tools.
- A handler renders its own report and returns the exit code. Returning `None` means "not
  handled": the one-line report is printed and the exit is 1. A handler may return 0 to
  mean "handled, success". A handler that raises, or returns something that is not an int
  in 0..255, is logged at WARNING and falls back to the one-line report and exit 1.
- Resolution walks the exception's MRO, most specific class first, and dict order never
  matters. An exception with no entry keeps today's behaviour: the one-line report and
  exit 1. `SystemExit` always passes through unchanged and `KeyboardInterrupt` is never
  caught.
- `default_report(exc)` writes the exact one-line report. Call it from a handler that
  wants to add to it.
- `exit_code_attr(attr="exit_code", default=1, report=default_report)` is a ready-made
  handler: it calls `report(exc)` and returns `getattr(exc, attr)`. For myxcel,
  `{MyxcelError: exit_code_attr()}` exits with the raised subclass's own code
  (`ConfigError` is 2) through the MRO. Pass `report=` to replace the one-line report with
  the consumer's own, as the maraxiom example below does with myxcel's
  `[red]Error:[/red] {e}` line.

**`exit_code_attr` covers int-valued attributes only.** It falls back to `default` when the
attribute is missing, is a bool, is not an int, or is outside 1..255. A string or enum code
(contemplex's `ErrorCode` is a `StrEnum`) therefore needs a handler with a lookup table:
the contemplex example below is a `{ContemplexError: handler}` that renders a Panel and
returns `_EXIT_CODES.get(exc.code.value, 1)`, plus an `Exception` fallback that renders an
`INTERNAL` panel and exits 1.

Handlers run inside the command's error path, after the telemetry span has closed, so
telemetry still sees the original exception. A handler may be called with a partly built
`ctx` (`ctx.arguments == {}`) when argument binding failed.

#### Worked example: redsox, an exception becomes exit 2 with a report

redsox is CLI-only, so it wires with `server=None`. The tool keeps its `-c/--config` and
`-o/--out` options exactly as redsox declares them, and the exit handler prints the report
the way redsox does today. The module uses `from __future__ import annotations`, so
`ConfigOption` and the `out` annotation are strings that name `Annotated`, `Path` and
`Parameter`: before the annotation fix this raised `NameError` at `wire()` time, and now
they resolve against the tool module's own globals.

<!-- example: redsox -->
```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

import cisternal
from cisternal import CliContext, CliContract
from redsox.core.guard import enforce_no_sibling_parity_leak   # == main.py:25
from redsox.core.seams import SeamExplosionError, derive_seams
# consumer-provided (stubbed by the test prelude): load_config
from redsox.config import load_config

app = App(name="redsox")
console = Console()                                   # stdout, as main.py:34

ConfigOption = Annotated[                             # == main.py:42-44
    Path, Parameter(name=["--config", "-c"], help="Path to config.yaml or config.toml")
]

def _seam_report(exc: SeamExplosionError, ctx: CliContext) -> int:
    report = getattr(exc, "report", None)            # optional: redsox may attach SeamExplosionReport
    console.print(f"[bold red]{report.format_text() if report else exc}[/bold red]")   # main.py:101-103
    return 2

REDSOX_CLI = CliContract(exit_codes={SeamExplosionError: _seam_report})
# Unmapped exceptions keep the one-line report and exit 1; redsox has no ConfigError.

def _seams_done(r: dict, ctx: CliContext) -> None:
    console.print(f"[green]Derived {r['count']} seams written to {r['out']}[/green]")

@cisternal.tool(registry="redsox", name="derive_seams", cli_name="derive-seams",
                cli_contract=CliContract(format_success=_seams_done))
def derive_seams_tool(
    config: ConfigOption,
    out: Annotated[Path, Parameter(name=["--out", "-o"], help="Output path for seams.json")] = Path(
        "seams.json"
    ),                                                # == main.py:88-91
) -> dict:
    cfg = load_config(config)                         # loaded once, as main.py:95
    enforce_no_sibling_parity_leak(cfg.sibling_parity_governed, cfg.target_package)   # == main.py:96
    seams = derive_seams(cfg)
    out.write_text(json.dumps(seams, indent=2))
    return {"count": len(seams), "out": str(out)}

cisternal.wire(None, app, registry="redsox", cli_contract=REDSOX_CLI)     # CLI-only: no MCP server
# `redsox derive-seams -c c.toml -o s.json` on explosion: red report on stdout (as today), exit 2;
# telemetry cli.cmd_end exc_type="SeamExplosionError".
```

`redsox.config` stands in for wherever redsox keeps `load_config`. redsox imports cisternal
through a compat shim today; this example assumes a direct `import cisternal`, or a shim
that exports `wire` and forwards `cli_name` and `cli_contract`.

Telemetry: a hand-written `cisternal.span("redsox.cli.derive_seams")` inside the body is
replaced by the `cli.cmd_*` span `wire()` opens with `cmd="derive_seams"`, unless the body
keeps its inner span.

#### Worked example: maraxiom-style rich command, with a prompt and `--working-dir`

This one uses a `prepare` hook, a rich table formatter, two CLI-only options and
`exit_code_attr(report=...)`. The tool body does not prompt: the MCP path never runs
`prepare`.

<!-- example: maraxiom -->
```python
from __future__ import annotations

import json
import os
from pathlib import Path

from cyclopts import App
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

import cisternal
from cisternal import CliContext, CliContract, CliOption, exit_code_attr, json_option
from myxcel import MyxcelError                            # real class with per-subclass exit_code
from maraxiom.mcp_server import mcp                       # consumer-provided (stubbed by the test prelude)

app = App(name="mrx")
_err = Console(stderr=True)
_PATH_ARGS = ("out",)                                     # Path-typed tool parameters

def _myxcel_report(e: BaseException) -> None:             # myxcel's own error line
    _err.print(f"[red]Error:[/red] {e}")

def _prepare(ctx: CliContext) -> None:
    if ctx.arguments["title"] is None:                    # always present after apply_defaults
        ctx.arguments["title"] = Prompt.ask("Title")
    if wd := ctx.options.get("working_dir"):
        for k in _PATH_ARGS:                              # resolve relative paths BEFORE chdir
            p = ctx.arguments.get(k)
            if isinstance(p, Path) and not p.is_absolute():
                ctx.arguments[k] = Path.cwd() / p
        os.chdir(wd)

def _table(result: dict, ctx: CliContext) -> None:
    if ctx.options["json_out"]:
        print(json.dumps(result, indent=2)); return None
    t = Table("slide", "status")
    for s in result["slides"]:
        t.add_row(s["id"], s["status"])
    Console().print(t)                                    # print, return None

@cisternal.tool(registry="maraxiom", name="new_presentation", cli_name="new",
    cli_contract=CliContract(prepare=_prepare, format_success=_table,
                    options=[json_option(),
                             CliOption("working_dir", Path | None, None,
                                       help="Run as if started in this directory "
                                            "(relative path arguments resolve against the original cwd).")]))
def new_presentation(title: str | None = None, audience: str = "lab",
                     out: Path = Path("deck")) -> dict:
    return {"title": title, "audience": audience, "out": str(out),
            "slides": [{"id": "s1", "status": "draft"}]}

cisternal.wire(mcp, app, registry="maraxiom",
               cli_contract=CliContract(exit_codes={MyxcelError: exit_code_attr(report=_myxcel_report)}))
# A ConfigError raised in a tool -> "[red]Error:[/red] <msg>" on stderr, exit 2 (MRO -> MyxcelError handler).
# Omit report= to get the one-line report instead.
# The T contract's options list is normalised to a tuple and merges over W without error.
```

The `exit_code_attr` mapping applies only when a tool body *raises* a `MyxcelError`.
myxcel's own tool bodies do not work that way out of the box: they catch every exception and
return `_tool_error(e)`, so they exit 0. A body like that must raise, or put an exit code in
its envelope for the envelope formatter below (section 5).

#### Worked example: contemplex, a raised `ContemplexError` becomes a Panel and a looked-up code

contemplex raises `ContemplexError` with a `StrEnum` code. `exit_code_attr` covers int
attributes only, so the mapping is a handler with a lookup table: the real `_EXIT_CODES`
table from contemplex's CLI. The handler renders the same Panel contemplex's `_render_error`
does and returns the code instead of raising `typer.Exit`. A fallback handler on `Exception`
mirrors `_handle_exc`'s non-contemplex branch: an `INTERNAL` panel and exit 1.

The recipe requires `@cisternal.tool` to decorate the raw, raising tool body, not
contemplex's error-shaping `traced_tool` wrapper (which returns `err_envelope(...)` instead
of raising). `wire()` then exposes that raw body on MCP too, so the MCP error shape changes
from `err_envelope` dicts to FastMCP errors. That change is the consumer's decision.

<!-- example: contemplex -->
```python
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from cisternal import CliContext, CliContract
from contemplex.errors import ContemplexError, ErrorCode

console = Console()                                       # stdout, as cli.py:41

_EXIT_CODES = {                                           # == contemplex/cli.py:43-52
    "INVALID_INPUT": 2,
    "INVALID_TASK_TYPE": 2,
    "SESSION_NOT_FOUND": 3,
    "PHASE_MISMATCH": 4,
    "GATE_BLOCKED": 4,
    "CORRUPT_SESSION": 5,
    "WRITE_FAILED": 6,
    "INTERNAL": 1,
}

def _panel(code: str, msg: str) -> None:                  # == cli.py:73-84 rendering
    console.print(Panel(f"[bold red]{code}[/bold red]\n{msg}",
                        title="contemplex error", border_style="red"))

def _contemplex_exit(exc: ContemplexError, ctx: CliContext) -> int:
    _panel(exc.code.value, str(exc))
    return _EXIT_CODES.get(exc.code.value, 1)             # e.g. STAGING_FAILED -> 1, as today

def _internal_exit(exc: Exception, ctx: CliContext) -> int:   # == cli.py:89-90 fallback
    _panel(ErrorCode.INTERNAL.value, f"{type(exc).__name__}: {exc}")
    return _EXIT_CODES[ErrorCode.INTERNAL.value]          # 1

CONTEMPLEX_CLI = CliContract(exit_codes={ContemplexError: _contemplex_exit,
                                         Exception: _internal_exit})
# MRO resolution: a SessionNotFound hits ContemplexError -> panel, exit 3; any other Exception -> INTERNAL, exit 1.
# cisternal.wire(mcp, app, registry="contemplex", cli_contract=CONTEMPLEX_CLI)
```

`STAGING_FAILED` is a real `ErrorCode` that is absent from `_EXIT_CODES`, so it exits 1,
exactly as contemplex does today.

### The `--json` formatter, and option help

`format_success(result, ctx)` renders the result. The standard shape is "print, return
`None`": under cyclopts' default `result_action`, `None` exits 0 and prints nothing more.
Return a renderable only if you accept that it is printed after the telemetry span closes.

`json_option()` is the standard JSON flag: `CliOption("json_out", Annotated[bool,
Parameter(name="--json", negative="")], False, help=...)`. `negative=""` removes the implicit
`--no-json`. Pass a different flag as `json_option("--json-out")`, or a different identifier
with `name=`. The value reaches the formatter and handlers through `ctx.options["json_out"]`
and never reaches the tool function or the MCP signature.

Every `CliOption(name, annotation, default, help=...)` becomes a keyword-only parameter of
the CLI callable. `help=` is wrapped for you as `Annotated[annotation, Parameter(help=...)]`;
do not also set `Parameter(help=...)` inside `annotation`. `annotation` must be a real
type object, not a string or `ForwardRef`.

Flags are checked at wiring time: an option whose name equals any tool parameter name, or
whose long flag (`--json`, or the derived `--no-...` negative) overlaps a tool parameter's,
raises `CisternalWireError` naming the tool. cyclopts itself does not detect a duplicated
flag; the first-declared parameter silently wins. The check uses cyclopts' default name
transform and sees an App's `default_parameter` only through `wire()`, not through
`cli_command()`.

#### Worked example: alphex, all five commands, table or `--json-out`

alphex shows the **two entry points** recipe (below) and per-command options. Every contract
lives in `alphex/cli.py`. `alphex/mcp.py` keeps only plain `@cisternal.tool(...)` decorators
(with `cli_name=` where the CLI name differs) and its existing `wire(server, registry=...)`
call. `cli.py` imports `alphex.mcp` to register the tools, and `mcp.py` never imports
`cli.py`, so there is no import cycle. First the MCP module:

<!-- example: alphex-mcp -->
```python
# alphex/mcp.py: only cli_name additions; no contracts, no import of alphex.cli
# (docstrings and the FastMCP setup omitted)
from typing import Any
import cisternal
from alphex import _surface                            # consumer-provided (stubbed by the test prelude)

@cisternal.tool(registry="alphex", name="list_alphabets", cli_name="list")
async def alphex_list_alphabets() -> list[dict[str, Any]]:
    return _surface.catalog()                           # mcp.py:43

@cisternal.tool(registry="alphex", name="show_alphabet", cli_name="show")
async def alphex_show_alphabet(name: str) -> dict[str, Any]:
    return _surface.describe(name)                      # mcp.py:54

# relation, perm and lint keep name == CLI name and are unchanged (mcp.py:57-104).
@cisternal.tool(registry="alphex", name="relation")
async def alphex_relation(src: str, dst: str) -> dict[str, Any]:
    return _surface.classify(src, dst)

@cisternal.tool(registry="alphex", name="perm")
async def alphex_perm(src: str, dst: str, policy: str = "raise") -> dict[str, Any]:
    if policy not in _surface.POLICIES:
        msg = f"policy must be one of {', '.join(_surface.POLICIES)}, got {policy!r}"
        raise ValueError(msg)                           # mcp.py:90-92
    return _surface.table(src, dst, policy)

@cisternal.tool(registry="alphex", name="lint")
async def alphex_lint() -> list[dict[str, Any]]:
    return _surface.lint()                              # mcp.py:104
```

Then the CLI module:

<!-- example: alphex-cli -->
```python
# alphex/cli.py
import json
import sys
from typing import Any

from cyclopts import App

import cisternal
from cisternal import CliContext, CliContract, CliOption, json_option
import alphex.mcp                                       # registers the "alphex" tools; no wire(mcp) at import
from alphex._render import _render                     # consumer-provided (stubbed by the test prelude)

cli_app = App(name="alphex")

def _emit_fmt(result: Any, ctx: CliContext) -> None:    # == cli.py:32-36 _emit
    print(json.dumps(result, indent=2) if ctx.options["json_out"] else _render(result))

def _list_fmt(rows: list[dict], ctx: CliContext) -> None:   # reproduces cli.py:61-68 exactly
    if ctx.options["json_out"]:
        print(json.dumps(rows, indent=2)); return
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        specials = ", ".join(f"{k}@{v}" for k, v in r["specials"].items()) or "-"
        flag = "  (lints)" if r["warnings"] else ""
        print(f"{r['name']:<{width}}  size={r['size']:<3} offset={r['offset']}  {specials}{flag}")

def _lint_fmt(findings: list, ctx: CliContext) -> None:     # reproduces cli.py:107-116
    if not findings:
        print(json.dumps([], indent=2) if ctx.options["json_out"] else "no warnings"); return
    _emit_fmt(findings, ctx)
    if ctx.options["strict"]:
        sys.exit(1)                                     # works under any result_action

CONTRACTS = {
    "list_alphabets": CliContract(format_success=_list_fmt),
    "lint": CliContract(format_success=_lint_fmt,
                        options=[CliOption("strict", bool, False, help="Exit 1 on any finding.")]),
    # Optional: keep today's CLI --help text instead of mcp.py's docstring:
    "perm": CliContract(help="Build the permutation table from `src` to `dst`. "
                             "`policy` is one of raise, unknown, gap, mask -- applied uniformly."),
}

cisternal.wire(None, cli_app, registry="alphex",
               cli_contract=CliContract(options=[json_option("--json-out")], format_success=_emit_fmt),
               cli_contracts=CONTRACTS)
# Each tool's options merge as (*W.options, *T.options): lint gets --json-out and --strict.
# The CLI names list/show/relation/perm/lint and the flag --json-out match today's cli.py:57-116.
# The MCP tool names and signatures are unchanged (e.g. list_alphabets() -> list[dict]).
```

`alphex._render` stands in for wherever alphex keeps `_render`. Precondition on the
consumer side: after this migration `alphex.cli` imports `alphex.mcp`, so the CLI needs the
`mcp` extra (cisternal and fastmcp, Python 3.13 or later). alphex's stated CLI policy
(Python 3.11, no cisternal) excludes that unless alphex drops the policy.

Differences from alphex's hand-written CLI, all accepted:

- `json_option` sets `negative=""`, so the implicit `--no-json-out` goes away. The flag
  defaults to false.
- `perm` with an invalid policy: today the CLI raises `SystemExit(msg)`, which prints `msg`
  and exits 1. After migration the tool raises `ValueError(msg)`, which prints
  `Error (ValueError): msg` and also exits 1.
- `perm` gains a positional `policy`: today's CLI declares `*, policy`, while the tool's
  `policy` is positional-or-keyword, so `alphex perm a b mask` now parses. `--policy` still
  works. Declaring `*, policy` on the tool restores the old shape (MCP callers pass
  arguments by name, so it is safe there) at the cost of changing the Python signature.
- `--help` text comes from the `mcp.py` docstrings for every command without a
  `CliContract.help`. The `perm` entry shows the per-command override.
- `list`, `show`, `relation`, `lint` (with `--strict`) and all `--json-out` output are
  byte-identical, given tool bodies that return the same `_surface` values.

### Two entry points

The recommended layout when a package has both an MCP server and a CLI:

- The tools and their `@cisternal.tool(...)` decorators live in one module, and **nothing
  there imports the CLI module**.
- The CLI module imports that module, keeps every contract in a `cli_contracts` map keyed
  by tool name, and calls `wire(None, cli_app, registry=..., cli_contract=...,
  cli_contracts=...)`.
- The MCP entry point calls `wire(mcp, registry=...)` inside its own `main()`.

This avoids a tool-module and CLI-module import cycle, and keeps every contract on the CLI
side where it belongs. The alphex example above is this layout. `wire()` snapshots the
registry at call time, so calling it once per entry point is fine.

### `help` and `show`

`CliContract(help="...")` overrides a command's `--help` text and `CliContract(show=False)`
hides it from `--help` (typer's `hidden=True`). Each is forwarded to `app.command` only when
set; otherwise the command's help is its function docstring, exactly as before. There are
**no aliases**: to give one tool two CLI names, register the same `cli_command(...)`
callable a second time by hand.

### Prepare and prompt

`prepare(ctx)` runs on the CLI path only, before dispatch, and may mutate `ctx.arguments`.
Use it for interactive prompts, `chdir`, worktree detection and context-derived arguments:

```python
def _prepare(ctx: CliContext) -> None:
    if ctx.arguments["title"] is None:
        ctx.arguments["title"] = Prompt.ask("Title")
```

Because MCP never runs `prepare`, a parameter that `prepare` fills from a prompt should
default to `None` in the tool, and MCP callers then see it as optional. That schema change
is the consumer's to accept. (The hidden-argument recipe below avoids it.)

### The generic result-envelope formatter

For a tool that *returns* a flat envelope instead of raising, `{"ok": True, **payload}` on
success and `{"ok": False, "error_code": ..., "error": ..., **context}` on failure, the
formatter maps the failure to an exit code with `sys.exit(code)`. That works under any
App-level `result_action`, because a callable `result_action` swallows a returned `int`
but never sees an exit raised from inside the command. The code table belongs to the
consumer.

<!-- example: envelope -->
```python
import json
import sys
from typing import Any

from cisternal import CliContext

_CODE_TO_EXIT: dict[str, int] = {"NOT_FOUND": 3, "INVALID_INPUT": 2}   # consumer-defined

def _envelope(result: dict[str, Any], ctx: CliContext) -> None:
    if result.get("ok") is False:
        print(f"Error ({result['error_code']}): {result['error']}", file=sys.stderr)
        sys.exit(_CODE_TO_EXIT.get(result["error_code"], 1))   # works under any result_action
    print(json.dumps({k: v for k, v in result.items() if k != "ok"}, indent=2))
```

A formatter's `sys.exit(n)` is recorded in telemetry as `ok=False` with `exit_code=n`.

### Groups: `cli_group_help` and `cli_group()`

A tool's `cli_group` puts its command in a sub-App. It may be a one-segment name, a
whitespace-separated path, or a tuple, so `cli_group="flow visuals"` and
`cli_group=("flow", "visuals")` both give `flow visuals <command>`. Group help comes from
`wire(cli_group_help={...})`, keyed by path, one entry per level:

```python
cisternal.wire(server, app, registry="demo",
               cli_group_help={"flow": "Flow operations", "flow visuals": "Visual operations"})
```

- Every `cli_group_help` key must be a prefix of some tool's group path, or `wire()` raises
  `CisternalWireError`.
- Help is applied to levels cisternal creates, and to cisternal-created levels that have no
  help yet. A second, different help for a cisternal-created level raises
  `CisternalWireError`; the same help again is a no-op.
- A user-constructed `App` already mounted at that name is **adopted**: `wire()` adds tools
  into it and leaves its help and commands untouched. A function command at that name is
  rejected with `CisternalWireError`, as is a user `App` that declares its own `@default`
  (call `cisternal.cli_group()` before adding the `@default`, so the group comes from the
  cache).
- `cisternal.cli_group(app, "flow visuals", help=None)` returns the same sub-App object
  `wire()` uses, whichever is called first, so hand-registered commands land in the same
  group: `cisternal.cli_group(app, "flow visuals").command(name="x")(...)`.

A name planned both as a command and as a group at one level, the same leaf planned twice,
and a flat or leaf name already on the App all raise `CisternalWireError` before anything
is registered (section 5).

### Hidden or context-derived argument

A parameter that the CLI must not accept as a flag, but that the tool needs (a token from
the environment, a detected worktree, a value derived from the cwd), is declared as a
**required keyword-only parameter with no default**, marked `parse=False`, and filled by
`prepare` through `ctx.arguments`:

```python
import os
from typing import Annotated

from cyclopts import Parameter

import cisternal
from cisternal import CliContext, CliContract


def _fill_token(ctx: CliContext) -> None:
    ctx.arguments["token"] = os.environ["MYTOOL_TOKEN"]


@cisternal.tool(registry="mytool", cli_contract=CliContract(prepare=_fill_token))
def publish(name: str, *, token: Annotated[str, Parameter(parse=False)]) -> dict:
    ...
```

- cyclopts does not accept `--token` (it reports `UnknownOptionError`), and leaves the
  parameter unbound.
- The MCP parameter stays **required**, and MCP callers pass it explicitly. The schema lists
  it in both forms.
- Until `prepare` sets it, the key is absent from `ctx.arguments`. If `prepare` leaves it
  unset, the call fails with a `TypeError` before the tool runs and before the telemetry
  span, so the tool is never called without it.
- `token: Annotated[str | None, Parameter(parse=False)] = None` also works, but MCP then
  sees the parameter as optional.

This recipe is prose: it is covered by `tests/test_registration_cli_contract.py`, not by
the guide's executed examples.

### Mid-command confirm

Do not prompt from a tool body. Split the work into a **preflight tool** that returns what
would happen, and a tool gated on `yes: bool = False` that refuses to act unless `yes`.
MCP clients call the two tools themselves. The CLI chains them with a composite
(section 4) that prompts between them:

```python
from rich.prompt import Confirm

import cisternal
from cisternal import CliContract

@cisternal.tool(registry="mytool")
def plan_delete(name: str) -> dict:
    return {"would_delete": [f"{name}/a", f"{name}/b"]}

@cisternal.tool(registry="mytool")
def delete(name: str, yes: bool = False) -> dict:
    if not yes:
        raise ValueError("refusing to delete without yes=True")
    return {"deleted": [f"{name}/a", f"{name}/b"]}

def delete_interactive(name: str) -> dict:
    plan = plan_delete(name)                      # the tool functions are unchanged by @tool
    if not Confirm.ask(f"Delete {len(plan['would_delete'])} items?"):
        return {"deleted": [], "aborted": True}
    return delete(name, yes=True)

cisternal.wire(mcp, registry="mytool")            # MCP only: app=None, so no CLI command is mounted
app.command(name="delete")(cisternal.cli_command(delete_interactive, contract=CliContract()))
```

The tools are wired with `app=None` because registering the same CLI name from both
`wire()` and a hand-written `cli_command(...)` would collide (section 4). This recipe is
prose and is not executed.

### Banner

A banner or progress line at command start belongs in `prepare`, the formatter, or
`logging` to stderr. Never `print` it to stdout in a tool body: that corrupts `--json`
output and the MCP stdio channel.

## 4. Composite commands

A composite chains several tools and writes intermediate files (redsox `audit`). A
declarative step DSL is a non-goal: real composites interleave control flow, such as
re-exec'ing under a target interpreter or twelve conditional stages, and that is ordinary
Python. The recommended pattern for a **CLI-only** composite is a plain function registered
with `cisternal.cli_command`, so it shares the one-line error report, the contract and
telemetry. It calls the **tool functions**, which `@tool` leaves unchanged, never their CLI
callables (those `sys.exit`).

This sketch is illustrative and not executed (`admit_tool` and the elided steps are redsox's):

```python
def audit(config: Path, out_dir: Path = Path("redsox_audit")) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    derive_seams_tool(config=config, out=out_dir / "seams.json")   # raises SeamExplosionError -> exit 2
    admit_tool(config=config, out=out_dir / "admissibility")
    ...
    return {"out_dir": str(out_dir)}

def _audit_done(r, ctx):
    Console().print(f"[bold green]Audit complete: {r['out_dir']}")

app.command(name="audit")(cisternal.cli_command(
    audit, name="audit",
    contract=CliContract(format_success=_audit_done).merged_over(REDSOX_CLI)))
# Equivalent: dataclasses.replace(REDSOX_CLI, format_success=_audit_done)
```

**Async sub-tools.** A composite over `async def` tools must itself be `async def` and
`await` each tool: never `asyncio.run` per tool. The CLI path already runs the
composite under one `asyncio.run`, and a nested `asyncio.run` raises inside a running loop.
A sub-tool exception propagates out of the awaited call into the error path and maps through
`exit_codes` exactly like a sync one.

<!-- example: async-composite -->
```python
from cyclopts import App

import cisternal
from cisternal import CliContract
from alphex.mcp import alphex_lint, alphex_list_alphabets   # the tools from the alphex example

app = App(name="alphex")

async def audit_all() -> dict:
    alphabets = await alphex_list_alphabets()
    findings = await alphex_lint()
    return {"alphabets": len(alphabets), "findings": findings}

app.command(name="audit-all")(cisternal.cli_command(audit_all, contract=CliContract()))
```

**Placement and registration.**

- **CLI and MCP.** A composite that should be both an MCP tool and a CLI command is declared
  only with `@cisternal.tool(cli_contract=...)` (or a `cli_contracts` entry), and `wire()`
  mounts it.
- **CLI only.** Hand registration through `cli_command()` is for CLI-only composites. Never
  combine the two on the same name, that is, a `@cisternal.tool` that `wire()` mounts *and*
  a hand `cli_command()` registration, unless that tool is wired with `app=None`.
- A bare `app.command(...)(cli_command(...))` registration is **not** recorded in
  `WiredRegistry.cli_commands`, because no `wire()` call saw it, and it gets no
  `CliContract.help`/`show` forwarding. Pass `help=`/`show=` to `app.command` directly.
- To put a CLI-only composite into a group that `wire()` populates, at any depth, register it
  on `cisternal.cli_group(app, "<group path>")`. That returns the same sub-App object.
- Use plain cyclopts with no cisternal involvement only for commands that are pure CLI
  plumbing (`--version`, shell completion, interactive TUIs).

## 5. Gotchas

- **`int` and `bool` returns.** An `int` or `bool` return becomes the exit code under
  cyclopts' default `result_action` only. A callable `result_action` (bathos and
  naurmalade set one App-wide) swallows it, so use `sys.exit(code)`. A formatter that
  returns `None` composes with such an App: the action sees `None`.
- **Formatters print and return `None`.** A renderable a formatter *returns* is printed by
  `result_action` after the telemetry span closes, so that printing is not timed.
- **Recovery turns failures into successes.** With `recovery=...`, a final failure that has
  `to_result()` becomes a *return value*, so it reaches `format_success`, not `exit_codes`.
  A formatter must therefore tolerate error-shaped results.
- **Telemetry `cmd` is the MCP name** (`entry.name`), not the CLI name.
- **`prepare` is never timed**, and a crash or exit in `prepare` emits no `cli.cmd_*` event.
  A `prepare` that sets an unknown argument, removes a required one, or removes a positional
  argument ahead of a later positional-only or `*args` value fails with `TypeError` before
  the span.
- **`prepare` sees every argument in `ctx.arguments`, defaults included.** When it
  `chdir`s, it must resolve relative `Path` arguments against the original cwd *before*
  calling `os.chdir`, as the maraxiom example does.
- **Exit handlers can see `ctx.arguments == {}`** when binding failed.
- **`_cisternal_timed` tools.** For a tool already decorated with `timed_command`, `wire()`
  adds no span, and the formatter runs untimed too.
- **A body that catches its exceptions and returns an error envelope exits 0** under the
  default `result_action`: nothing raises, so `exit_codes` never runs. The same holds for
  a tool wrapped by an error-shaping `traced_tool`, which catches and returns an envelope
  around an otherwise raising body. Current cases:
  - myxcel's tools end in `except Exception as e: return _tool_error(e)`, and `_tool_error`
    returns `{"error", "message"}` with no exit code;
  - maraxiom's flow tools discard the int code their helpers return;
  - the `traced_tool` wrappers of contemplex, bathos and myxcel, and cisternal's own
    `traced_tool`, return a shaped error instead of raising. After the cisternal
    `traced_tool` cutover, `ContemplexAdapter.shape_error` always yields `INTERNAL`, so an
    envelope formatter cannot recover contemplex's exit codes 2 to 6.

  Such a body must either raise (for a wrapped tool: decorate the raw body with
  `@cisternal.tool`, as in the contemplex example), which changes the MCP error shape (the
  consumer's decision), or carry an exit code in the envelope for the envelope formatter to
  read and `sys.exit` with.
- **A failed `wire()` leaves the server and the App untouched.** A `CisternalWireError`
  raised for a contract, name or group problem is raised in a pre-pass, before the first
  `add_tool` or `app.command` call, so it can be fixed and retried. A name planned twice at
  one level, or a name already on the App, raises it too, where cyclopts would otherwise
  raise `CommandCollisionError` partway through registration.
- **`from __future__ import annotations` is fine in tool modules.** Parameter annotations
  resolve against the tool module's globals, also through `functools.wraps` decorators
  (verified on CPython 3.13), and a return type imported only under `TYPE_CHECKING` is fine.
  **The bathos workaround is deletable:** mutating `__annotations__` after the `def`
  (`bathos/mcp.py`, `list_runs_tool` and `run_cli_tool`) still works, but is no longer
  needed.
- **cyclopts does not detect two parameters that claim the same flag.** The contract builder
  checks option-versus-tool collisions only, and `cli_command()` cannot see an App's
  `default_parameter`.
- **Global options are not part of the contract.** `CliContract.options` are per-command
  only and `CliContext` carries no global values. Use `app.meta` (section 7).
- **cyclopts is pinned `>=4.18.0,<5`.** The builder uses a few cyclopts internals
  (`default_name_transform`, `Parameter.get_negatives`, `Parameter.combine`).

## 6. When to drop to plain cyclopts

`wire()` is for commands that are the same operation as an MCP tool. Stay on plain
cyclopts (or typer) when:

- the command has no MCP counterpart and no use for cisternal telemetry (`--version`, shell
  completion, an interactive TUI);
- the command is mostly terminal interaction (several prompts, a full-screen UI), where
  `prepare` and one formatter would be a worse fit than the code you have;
- the project must run without cisternal and fastmcp (alphex's Python 3.11 CLI policy);
- you want a pipeline DSL (section 4: not provided).

You can mix freely: a plain `app.command` next to wired commands is fine, and
`cisternal.cli_group()` and `cisternal.cli_command()` exist so the hand-written parts share
the groups, the contract and the telemetry of the wired ones.

## 7. A migration checklist for typer CLIs

For each typer command being moved to `@cisternal.tool` + `wire()`:

1. Move the body into a plain function that returns data and raises domain exceptions.
2. Turn typer parameters into annotated parameters (table below).
3. Map the `typer.Exit(code)` and `except ...: raise typer.Exit(n)` sites to `exit_codes`.
4. Move rendering into `format_success`; move `--json` into `json_option()`.
5. Move prompts, `chdir` and context-derived values into `prepare`.
6. Run `wire(...)` and diff `--help` and stderr/exit codes against the old CLI.

| typer | cyclopts / cisternal |
|---|---|
| `typer.Argument(...)` | Positional parameter. Use `Annotated[T, Parameter(...)]` for help and metavar |
| `typer.Option(...)` | Keyword parameter (keyword-only for flag-only). Use `Annotated[T, Parameter(help=...)]` |
| Aliases and renames (`typer.Option("--from", "-f")`) | `Annotated[T, Parameter(name=["--from", "-f"])]` on the tool parameter. The Python identifier, and therefore the MCP property name, is unchanged |
| `help=` on Argument/Option | `Parameter(help=...)`, or the docstring's parameter section. For a CLI-only option, `CliOption(help=...)` |
| `help=` / `hidden=True` on `@app.command` | `CliContract(help=...)` / `CliContract(show=False)` |
| `@app.callback()` global options | `app.meta` (cyclopts meta-app), recipe below. Not a `CliContract` feature: `CliContract.options` are per-command only |
| `--version` callback | `App(version=...)` |
| `invoke_without_command=True` | `@app.default` |
| Nested `typer.Typer()` sub-apps (`app.add_typer(visuals, name="visuals")` under `flow`) | `cli_group="flow visuals"` on the tool, or `cisternal.cli_group(app, "flow visuals")` |
| `typer.prompt` when an option is missing | A `prepare` hook writing `ctx.arguments[...]`. The parameter defaults to `None` |
| Hidden or context-derived option (`hidden=True`, `ctx.obj`-derived value) | `*, name: Annotated[T, Parameter(parse=False)]` (required keyword-only, recommended) or `... = default`, filled by `prepare` through `ctx.arguments` |
| `typer.confirm` mid-command | A preflight tool plus a `yes`-gated tool, chained by a `cli_command` composite that prompts between them |
| `typer.echo` banner at command start | Emitted from `prepare`/the formatter, or `logging` to stderr; never `print` to stdout in a tool body |
| `typer.Exit(code)` / `raise SystemExit` | Unchanged passthrough. Prefer a domain exception plus an `exit_codes` entry |

### Global options via `app.meta`

This replaces `@app.callback()`. The meta-app parses the global flags, sets state the
consumer owns, and forwards the remaining tokens to the real App:

<!-- example: app-meta -->
```python
import logging
from typing import Annotated

from cyclopts import App, Parameter

app = App(name="mytool")
# ... cisternal.wire(mcp, app, registry=...) ...

VERBOSE = False                       # consumer-owned state that prepare hooks and formatters read

def _setup_logging(verbose: bool) -> None:
    global VERBOSE
    VERBOSE = verbose
    logging.getLogger("mytool").setLevel(logging.DEBUG if verbose else logging.INFO)

@app.meta.default
def main(*tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
         verbose: bool = False):
    _setup_logging(verbose)
    return app(tokens)        # nested call returns the command's value

if __name__ == "__main__":
    app.meta()                # launch through the meta-app, not app()
```

The inner `app(tokens)` returns the command's value, and the outer `app.meta()` applies
`result_action` once, so an `int` result of the inner command is still the exit code under
the default action, and a callable `result_action` sees the inner result. This is verified
for the returned-value form only. Prefer calling tool *functions* directly in composites
rather than re-entering `app()`.

A global value reaches `prepare` or a formatter only through state the consumer owns, such
as the module variable above or a contextvar set in `main`. It is never put into
`CliContext`.
