---
title: "wire() rich CLI contract"
description: "Declarative CLI contract with exception mapping, rich formatters, and group interop for cisternal #30"
task_id: 261001_wire-cli-contract
status: accepted
---

# Spec: `wire()` rich CLI contract (cisternal #30)

task_id: `261001_wire-cli-contract` · status: draft rev 8 (adversarial coherence round 7 and fitness round 7 applied) · base: `release/0.1.1a14` @ `8730da8`

---

## 1. Problem

`cisternal.wire(server, app, registry=...)` puts every `@cisternal.tool()` function on a FastMCP server and on a `cyclopts.App`. The CLI side is a fixed closure built by `_make_cli_cmd`. Today that closure is defined inside `wire()`'s per-entry loop, under `if app is not None` (`src/cisternal/registration/wired.py:273-319`):

- **Success.** The raw result goes back to cyclopts (`wired.py:302`), and the App's `result_action` decides what happens next.
  - Cyclopts' default is `"print_non_int_sys_exit"` (`cyclopts/_result_action.py:96-105`). It rich-prints a non-int result and exits 0. An `int` result becomes the exit code, and a `bool` maps to exit 0/1.
  - A *callable* `result_action` swallows a returned `int` (`_result_action.py:92-93`), so the int is never used as an exit code.
- **Failure.** Any `Exception` prints `Error (<Type>): <msg>` to stderr and calls `sys.exit(1)` (`wired.py:306-313`). `SystemExit` is re-raised unchanged (`wired.py:303-305`).
- **Registration.** Only `name=` is passed to `app.command` (`wired.py:323,326`). No help or visibility override is possible.
- **Identity.** The closure takes `__name__` and `__doc__` from the original function (`wired.py:315-316`), plus `__signature__` and `__annotations__` (`:317-318`). It does not set `__qualname__`, `__module__` or `__wrapped__`.

Consumers have five needs that this closure cannot meet.

1. **Mapping failures to exit codes, with a custom report.** Each consumer maps raised exceptions to exit codes.
   - redsox exits 2 on `SeamExplosionError` (`redsox/src/redsox/cli/main.py:101-103`).
   - myxcel carries `exit_code` as an integer class attribute (`myxcel/src/myxcel/_error.py:1-31`: `MyxcelError.exit_code = 1`, `ConfigError = 2` … `MyxcelSubprocessError = 6`).
   - contemplex carries a *string-valued* code. `ContemplexError.code` is an `ErrorCode` `StrEnum` (`contemplex/src/contemplex/errors.py:6-22`). The CLI maps the code through a lookup table, `_EXIT_CODES` (`contemplex/src/contemplex/cli.py:43-52`): `INVALID_INPUT`/`INVALID_TASK_TYPE` → 2, `SESSION_NOT_FOUND` → 3, `PHASE_MISMATCH`/`GATE_BLOCKED` → 4, `CORRUPT_SESSION` → 5, `WRITE_FAILED` → 6, `INTERNAL` → 1.
     - The route goes through a raised exception. Each command catches the exception and calls `_handle_exc` (`cli.py:86-90`).
     - For a `ContemplexError`, `_handle_exc` builds `err_envelope(exc.code, str(exc), **exc.context)` (`errors.py:79-80`). Any other exception becomes `err_envelope(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}")`.
     - `_render_error` (`cli.py:73-84`) prints a red rich `Panel` titled `contemplex error` and raises `typer.Exit(code=_EXIT_CODES.get(code, 1))`. A code missing from the table, such as `STAGING_FAILED`, exits 1.
   - Some consumers instead *return* error-shaped result envelopes from a tool that does not raise, so the failure lives in the result. G3 covers that shape, and §6.10 gives a generic recipe.
2. **Rich or structured output**: tables, colours, `--json` / `--json-out`.
   - alphex hand-renders its output and offers `--json-out` (`alphex/src/alphex/cli.py:32-116`).
   - bathos sets an App-wide `result_action` (`bathos/src/bathos/cli_render.py:59-65`, `bathos/src/bathos/cli_cyclopts.py:30`) that cannot tell commands apart.
   - naurmalade does the same with `App(result_action=render_envelope)` (`naurmalade/src/naurmalade/cyclopts_cli.py:89,122-126`) over `wire(None, app=app, ...)` (`:133-135`).
3. **CLI-only parameters** that the MCP tool signature must not gain: `--json`, `--working-dir`, and interactive fallbacks such as maraxiom's `typer.prompt` when `--from` is absent.
4. **Composite commands** that chain several tools and write intermediate files, such as redsox `audit` (`redsox/cli/main.py:386-436`).
5. **Pre-existing and nested command groups.**
   - A consumer that has already mounted `app.command(App(name="jobs", help=...))` cannot have `wire()` add tools into that group. `_get_or_create_subapp` (`wired.py:65-81`) creates a bare `App(name=group)` and mounts it unconditionally, which raises `CommandCollisionError` at `wire()` time (A20).
   - Groups that `wire()` creates have no way to get help text.
   - Groups cannot be nested (`flow visuals`).

Two consumers show the duplication pattern. alphex uses `wire()` only for MCP and hand-writes a parallel CLI. That split is deliberate: alphex supports Python >=3.11 (`alphex/pyproject.toml:14`) and keeps its CLI free of cisternal and fastmcp, whose `mcp` extra installs cisternal only on >=3.13 (`alphex/pyproject.toml:62-70`). So alphex is an example of the pattern, not a case that `wire()` removes on its own. redsox is CLI-only: it has no MCP server, makes no `wire()` call, and hand-writes its CLI. The downstream migrations (maraxiom, myxcel, contemplex and demistify; praxia debt #2387–#2390) would repeat that pattern. No consumer-onboarding doc explains when `@tool` + `wire()` should replace a hand-rolled CLI/MCP pair.

**A latent bug (§3, A9) blocks the migration on its own.**

- **Cause.** The CLI closure's `__annotations__` are copied raw from the original function (`wired.py:318`), but its `__globals__` belong to `wired.py`. cyclopts calls `typing.get_type_hints(func)` (`cyclopts/field_info.py:357`) over every key of `__annotations__`, including `return`, although it only reads the parameter names.
- **Effect.** A tool module that uses `from __future__ import annotations` breaks if it annotates with any name that `wired.py` does not import (`Annotated`, `Path`, `Parameter`, …). `wire(..., app)` then raises `NameError` at registration time. A return type imported only under `TYPE_CHECKING` breaks it the same way.
- **bathos already hit this.** It works around it by mutating `__annotations__` after the `def`, so the stored values are real objects and not strings (`bathos/src/bathos/mcp.py:313-325` for `list_runs_tool`, `:1929-1945` for `run_cli_tool`).
- **Other consumers.** The remaining tool annotations in bathos and alynxr use builtins and `Any`, which resolve only because `wired.py` happens to import `Any` (`wired.py:39`).

## 2. Goals / Non-goals

**Goals**

- **G1.** A declarative `CliContract` with defined precedence, attachable in three places:
  - per `wire()` call, as `wire(cli_contract=...)`;
  - per tool, through `@cisternal.tool(cli_contract=...)`;
  - per tool name from the wiring site, through `wire(cli_contracts={entry.name: ...})`. This lets every contract live in the CLI module without the MCP module importing it.
- **G2.** Exception-to-exit-code mapping.
  - A mapping value is either an `int` in 1..255 (default F1 message, custom code) or a handler `(exc, ctx) -> int | None` that renders its own report.
  - A handler returning `None` means "print the F1 line and exit 1".
  - Resolution is deterministic and follows the MRO.
  - The `default_report` and `exit_code_attr` helpers cover the common cases. `exit_code_attr` accepts a custom `report` function. It handles int-valued code attributes only. String or enum codes need a handler with a lookup table (§6.9).
- **G3.** A success formatter `(result, ctx) -> Any` for rich, plain or JSON output, selected per command. A formatter maps result-shaped failures (envelopes) to exit codes with `sys.exit(code)`, which works under any `result_action`.
- **G4.** CLI-only options (e.g. `--json`) are injected into the signature of the *CLI* callable only. Their values reach the formatter and handlers through `ctx.options`, and never reach the tool function or the MCP signature.
- **G5.** An optional `prepare(ctx)` hook that runs before dispatch. It covers interactive prompts, `chdir`, worktree detection and context-derived arguments by mutating `ctx.arguments`.
- **G6.** A public `cli_command(fn, ...)` helper built from the same code path. A hand-written composite command (redsox `audit`) then gets identical F1, contract and telemetry behaviour.
- **G7.** Fix A9 (annotation resolution) so that tool modules using `from __future__ import annotations` can be wired. This includes tools wrapped by `functools.wraps` decorators such as `timed_command`, and tools whose return type cannot be resolved.
- **G8.** A consumer-onboarding doc.
- **G9.** With no contract supplied, behaviour is byte-identical to today: the same stderr bytes, exit codes, return values, telemetry events, CLI signature and `app.command` arguments (`name=` only).
- **G10.** Group interop:
  - (a) `_get_or_create_subapp` adopts an existing user-constructed `App` that is already mounted as `app[group]`.
  - (b) `wire(cli_group_help=...)` supplies help text for the groups that cisternal creates, at every level.
  - (c) A public `cisternal.cli_group(app, path, help=None)` uses the same cache, so hand-registered commands land in the same group object.
  - (d) Group paths can be nested (`"flow visuals"` or `("flow", "visuals")`).
- **G11.** Per-command `--help` text and visibility overrides, through `CliContract.help` and `CliContract.show`. They are forwarded to `app.command` only when set.

**Non-goals**

- **N1.** Any change to the MCP surface (§10).
- **N2.** A pipeline/DAG DSL for composite commands. §7 explains why and gives the recommended plain-cyclopts pattern.
- **N3.** Bundling or mandating a rendering library. Formatters may use `rich` (already a transitive dependency via cyclopts, `cyclopts-4.18.0.dist-info/METADATA:22`), `print` or `json`. cisternal ships no table helpers.
- **N4.** Progress bars as a contract feature. Progress belongs in the tool body or the formatter; the contract only has to not obstruct it.
- **N5.** Changing App-level `result_action` semantics. Consumers such as bathos and naurmalade keep theirs, and the contract composes with them (§6.1).
- **N6.** Supporting cyclopts 5.x. The design targets cyclopts 4.18, which is installed and pinned `>=4.18.0` (`pyproject.toml:24`). T5 adds the `<5` upper bound (R3).
- **N7.** CLI-path recovery telemetry (the contextvar). It stays deferred per `compose.py:243-247`.
- **N8.** App-level (global) options. `CliContract.options` are per-command only, and `CliContext` carries no global values. Global options use cyclopts' `app.meta` (§8 item 7). A global value reaches `prepare` or a formatter only through state the consumer owns, such as a module variable or a contextvar.
- **N9.** Command aliases (several CLI names for one tool). `CliContract` carries only `help` and `show` for registration. To add an alias, register the same `cli_command(...)` callable a second time by hand.

## 3. Assumptions

| # | Assumption | Tag | Evidence / spike |
|---|---|---|---|
| A1 | The CLI closure is built per entry in `_make_cli_cmd`, which today is nested inside `wire()`'s entry loop under `if app is not None` and closes over `recovery` and `cli_telemetry`. F1 catches `Exception` only and re-raises `SystemExit`. The closure sets `__name__`/`__doc__` from the original function, then `__signature__` and `__annotations__`. It sets no `__qualname__`, `__module__` or `__wrapped__`. | VERIFIED | `wired.py:273-319` (def at `:273`; F1 at `:296-313`; identity at `:315-318`) |
| A2 | `timed_command` wraps `_dispatch` *inside* F1, so telemetry sees the original exception. It catches `BaseException` and records `exit_code` for `SystemExit`; a nonzero exit is recorded `ok=False`. Failures are logged at ERROR. `timed_command` applies `functools.wraps(fn)` to its wrapper, which therefore carries `fn`'s `__annotations__` and a `__wrapped__`. | VERIFIED; the `functools.wraps` claim is VERIFIED on CPython 3.13 only | `wired.py:285-294`; `adapters/cli.py:64` (`@functools.wraps(fn)`), `:65-96` (the recon quote omitted the `level=` argument at `cli.py:91-92`). Test 28 asserts the `ok=False`/`exit_code` pair end-to-end. The project requires `>=3.13` (`pyproject.toml:22`); the venv is 3.13.12. On 3.14 (PEP 649 lazy annotations), what `wraps` copies is unverified (see A9) |
| A3 | The telemetry `cmd` field is `entry.name`, not the CLI name. | VERIFIED | `wired.py:270,321` → `timed_command(cmd_name)` at `:294` |
| A4 | The CLI recovery leg applies AC3 `to_result()` only when `recovery is not None`. With `recovery=None`, exceptions reach F1 raw. | VERIFIED | `compose.py:265-279`; `_final_failure` at `:154-162` |
| A5 | Async tools on the CLI run via `asyncio.run` in `cli_dispatch`. Their exceptions propagate synchronously into F1. | VERIFIED | `shim.py:107-127`. Spike: async `aadd 4` → printed dict, exit 0 |
| A6 | On the default success path, a dict result is rich-printed and exits 0, an `int` result *becomes the exit code*, and `bool` maps to 0/1. | VERIFIED | `_result_action.py:96-105`. Spike: `retint 5` → `EXIT 5` |
| A7 | If an extra `KEYWORD_ONLY` parameter is injected into a CLI callable's `__signature__`/`__annotations__`, cyclopts parses it and passes it as a kwarg. The annotation must be a real object, e.g. `Annotated[bool, Parameter(name="--json")]`. | VERIFIED | Spike `/tmp/claude-1000/spk/run.py extra addx 1 --json` → `JSON_OUT= True RESULT= {'sum': 3}`, exit 0 |
| A8 | cyclopts reads a command's signature once, at `app.command()` time (`core.py:1427` → `default` `:1516` → `validate_command` → `signature_parameters`). Injection and annotation resolution must therefore happen before registration, when the CLI callable is built. `signature_parameters` calls `get_type_hints` over every key of `__annotations__` but reads only the parameter names, so a `return` key affects only whether resolution succeeds. | VERIFIED | `field_info.py:349-363`. The traceback in the A9 spike runs through exactly these frames |
| A9 | **Bug:** a tool module with `from __future__ import annotations` and a non-builtin annotation name makes `wire(..., app)` raise `NameError` at registration. The closure copies raw string annotations (`wired.py:318`), and cyclopts resolves them via `get_type_hints(_cli_cmd)` against `wired.py`'s globals (`field_info.py:357`). **Fix (§5.5):** `_resolve_cli_hints` resolves *per parameter* (only names in `inspect.signature(fn).parameters`) with `include_extras=True` and `globalns={**vars(wired_module), **getattr(inspect.unwrap(fn), "__globals__", {})}`. It reads the raw annotations from `fn.__annotations__`. When that is empty and `fn` has `__wrapped__`, it reads them from `inspect.unwrap(fn).__annotations__` instead. The result goes into `_cli_cmd.__annotations__` only, and `return` and any other non-parameter key are dropped. The globals must come from the *unwrapped* function: a `functools.wraps` wrapper such as `timed_command`'s (`adapters/cli.py:64`) has `adapters/cli.py`'s `__globals__`, and passing an explicit `globalns` turns off `get_type_hints`' own `__wrapped__` unwrapping. On `NameError`, `AttributeError`, `TypeError` or `SyntaxError` (a malformed string annotation such as `"list[int"`) for any parameter, the no-contract path falls back to the raw copy `dict(fn.__annotations__)`, and the contract path raises `CisternalWireError`. `__signature__ = inspect.signature(original_fn)` stays unchanged and keeps its return annotation. | VERIFIED (bug); fix VERIFIED on CPython 3.13 only | Bug spike `wrapfix.py`: `plain` → `FAIL NameError name 'Annotated' is not defined`. The signature must not change: `tests/test_registration_wire.py:18` uses `from __future__ import annotations`, and `:561-565` asserts `inspect.signature(registered_fn) == inspect.signature(original)` against the string-annotated original, so a resolved signature would break test 24. T0b acceptance (tests 9 no-contract, 9b, 9c, 9d no-contract half) re-asserts the fix on 3.13. The empty-`__annotations__` `__wrapped__` fallback targets 3.14, where a wrapper's `__annotations__` may be empty under PEP 649. T0b adds a 3.14 spike of test 9d; if no 3.14 interpreter is available, the PR records the 3.14 wrapped case as unverified. bathos' post-def `__annotations__` mutation (`bathos/mcp.py:313-325, 1929-1945`) stores real objects, which `get_type_hints` passes through unchanged, so that workaround keeps working (test 9c) |
| A10 | `ToolEntry` is a dataclass whose optional fields all have defaults, so a new trailing `cli_contract: CliContract \| None = None` is back-compatible. | VERIFIED | `registry.py:29-48`. UNVERIFIED: that no out-of-repo code builds `ToolEntry` positionally with more than 5 args. Spike: `grep -rn "ToolEntry(" ~/projects/*/src` before T2 |
| A11 | `wired.py` and the new module stay fastmcp-free at import time; `Tool` is imported locally. | VERIFIED | `wired.py:253`; lazy `__getattr__` in `registration/__init__.py:36-46` and `cisternal/__init__.py:158-178` |
| A12 | Today sub-apps are cached per `(id(app), group)`, and grouped commands are recorded as `"<group> <cli_name>"`. After this change, a group is a path of one or more segments. Each level is cached per `(id(parent), segment)`, and grouped commands are recorded as `"<seg1> … <segN> <cli_name>"`. That is identical to today for a single segment. | VERIFIED (today) | `wired.py:62-81, 322-328`. Tests 7 and 33 cover the new form |
| A13 | bathos relies on an App-level `result_action=cyclopts_result_action` that only handles `dict` and ignores everything else. naurmalade relies on an App-level `result_action=render_envelope`. | VERIFIED | `bathos/cli_render.py:59-65`; `bathos/cli_cyclopts.py:30`; `naurmalade/cyclopts_cli.py:89,125,133-135` |
| A14 | alphex currently calls `wire()` for MCP only. The call `cisternal.wire(app, registry="alphex")` sits inside the `mcp_server()` entry point (`mcp.py:118`), where `app` is the FastMCP instance. `alphex.mcp` imports `cisternal` and `fastmcp` and raises `SystemExit` if they are missing (`mcp.py:20-35`). Its five tools are async: `list_alphabets` (`mcp.py:40-43`), `show_alphabet` (`:46-54`), `relation` (`:57-70`), `perm` (`:73-94`; `policy: str = "raise"` is positional-or-keyword; raises `ValueError` on a bad policy at `:90-92`) and `lint` (`:97-104`). Its five hand-written CLI commands each take `json_out: bool` → `--json-out`: `list` (`def list_`, `cli.py:57-68`, custom line rendering at `:64-68`), `show` (`:71-74`), `relation` (`:77-80`), `perm` (`:83-92`, with `*, policy` keyword-only, and `raise SystemExit(msg)` on a bad policy at `:90-91`) and `lint` (`:95-116`: `"no warnings"` when empty at `:112`, `--strict` → `sys.exit(1)` at `:115-116`). The CLI docstrings differ from the `mcp.py` docstrings (e.g. `perm`: `cli.py:84-88` vs `mcp.py:75-88`). | VERIFIED | Files read at the cited lines |
| A15 | `SeamExplosionError` is a bare `Exception` subclass with no report attribute. `SeamExplosionReport.format_text()` is a separate dataclass. redsox defines no `ConfigError`. | VERIFIED | `redsox/core/seams.py:19-37`; `grep -rn "class ConfigError" redsox/src` returns no hits. Attaching the report to the exception is a redsox-side change, so the worked example (§6.6) treats `exc.report` as optional |
| A16 | cyclopts' `_is_nested_call()` defaults the inner `result_action` to `"return_value"`, so calling `app(tokens)` inside a command returns the inner command's value instead of exiting. | VERIFIED for the returned-value form only | Recon cites `core.py:1860,1948`. Spike `/tmp/claude-1000/spk/meta.py --verbose hello --n 3`: an `@app.meta.default` that sets module state and does `return app(tokens)` printed `hello 3 verbose= True`, and the inner command's `int` return `7` became the outer `app.meta()` exit code (`EXIT 7`). So the inner call returned the value and the outer call applied `result_action` once. Other uses of a nested `app()` call (e.g. discarding its value) were not exercised. §7 still recommends calling tool functions directly, not re-entering `app()` |
| A17 | The recon "consumers" report claims `wire()` already supports `result_action`. That is **false**: `result_action` is a cyclopts `App` parameter that bathos and naurmalade set themselves, and `wire()` has no such parameter. | VERIFIED | `wired.py:112-122` |
| A18 | cyclopts calls `command(*bound.args, **bound.kwargs)`. An argument the user supplied positionally therefore arrives in `args`, not `kwargs`, and a closure that reads only `kwargs` misses it. | VERIFIED | `cyclopts/_run.py:50` |
| A19 | A callable `result_action` ignores a returned `int`; it is not used as an exit code. `sys.exit(code)` raised inside the command is honoured under any `result_action`. | VERIFIED (first half) | `_result_action.py:92-93`. Second half: `SystemExit` propagates out of the command before `result_action` runs (A1 passthrough). Tests 28/29 exercise both Apps |
| A20 | Five cyclopts 4.18 behaviours for group lookup and collision. (a) Mounting a user App makes `app[name] is sub` true, and `sub.default_command is None`. (b) A function command is stored as a cyclopts-built wrapper `App` whose `default_command` is the function (`core.py:1418-1427`: `type(self)(**kwargs)` then `app.default(obj)`). (c) `name in app` is True for both kinds. (d) Mounting a second `App(name=g)` under a taken name raises `CommandCollisionError` (`core.py:1445-1447`). (e) Today's `_get_or_create_subapp` mounts unconditionally (`wired.py:76-80`), so wiring into a pre-mounted group raises `CommandCollisionError` at `wire()` time. | VERIFIED | This session's probe: `a["g"] is s` → True; `s.default_command` → None; `a["jobs"]` wrapper `default_command` → `<function jobs>`; `"g" in a`, `"jobs" in a` → True; second mount → `CommandCollisionError`. T4g re-asserts the discriminator as a test (30). Residual UNVERIFIED: that a user App which declares its own `@default` is the only false negative of the `default_command is None` discriminator (R9) |
| A21 | `myxcel.MyxcelError` exists with an integer class attribute `exit_code`, overridden per subclass. No `MaraxiomError` exists. | VERIFIED | `myxcel/src/myxcel/_error.py:1-31` |
| A22 | cyclopts' default long-flag name for a parameter is `"--" + cyclopts.utils.default_name_transform(identifier)`. `default_name_transform` (`utils.py:208-230`) is `_pascal_to_snake(s).lower().replace("_", "-").strip("-")`. `Parameter.name_transform` falls back to it when no App transform is set (`parameter.py:362-363`). | VERIFIED | `utils.py:208-230`; `parameter.py:362-363` |
| A23 | cyclopts derives negative flags in `Parameter.get_negatives(type_)` (`parameter.py:365-423`): unions merge member negatives (`:370-381`); bool and implicit-bool iterables use `negative_bool`; None-types use `negative_none`; other negatable iterables use `negative_iterable`, which defaults to `("empty-",)` (`:282-287`). User negatives that start with `-` are kept verbatim, and the rest are normalised to `--<prefix><neg>` (`:392-396, 419-421`). Only `--` long names get negatives (`:401`). | VERIFIED (source read) | UNVERIFIED: that `get_negatives` can be called on a `Parameter` built before registration, with `name` set to a tuple (it asserts `isinstance(self.name, tuple)` at `:399`). Spike in T3: `Parameter(name=("--x",)).get_negatives(bool) == ("--no-x",)`, the `list[str]` analogue → `("--empty-x",)`, and `Parameter(name=("--x",), negative="off").get_negatives(bool) == ("--off",)`. If the spike fails, the builder reimplements exactly those three rules, citing the lines above |
| A24 | cyclopts 4.18 does **not** reject two parameters that claim the same long flag. The first-declared parameter silently receives the value, and `--help` lists both. | VERIFIED | This session's probe: `def f(json: bool=False, *, json_out: Annotated[bool, Parameter(name="--json")]=False)` and `f --json` → `json=True, json_out=False`; `--help` shows `JSON --json --no-json` and `--json --no-json` |
| A25 | An explicit cyclopts `Parameter(name="foo")` (no leading hyphen) resolves to the long flag `--foo`. | UNVERIFIED | Spike in T3: register `def f(*, a: Annotated[int, Parameter(name="foo")] = 0)` and parse `f --foo 3`. If false, the builder uses explicit names verbatim and keeps only those that start with `--` |
| A26 | `Annotated[T, Parameter(parse=False)] = default` makes cyclopts refuse the flag (`UnknownOptionError` on `--token`) and leave the parameter unbound, so the function default applies. The required keyword-only form `*, token: Annotated[T, Parameter(parse=False)]` (no default) is also accepted at registration, and cyclopts leaves it unbound without raising a missing-argument error, so `cli_cmd` is called without it. | VERIFIED (registration acceptance of both forms, source read); UNVERIFIED (parse behaviour of both forms) | `parameter.py:231` declares `parse`; `parameter.py:533-540` raises `ValueError` for a `parse=False` parameter only when it is neither `KEYWORD_ONLY` nor defaulted. Spike in T3 as a standalone probe, for both forms; test 34 (T4) then asserts both through `wire()` |
| A27 | No consumer passes a `cli_group` string that contains whitespace, so treating whitespace as a path separator is back-compatible. | VERIFIED | This session's grep over `~/projects/*/src` for `cli_group="… "` returned no hits |
| A28 | The `default_parameter` that cyclopts applies to a command registered on a sub-App is `Parameter.combine` of the `default_parameter` of each App on the path from the root to that sub-App, root first, with `None` entries skipped. `wire()` can compute it before registration from the App objects alone. | UNVERIFIED | Spike in T4: on `root = App(default_parameter=Parameter(negative=()))` with a sub-App `g`, register a bool parameter `x` and check that `--help` lists no `--no-x`; compare with the predicted `get_negatives` on the combined chain. If the resolution differs, the builder uses only the target sub-App's own `default_parameter`, and R8 documents the gap |
| A29 | A `cyclopts.App(name=g)` constructed without help reads `help == ""`, not `None`. Assigning `sub.help = "H"` after the sub-App is mounted takes effect: the parent's `--help` lists `g` with `H`. So cisternal cannot use `sub.help is None` to tell whether a level has help, and records the help it applied itself (§5.6). | VERIFIED | Spike `/tmp/claude-1000/spk/h.py`: `repr(g.help)` → `''`; after `g.help = "H"` → `'H'`; root `--help` shows `g  H` |

Spikes ran against the worktree venv (CPython 3.13.12, cyclopts 4.18.0, fastmcp 4.0.10, rich 15.0.0). They are inspection probes only, cite no numbers, and need no sidecar.

## 4. API design

The new module is `src/cisternal/registration/cli_contract.py`. It stays fastmcp-free. Its only module-scope cisternal import is `cisternal.registration.errors` (`CisternalWireError`). It imports `cyclopts`, `cisternal.adapters.cli.timed_command`, `cisternal.registration.compose` and `cisternal.registration.wired` inside functions only (R10).

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, TypeAlias

from cisternal.registration.errors import CisternalWireError

# The first parameter is Any, not Exception, so that handlers typed on a narrower exception
# (e.g. `(exc: SeamExplosionError, ctx)` in §6.6, `(exc: ContemplexError, ctx)` in §6.9) type-check.
ExitHandler = Callable[[Any, "CliContext"], "int | None"]
SuccessFormatter = Callable[[Any, "CliContext"], Any]
PrepareHook = Callable[["CliContext"], None]
ReportFn = Callable[[BaseException], None]
GroupPath: TypeAlias = str | tuple[str, ...]   # "flow visuals" == ("flow", "visuals")


@dataclass(frozen=True)
class CliOption:
    """A CLI-only keyword option injected into the CLI callable's signature.

    It is never passed to the tool function. Its parsed value lands in ctx.options[name].
    Its CLI flags are derived exactly like a tool parameter's (§5.4).
    """
    name: str                         # Python identifier
    annotation: Any                   # real type object, e.g. bool or Annotated[bool, Parameter(...)]
    default: Any = None
    help: str | None = None           # wrapped by the builder as Annotated[annotation, Parameter(help=help)]

    def __post_init__(self) -> None:
        """Raise at construction:
        - ValueError if name is not str.isidentifier() or keyword.iskeyword(name);
        - TypeError if annotation is a str or a typing.ForwardRef (R5);
        - ValueError if help is set AND annotation is Annotated[...] whose metadata holds a
          cyclopts Parameter with help is not None (cyclopts imported lazily here)."""


def json_option(flag: str = "--json", *, name: str = "json_out",
                help: str = "Emit machine-readable JSON instead of formatted output.") -> CliOption:
    """The standard JSON flag:
    CliOption(name, Annotated[bool, Parameter(name=flag, negative="")], False, help=help)."""


def default_report(exc: BaseException) -> None:
    """Write the exact F1 bytes to sys.stderr: f"Error ({type(exc).__name__}): {exc}\\n"."""


def exit_code_attr(attr: str = "exit_code", *, default: int = 1,
                   report: ReportFn = default_report) -> ExitHandler:
    """Return a handler that calls report(exc), then returns getattr(exc, attr).
    Covers int-valued attributes only. The handler falls back to `default` when the attribute
    is missing, is a bool, is not an int (a str or StrEnum code included), or is outside 1..255.
    String or enum codes need a handler with a lookup table (§6.9).
    `default` itself is validated to 1..255 at call time (ValueError), and `report` must be
    callable (TypeError).
    If `report` raises, the exception propagates to _resolve_exit's handler-failure path (§5.3)."""


@dataclass
class CliContext:
    """Per-invocation context handed to prepare, format_success and exit handlers.

    It is created empty before any parsing work, so exit handlers may receive a partially
    built ctx: arguments == {} (and options possibly partial) when the failure happened
    before or during binding (§5.2). It carries no App-level (global) option values (N8)."""
    tool_name: str                    # entry.name (matches telemetry `cmd` and the MCP name)
    command: str                      # CLI path as registered: "<seg1> … <segN> <cli_name>" or "<cli_name>"
    arguments: dict[str, Any] = field(default_factory=dict)  # tool args by name, defaults applied; prepare may mutate
    options: dict[str, Any] = field(default_factory=dict)    # CLI-only option values, keyed by CliOption.name


@dataclass(frozen=True)
class CliContract:
    format_success: SuccessFormatter | None = None
    exit_codes: Mapping[type[Exception], int | ExitHandler] = field(default_factory=dict)
    options: Sequence[CliOption] = ()
    prepare: PrepareHook | None = None
    help: str | None = None           # --help text override; forwarded to app.command(help=) only when set
    show: bool | None = None          # visibility override; forwarded to app.command(show=) only when set

    __hash__ = None   # contracts are unhashable: hash(contract) raises TypeError

    def __post_init__(self) -> None:
        """Normalise, then validate eagerly at construction.

        Normalise (via object.__setattr__, since the dataclass is frozen):
          - options    -> tuple(options)                     (a list passed in becomes a tuple)
          - exit_codes -> types.MappingProxyType(dict(exit_codes))  (copied, read-only)

        Validate:
          - every exit_codes key is a class with issubclass(key, Exception), else TypeError
            (SystemExit and KeyboardInterrupt are not Exception subclasses, so they are rejected here);
          - a bool value -> TypeError (checked before int, since bool is an int);
          - an int value of 0 -> ValueError; any int value outside 1..255 -> ValueError;
          - any other value must be callable, else TypeError;
          - option names are unique within this contract, else ValueError;
          - help is None or a str, else TypeError; show is None or a bool, else TypeError.
        Per-option identifier, annotation and help checks live in CliOption.__post_init__."""

    def merged_over(self, base: CliContract | None) -> CliContract:
        """Pure field-wise merge in which self (more specific) wins; see §5.1.
        merged_over(None) returns self (the identical object).
        Otherwise it returns CliContract(options=(*base.options, *self.options),
        exit_codes={**base.exit_codes, **self.exit_codes}, ...), which goes back through __post_init__.
        Raises ValueError if self.options and base.options share an option name.
        Does no signature inspection."""


def cli_command(
    fn: Callable[..., Any],
    *,
    name: str | None = None,              # telemetry cmd name; default fn.__name__
    command: str | None = None,           # ctx.command; default name
    contract: CliContract | None = None,
    recovery: tuple[Callable[[BaseException], bool], Callable[[], None]] | None = None,
    telemetry: bool = True,
) -> Callable[..., Any]:
    """Return the CLI callable that wire() would build for fn. Register it yourself:
    app.command(name="audit")(cli_command(audit, contract=...)), or put it in a wired group
    with cisternal.cli_group(app, "g").command(...)(cli_command(...)).
    contract.help and contract.show are NOT applied: cli_command returns a callable, not a
    registration. Pass help=/show= to app.command yourself.
    The collision check sees no App default_parameter (R8).
    With contract=None this is exactly today's F1 closure, plus the A9 annotation resolution.
    Raises CisternalWireError when the CLI callable cannot be built (§5.4)."""


def cli_group(app: Any, path: GroupPath, *, help: str | None = None) -> Any:
    """Return the cyclopts sub-App at `path` on `app`, through the same cache wire() uses.

    Walks the path one segment at a time (§5.6) and applies the adoption rule at each level.
    `help` applies only to the leaf:
      - when cli_group creates the leaf, it is created with that help;
      - on a cache hit for a leaf that cisternal created without help, the help is applied;
      - on a cache hit for a cisternal-created leaf that already has a different help,
        CisternalWireError is raised (the same help again is a no-op);
      - an adopted user App is left untouched, and the help is ignored.
    cli_group(app, "flow visuals") is cli_group(cli_group(app, "flow"), "visuals").
    Raises CisternalWireError on empty segments, or when a segment names a function command."""
```

The group machinery (`_CLI_SUBAPPS`, `_CLI_CREATED_HELP`, `_normalise_group_path`, `_get_or_create_subapp`, `_probe_group_path`, `cli_group`) lives in `cli_contract.py`. `wired.py` imports `_CLI_SUBAPPS` and `_get_or_create_subapp` from there, so `wired._CLI_SUBAPPS` remains the same dict object. `_CLI_CREATED_HELP: dict[tuple[int, str], str | None]` records, for each cache key whose level cisternal created, the help cisternal applied, or `None` if it applied none. A key missing from it is an adopted level (A29).

There are two builders, and both are reached from `wire()` and `cli_command()`:

```python
# wired.py: hoisted to module scope in T0b (verbatim body), so its __globals__ remain wired.py's (§9).
# The former free variables `recovery` and `cli_telemetry` become parameters.
def _make_cli_cmd(original_fn, cmd_name, *, recovery, telemetry) -> Callable[..., Any]:
    """Today's closure verbatim, with `cli_telemetry` read as `telemetry`, except that line 318 becomes
    _cli_cmd.__annotations__ = _resolve_cli_hints(original_fn, strict=False)."""
# call site in wire(): _make_cli_cmd(_fn, _name, recovery=recovery, telemetry=cli_telemetry)

# cli_contract.py
def _resolve_cli_hints(fn, *, strict: bool, tool_name: str = "") -> dict[str, Any]:
    """Resolve the annotations of fn's *parameters* only.

    from cisternal.registration import wired as wired_module      # lazy import
    src = inspect.unwrap(fn)                                       # globals from the unwrapped fn (A9)
    globalns = {**vars(wired_module), **getattr(src, "__globals__", {})}
    raw = fn.__annotations__                                       # annotations read from fn ...
    if not raw and hasattr(fn, "__wrapped__"):
        raw = src.__annotations__                                  # ... or from the unwrapped fn (3.14, A9)
    out = {}
    for pname in inspect.signature(fn).parameters:
        if pname not in raw: continue
        shim = lambda: None; shim.__annotations__ = {pname: raw[pname]}
        try:
            out[pname] = typing.get_type_hints(shim, include_extras=True, globalns=globalns)[pname]
        except (NameError, AttributeError, TypeError, SyntaxError) as e:   # SyntaxError: malformed str, e.g. "list[int"
            if strict:
                raise CisternalWireError(message=f"tool {tool_name!r}: cannot resolve annotation of "
                                                 f"parameter {pname!r}: {getattr(e, 'name', None) or e}") from e
            return dict(fn.__annotations__)   # legacy fallback: raw copy, exactly as today (incl. 'return');
                                              # the __wrapped__ substitution above is used for resolution only
    return out                            # 'return' and any other non-parameter key are dropped
    """

def _build_cli_callable(fn, *, tool_name: str, command: str, contract: CliContract | None,
                        recovery, telemetry: bool,
                        app_default_parameter: Any = None) -> Callable[..., Any]:
    """Delegates to wired._make_cli_cmd (lazy import) when contract is None. Otherwise it
    builds the §5.2 closure with options injected (§5.4) and hints resolved with strict=True.
    The contract-path closure sets __name__ = fn.__name__ and __doc__ = fn.__doc__ exactly as
    wired.py:315-316 does, then __signature__ and __annotations__ (§5.4). It sets no __wrapped__,
    __qualname__ or __module__ (the legacy closure sets none of them either, wired.py:315-318).
    app_default_parameter is the target App's resolved default_parameter (A28); wire() passes it,
    cli_command() passes None. It is used only by the collision check (§5.4).
    Every failure raises CisternalWireError(message=f"tool {tool_name!r}: ...")."""

def _resolve_exit(exc: Exception, ctx: CliContext,
                  exit_codes: Mapping[type[Exception], int | ExitHandler]) -> int:
    """§5.3. exit_codes is the effective (merged) contract's map."""
```

Changed signatures. All additions are keyword-only with a `None` default.

```python
# decorator.py / registry.py
def tool(fn=None, *, registry="default", name=None,
         cli_group: str | tuple[str, ...] | None = None, cli_name=None,
         cli_contract: CliContract | None = None): ...
def register(fn, *, registry="default", name=None,
             cli_group: str | tuple[str, ...] | None = None, cli_name=None,
             cli_contract: CliContract | None = None) -> None: ...

@dataclass
class ToolEntry:
    name: str; fn: Callable[..., Any]; registry: str
    cli_group: str | tuple[str, ...] | None = None; cli_name: str | None = None
    cli_contract: CliContract | None = None        # NEW, trailing

# wired.py
def wire(server, app=None, *, adapter=None, registry="default", expected=None,
         validate=True, recovery=None, cli_telemetry=True,
         cli_contract: CliContract | None = None,
         cli_contracts: Mapping[str, CliContract] | None = None,
         cli_group_help: Mapping[str | tuple[str, ...], str] | None = None) -> WiredRegistry: ...
# cli_contract:   W, the default for every command of this call.
# cli_contracts:  {entry.name: contract}. Applied at T (tool) precedence. A key that names no entry
#                 of `registry` raises CisternalWireError. A tool that has both a decorator contract
#                 (entry.cli_contract) and a map entry raises CisternalWireError. Both checks run
#                 before any registration, and also when app is None.
# cli_group_help: {group_path: help_text}. Keys are normalised to segment tuples, so
#                 {"flow": "Flow ops", "flow visuals": "Visual ops"} gives each level its own help.
#                 A key that is not a prefix of any entry's normalised cli_group path raises
#                 CisternalWireError in the pre-pass (§5.1). Help is applied to levels cisternal
#                 creates, and to cisternal-created levels that have no help yet; a cisternal-created
#                 level with a different help raises CisternalWireError; an adopted pre-mounted level
#                 is left untouched (§5.6).
```

**Exports.** These names are exported from `cisternal.registration` and from top-level `cisternal`: `CliContract`, `CliOption`, `CliContext`, `json_option`, `default_report`, `exit_code_attr`, `cli_command`, `cli_group`. Each goes in `__all__` and is imported eagerly, because the module is fastmcp-free and cycle-free (R10). If T5's acceptance check fails for a name, that name goes through `_lazy_import`/`__dir__` instead, and T5 records which.

**Where the contract attaches:** both levels.
- **W level:** a `wire(cli_contract=...)` default applies to every command of that call.
- **T level:** a per-tool contract refines W. It comes either from `@tool(cli_contract=...)` on the tool, or from `wire(cli_contracts={entry.name: ...})` at the wiring site, never both for one tool.
- A per-tool contract on a tool wired with `app=None` is inert.

## 5. Semantics

### 5.1 Effective contract, precedence and the wire-time pre-pass

Let T be the tool contract: `entry.cli_contract` or `cli_contracts.get(entry.name)`. If both are set, `wire()` raises `CisternalWireError` naming the tool. Let W be `wire(cli_contract=...)`.

The effective contract is `T.merged_over(W)` when T is set, and W otherwise. (`merged_over(None)` returns T itself.) If both are `None`, the effective contract is `None` and the **legacy code path runs unchanged** (§9). The merge goes field by field:

- **`format_success`**: T's if not None, else W's.
- **`prepare`**: T's if not None, else W's. Hooks do not chain; a tool that needs both calls W's hook from its own.
- **`help`**, **`show`**: T's if not None, else W's. If the effective value is `None`, the keyword is not passed to `app.command` at all, so `app.command(name=_cli_name)` is called exactly as today.
- **`exit_codes`**: `MappingProxyType({**W.exit_codes, **T.exit_codes})`. On an equal key, T wins.
  - Resolution then runs over the merged map (§5.3), so a T entry for a superclass does *not* shadow a W entry for a more specific subclass.
  - Example: W has `{ConfigError: 2}`, T has `{MyxcelError: 9}`, and `ConfigError` is raised → 2.
- **`options`**: `(*W.options, *T.options)`, always a tuple because of `__post_init__`.
  - `merged_over` raises `ValueError` on a duplicate option name. When `wire()` calls it, that error is re-raised as `CisternalWireError` naming the tool.
  - Collisions with the tool's own parameters are checked by the builder (§5.4), not by `merged_over`.

**Wire-time pre-pass.** `wire()` validates in two stages before its first `add_tool` or `app.command` call.

1. **Always**, including with `app=None`: the `cli_contracts` unknown-key and decorator-conflict checks.
2. **When `app is not None`**, for every entry, in this order:
   1. Resolve the effective contract, including the W/T merge.
   2. Normalise the group path and validate it with `_probe_group_path` (§5.6). The probe only detects rejections and help conflicts; it mounts nothing and writes no cache entry.
   3. Compute the target sub-App's resolved `default_parameter` (A28) from the Apps that already exist on the path. Levels that cisternal will create contribute `None`, because cisternal creates them without a `default_parameter`.
   4. Build the entry's CLI callable through `_build_cli_callable`, which runs the §5.4 collision check.

   **Planned names.** Across the entries of the call, the pre-pass tracks the names it plans to register at each level: at the root, every flat `cli_name` and every first group segment; under each group path, every next segment and every leaf `cli_name`. It raises `CisternalWireError` naming the clashing name, before the first `add_tool`, when one name is planned at one level both as a command and as a group (a flat `jobs` and `cli_group="jobs"`, in either order; a flat `flow` and `cli_group="flow visuals"`), or when the same leaf is planned twice at one level. Without this check those cases would get through the pre-pass and raise cyclopts' `CommandCollisionError` partway through the registration loop (spiked: flat-then-group, group-then-flat and a duplicate leaf each raise `CommandCollisionError` in cyclopts 4.18).

   It also raises `CisternalWireError` naming the clashing name when a planned flat name or leaf name is already `in` its existing target App level (A20c): the root, or a group level that already exists (cached from an earlier call) or is adopted. An example is a flat name that an earlier `wire()` call already registered on the root, or a leaf that names a command already present in an adopted group. Levels that cisternal will create are empty, so they need no check. A group segment that already exists at its level is not a clash; the probe handles it (adopt, reuse or reject, §5.6).

   The pre-pass also normalises every `cli_group_help` key and checks that it is a prefix of at least one entry's normalised group path. A tuple `k` is a prefix of `p` when `p[:len(k)] == k`. Any other key raises `CisternalWireError` naming the key.

The registration loop then mounts groups and registers the pre-built callables. **Any `CisternalWireError` raised at wire time leaves both `server` and `app` untouched**: no tool is added to the server, no group is mounted or cached, and no command is registered (test 35).

### 5.2 Call layering (contract present)

```
_cli_cmd(*args, **kw)                       # registered on cyclopts; signature = tool sig + options
  ctx = CliContext(tool_name, command)      # arguments={}, options={}; cannot fail
  try:                                      # F1: everything below is inside it
      for o in effective.options:
          ctx.options[o.name] = kw.pop(o.name, o.default)
      b = sig.bind_partial(*args, **kw); b.apply_defaults()   # sig = inspect.signature(entry.fn)
      ctx.arguments = dict(b.arguments)
      if prepare: prepare(ctx)              # untimed; mutates ctx.arguments
      b2 = _rebind(sig, ctx.arguments)      # untimed; before the span; may raise TypeError
      return _timed(b2, ctx)                # timed_command(entry.name), see the telemetry rule below
           ├─ result = apply_recovery_sync(fn, recovery, *b2.args, **b2.kwargs)
           └─ return format_success(result, ctx) if format_success else result
  except SystemExit: raise                  # unchanged passthrough (formatter/prepare/tool may sys.exit)
  except Exception as exc:
      sys.exit(_resolve_exit(exc, ctx, effective.exit_codes))   # §5.3; ctx may be partially built
```

- **Binding.** CLI-only options are always keyword-only (§5.4), so popping them from `kw` first is complete. cyclopts may pass tool arguments positionally (A18), so the closure binds `args` and `kw` through the tool's own signature and never reads `kw` alone. It binds with `sig.bind_partial`, not `sig.bind`, because cyclopts does not supply a required `parse=False` parameter (A26): such a parameter is legitimately absent until `prepare` sets it. After `apply_defaults`, `ctx.arguments` has an entry for every parameter except a required (no-default) parameter that cyclopts did not supply, typically a required keyword-only `parse=False` one; that key is missing from `ctx.arguments` until `prepare` sets it. If it is still missing after `prepare`, `_rebind` step 4 raises `TypeError(f"prepare removed required argument {name!r}")`, so the tool is never called without it.
  - A **VAR_POSITIONAL** `*rest` appears as `ctx.arguments["rest"]: tuple`, which is `()` when empty.
  - A **VAR_KEYWORD** `**extra` appears as `ctx.arguments["extra"]: dict`, which is `{}` when empty. Extra keyword arguments are never flattened into the top level.
  - A bind failure (`bind_partial` still rejects unexpected keyword arguments and surplus positionals) is an ordinary `Exception` inside F1. It produces the F1 line and exit 1, or the mapped code, and handlers then see `ctx.arguments == {}`.
- **Rebinding (`_rebind(sig, arguments)`).** It runs after `prepare` and before the span opens, inside F1, in four steps:
  1. **Unknown keys.** If `arguments` has a key that is not in `sig.parameters`, raise `TypeError(f"prepare set unknown argument {k!r}")`.
  2. **Rebuild `(a, k)` by parameter kind, in declaration order.** The *gap* is the first `POSITIONAL_ONLY` or `POSITIONAL_OR_KEYWORD` name absent from `arguments`.
     - `POSITIONAL_ONLY` and `POSITIONAL_OR_KEYWORD` values before the gap are appended to `a`.
     - After the gap, a present `POSITIONAL_ONLY` value, or a non-empty `VAR_POSITIONAL` tuple, cannot be placed. Raise `TypeError(f"prepare removed argument {absent!r} ahead of {later!r}")`, naming the absent argument and the later one.
     - After the gap, a present `POSITIONAL_OR_KEYWORD` value goes into `k` by name.
     - With no gap, the `VAR_POSITIONAL` tuple is extended into `a`. After a gap, an empty tuple is dropped.
     - Present `KEYWORD_ONLY` values go into `k` by name.
     - The `VAR_KEYWORD` dict is merged into `k`.
  3. **Bind.** Call `b2 = sig.bind_partial(*a, **k)` and then `b2.apply_defaults()`.
  4. **Required check.** If any parameter that is not `VAR_POSITIONAL`/`VAR_KEYWORD` and has no default is absent from `b2.arguments`, raise `TypeError(f"prepare removed required argument {name!r}")`.

  The result is `fn(*b2.args, **b2.kwargs)`, with positional-only, positional-or-keyword, `*args` and `**kwargs` arguments in their correct positions. Every `TypeError` above goes through `_resolve_exit` and emits no `cli.cmd_*` event (test 20b).
- **Success.** Whatever the formatter returns goes back to cyclopts' `result_action`.
  - Under the default action (A6), `None` exits 0 and prints nothing.
  - An `int` is the exit code **only under the default action**; a callable `result_action` ignores it (A19).
  - For a result-shaped failure (an error envelope), the route that works under any `result_action` is `sys.exit(code)` from the formatter. The formatter is inside the span, so `timed_command` records the exit as `ok=False` with `exit_code` (A2).
  - The guide recommends that formatters print and return `None`.
  - Without a formatter, the raw result is returned exactly as today.
- **Telemetry, one rule: `prepare` and `_rebind` are never timed.**
  - **Usual case: `entry.fn` is not `_cisternal_timed`.** Dispatch and the formatter run inside one `timed_command(entry.name)` span, opened after `_rebind` returns.
    - A formatter crash is recorded as `ok=False` with the formatter's `exc_type`.
    - A formatter `sys.exit(n)` is recorded with `exit_code=n`.
    - The duration includes any rendering the formatter does itself.
    - A renderable that the formatter *returns* is printed by `result_action` after the span closes, so that printing is not timed.
  - **`entry.fn` is `_cisternal_timed`.** `wire()` adds no span. The tool's own span covers only the tool call. The formatter runs untimed: a formatter crash shows up only as the F1 exit with no `ok=False` event, and a formatter `sys.exit` is not recorded either.
  - **`cli_telemetry=False` / `telemetry=False`.** No span at all.
  - **In every case:**
    - Anything that fails before the span opens emits **no** `cli.cmd_*` event. That covers option pop, bind, `prepare` (crash or `sys.exit`) and `_rebind` (unknown key, misplaced positional after a gap, or missing required argument). Those failures are visible only as the F1 exit.
    - Exit handlers run outside any span, inside F1, so telemetry observes the original exception (A2).
    - A handler-chosen exit code is not added to telemetry, because it is not known until after the span closes (R1).
- **Recovery.** Unchanged and threaded identically (A4). With `recovery` set, a final failure that has `to_result()` becomes a *return value* and reaches `format_success`, not `exit_codes`. This is documented.
- **cli_group / cli_name.** Unchanged for single-segment groups (A12). `ctx.command` equals the joined-path string appended to `WiredRegistry.cli_commands`.
- **Registration.** `wire()` calls `target_app.command(name=_cli_name, **extra)(cli_cmd)`. `extra` contains `help=` and/or `show=` only when the effective contract sets them (§5.1). With no contract, or with both `None`, `extra` is empty (G9). With `help` unset, cyclopts takes the command's help from `cli_cmd.__doc__`, which is `entry.fn.__doc__` (§5.4), so the docstring summary and its `Args` section appear exactly as today (test 36).

### 5.3 Exception → exit code resolution

```python
def _resolve_exit(exc, ctx, exit_codes):      # ctx may be partial: arguments == {}
    for klass in type(exc).__mro__:           # most specific first; dict order irrelevant
        if klass in exit_codes:
            v = exit_codes[klass]; break
    else:
        v = None
    if v is None or isinstance(v, int):       # bools rejected at construction
        default_report(exc)                    # F1 bytes, unchanged
        return 1 if v is None else v
    try:
        code = v(exc, ctx)                     # handler renders its own report
    except SystemExit:
        raise                                  # handler may exit explicitly
    except Exception:
        _log.warning("cisternal: exit handler for %s failed", type(exc).__name__, exc_info=True)
        default_report(exc)
        return 1
    if code is None:                           # "not handled": F1 line, exit 1
        default_report(exc)
        return 1
    if not isinstance(code, int) or isinstance(code, bool) or not 0 <= code <= 255:
        _log.warning("cisternal: exit handler returned %r; using 1", code)
        return 1
    return code
```

- `exit_codes` is the effective contract's merged map. The §5.2 closure passes `effective.exit_codes`.
- Matching is exact by MRO over the merged map. With multiple inheritance, the first base in MRO order wins.
- Unmapped exceptions get today's F1 behaviour: the same line and exit 1.
- `KeyboardInterrupt` and other `BaseException`s that are not `Exception`s are not caught (unchanged).
- Mapped `int` values are 1..255, validated at construction. A *handler* may return 0, meaning "handled, success". That is allowed and documented.
- Handlers must tolerate a partially built `ctx`: `ctx.arguments == {}` and `ctx.options` possibly incomplete when the failure came from option pop or bind. `default_report` and `exit_code_attr` never read `ctx`.
- `exit_code_attr()` is a handler for int-valued code attributes. For myxcel, `{MyxcelError: exit_code_attr()}` prints the F1 line and exits with the subclass's own code; for example `ConfigError` → 2 via the MRO (A21). Passing `report=` replaces the F1 line with the consumer's own report (§6.8). A string or enum code, such as contemplex's `ErrorCode`, falls back to `default`; such codes need a handler with a lookup table (§6.9).

### 5.4 CLI-only options

When the CLI callable is built in `_build_cli_callable`, the contract-path closure first takes `__name__ = fn.__name__` and `__doc__ = fn.__doc__`, exactly as `wired.py:315-316` does. It adds no `__wrapped__`, `__qualname__` or `__module__`, matching the legacy closure (`wired.py:315-318`). Its `__signature__` and `__annotations__` are then set as follows.

**`__signature__`** becomes `sig.replace(parameters=...)`, keeping the return annotation. Each option is added as `Parameter(name, KEYWORD_ONLY, default=o.default, annotation=A(o))`, where:

- `A(o) = Annotated[o.annotation, cyclopts.Parameter(help=o.help)]` when `o.help` is set;
- `A(o) = o.annotation` otherwise.

Options go before any `VAR_KEYWORD` parameter and after everything else.

**`__annotations__`** becomes `{**_resolve_cli_hints(fn, strict=True, tool_name=...), o.name: A(o)}`. That is parameter keys only; `return` is dropped (§5.5). These are real objects (enforced by `CliOption.__post_init__`), so `get_type_hints` passes them through (A7). The tool function and the MCP callable never see the options, and `compose_mcp_callable` is untouched.

**Collision validation** happens in the builder. It runs on the hints resolved by `_resolve_cli_hints(strict=True)`, never on `inspect.Parameter.annotation`, which is still a string under `from __future__ import annotations`. A parameter annotation that cannot be resolved raises `CisternalWireError` naming the tool and the parameter. An unresolvable return annotation does not raise. (The no-contract path keeps the legacy raw-copy fallback.) On a collision the builder raises `CisternalWireError(message=...)` naming the tool. When the builder runs inside `wire()`, it runs in the pre-pass (§5.1), so a collision leaves `server` and `app` untouched. It checks two things:

1. **Identifiers.** An option name equal to *any* parameter name of `inspect.signature(fn)` is a collision. That includes positional-only, `*args` and `**kwargs` parameters, since the injected signature would otherwise contain duplicate names.
2. **Long CLI flags only.** The builder computes a long-flag set (names starting with `--`) for every tool parameter of kind `POSITIONAL_OR_KEYWORD` or `KEYWORD_ONLY`, and for every option, and rejects any overlap.
   - Positional-only, `*args` and `**kwargs` parameters are skipped.
   - A tool parameter whose combined `Parameter` (`Parameter.combine(app_default_parameter, *<Annotated Parameters>)`) has a falsy `parse` that is not a `re.Pattern` is skipped too, matching cyclopts' own test (`parameter.py:533`): cyclopts never parses it, so it claims no flag. Item 1's identifier check still applies to it. So a `parse=False` tool parameter `working_dir` and a `CliOption` that claims `--working-dir` under another identifier wire without error.
   - Short flags (`-n`) are not compared.

   Tool parameters and options use **the same derivation**. The identifier is the parameter name or `CliOption.name`. The annotation is the resolved hint, or `o.annotation` for an option; the `CliOption.help` wrapper adds only `Parameter(help=)` and does not change names. For collision derivation only, the hint used for negatives is derived the way cyclopts' `Argument._negatives_hint` derives it (`cyclopts/argument/_argument.py:997-1009`): when the hint is empty (`inspect.Parameter.empty`) or resolves to `Any`, it is replaced by `type(default)` only if the default is neither `inspect.Parameter.empty` nor `None`; otherwise the hint is kept unchanged, `Optional` and other unions included. So an unannotated `flag=False` and an `x: Any = False` both derive as `bool` and claim `--no-flag` / `--no-x`. An unannotated parameter whose hint stays empty (no default, or a `None` default) contributes only its name, with no negatives. With `type_` the annotation stripped of `Annotated`:
   - **Names.** If the `Annotated` metadata contains cyclopts `Parameter(name=...)` entries, those names are used (a str or a sequence; names without a leading hyphen are normalised per A25). Otherwise the name is `"--" + cyclopts.utils.default_name_transform(identifier)` (A22). The builder calls cyclopts' own transform and does not reimplement it.
   - **Negatives.** The builder delegates to cyclopts' `Parameter.get_negatives(type_)` (A23) on `Parameter.combine(app_default_parameter, *<Annotated Parameters>, Parameter(name=<normalised names tuple>))`. `app_default_parameter` comes first in the chain, and the `Parameter` carrying the normalised `--`-prefixed names comes last, so those names always win over an un-normalised `Parameter(name="foo")` in the metadata, and `get_negatives` sees them. It is the target App's resolved `default_parameter` (A28), passed by `wire()`, and `None` (skipped) from `cli_command()`. That covers:
     - the default `--no-<x>` for bool and implicit-bool types;
     - the iterable `--empty-<x>` (`parameter.py:282-287`);
     - user negatives, normalised: a value starting with `-` is kept verbatim, otherwise `--<prefix><neg>` (`:392-396, 419-421`);
     - `negative=""` meaning none (so `json_option()` claims only its flag);
     - union merging (`:370-381`);
     - App-wide negative settings from `default_parameter` (`wire()` only).

     If the A23 spike shows `get_negatives` cannot run before registration, the builder reimplements exactly those rules.
   - Only names starting with `--` enter the comparison.

   So a tool with `json: bool` collides with `json_option()`. The identifiers differ (`json` vs `json_out`), but both claim `--json`. Likewise a bool option `x2` claims `--no-x2` unless the App's `default_parameter` removes negatives.

This check is the only guard. cyclopts 4.18 silently lets the first-declared parameter win on a duplicated flag (A24). An `App` with a custom `name_transform` can make the derived names inaccurate; that is out of scope (R8).

### 5.5 A9 fix

In both paths, the CLI callable's `__annotations__` hold the hints that `_resolve_cli_hints` resolved (§4):

- **Per parameter.** Only names in `inspect.signature(fn).parameters` are resolved. `return` and any other non-parameter key are left out of the CLI callable's `__annotations__`, and an unresolvable non-parameter key is simply dropped. cyclopts reads only parameter names (A8), so nothing it uses is lost. `__signature__` keeps the return annotation.
- **Globals from the unwrapped function.** The resolver calls `src = inspect.unwrap(fn)` and uses `globalns={**vars(wired_module), **getattr(src, "__globals__", {})}`, so the tool module's globals override `wired.py`'s. The raw annotations are read from `fn.__annotations__`, which `functools.wraps` copies onto wrappers on CPython 3.13 (A2). When `fn.__annotations__` is empty and `fn` has `__wrapped__`, they are read from `src.__annotations__` instead; this covers 3.14, where a wrapper's `__annotations__` may be empty (A9). This matters for `@timed_command`-decorated tools (`adapters/cli.py:64`): the wrapper's own `__globals__` belong to `adapters/cli.py`, and an explicit `globalns` turns off `get_type_hints`' own `__wrapped__` unwrapping (test 9d).
- **`__signature__`** stays exactly `inspect.signature(original_fn)` in the no-contract path, and `inspect.signature(original_fn).replace(...)` in the contract path. Resolved annotations are **not** swapped into the signature. `tests/test_registration_wire.py:18` uses `from __future__ import annotations`, and `:561-565` asserts signature equality against the string-annotated original, so changing the signature would break test 24.
- **No-contract path.** A `NameError`, `AttributeError`, `TypeError` or `SyntaxError` while resolving any parameter falls back to `dict(original_fn.__annotations__)`. That is exactly today's line 318, `return` key included, so cyclopts then fails exactly as it does today.
- **Contract path.** The same errors on a *parameter* annotation raise `CisternalWireError` (§5.4). A malformed string annotation such as `"list[int"` makes `get_type_hints` raise `SyntaxError`, which is wrapped the same way (test 16c).
- **Why `wired.py`'s globals are merged in.** Names that resolve today only through them keep resolving. The case is an `Any` that the tool module imports only under `TYPE_CHECKING` (test 9b).
- **bathos' workaround.** Its post-def mutation of `__annotations__` stores real objects, which `get_type_hints` returns unchanged, so it keeps working (test 9c). After this change it is no longer needed (§8).
- **No `__wrapped__`.** Neither CLI callable gains a `__wrapped__` attribute.
- **Python versions.** The fix is verified on CPython 3.13 only. T0b spikes test 9d on 3.14, or records the 3.14 wrapped case as unverified.

### 5.6 Groups (`cli_group`, `cli_group_help`, adoption, nesting)

**Path normalisation (`_normalise_group_path`).**

- A `str` is split on whitespace (`"flow visuals"` → `("flow", "visuals")`).
- A `tuple[str, ...]` is used as given, and each element is `.strip()`ped.
- An empty path, an empty or whitespace-only segment, or a segment that itself contains whitespace raises `CisternalWireError`. Examples: `""`, `"  "`, `("a", "")`, `("a b",)`.

**Walking the path.** `_get_or_create_subapp(app, path, *, helps=None)` walks the normalised path one segment at a time. At each level, with `parent` the current App, `seg` the segment, `key = (id(parent), seg)`, `prefix` the path up to and including this level, and `h = helps.get(prefix)`:

1. **Cache hit.** If `key in _CLI_SUBAPPS`, use the cached App.
   - If `key in _CLI_CREATED_HELP` (cisternal created the level) and `h` is not None:
     - if the recorded help is `None`, set `sub.help = h` (A29) and record `h`;
     - if the recorded help equals `h`, do nothing;
     - otherwise raise `CisternalWireError(message=f"cli group {joined!r}: help already set to {recorded!r}")`.
   - If the level was adopted (`key not in _CLI_CREATED_HELP`), it is left untouched and `h` is ignored.
2. **Existing entry.** On a miss, if `seg in parent` (A20c), let `entry = parent[seg]`:
   - **Adopt** if `entry` is a `cyclopts.App` with `entry.default_command is None`, i.e. a user-constructed App mounted directly (A20a). Cache it, do not re-mount it, and do not record it in `_CLI_CREATED_HELP`. Its existing help and commands are kept, and `h` is ignored.
   - **Reject** otherwise, which covers cyclopts' wrapper around a function command (A20b) and a user App that declares its own `@default` (R9). Raise `CisternalWireError(message=f"cli group {joined!r}: {seg!r} is already a command, not a group")`.
3. **Create.** Otherwise create `cyclopts.App(name=seg, help=h)` (omitting `help=` when `h` is None), mount it on `parent`, cache it, and record `_CLI_CREATED_HELP[key] = h`.

**Probing without mounting.** `_probe_group_path(app, path, *, helps)` follows the same walk read-only, for the `wire()` pre-pass (§5.1). It raises exactly where steps 1 and 2 would raise (a help conflict or a rejection). It stops descending at the first level that step 3 would create, since nothing below it can collide. It returns the list of Apps that already exist on the path, for the `default_parameter` computation (A28). It mounts nothing and writes nothing to `_CLI_SUBAPPS` or `_CLI_CREATED_HELP`.

**Consequences.**

- `cli_group(app, "flow visuals")` is `cli_group(cli_group(app, "flow"), "visuals")`: both walks hit the same `(id(parent), segment)` keys.
- `wire()` passes `helps` = `cli_group_help` with keys normalised to tuples. Every key must be a prefix of some entry's path (§5.1).
- `cisternal.cli_group(app, path, help=None)` passes `{path: help}` (leaf only) and returns the identical object `wire()` uses, whichever is called first. A help supplied on the second call reaches a cisternal-created level whose help is still unset, in either call order (test 32).
- `ctx.command` and `WiredRegistry.cli_commands` record `" ".join((*segments, cli_name))`.
- For the collision check, `wire()` computes the target sub-App's resolved `default_parameter` (A28) from the existing Apps that `_probe_group_path` returned, and passes it to the builder.

## 6. Worked examples

Every example below is self-contained and lists its imports. Names that come from a consumer package and are not shown here (`load_config`, `enforce_no_sibling_parity_leak`, `_render`, `_surface`, `mcp`) are consumer code. T6 replaces them with a named stub prelude (§12).

### 6.1 Composition with an App-level `result_action` (bathos, naurmalade)

bathos keeps `App(result_action=cyclopts_result_action)`, and naurmalade keeps `App(result_action=render_envelope)`.

- A tool whose `format_success` returns `None` reaches the App's action as `None`, which bathos' action ignores (A13), and cyclopts exits normally.
- A formatter that needs a nonzero exit under such an App must `sys.exit(code)`, because the callable action would swallow a returned int (A19).
- Tools without a contract behave exactly as before.

### 6.6 redsox: `SeamExplosionError` → exit 2 with a report

redsox is CLI-only (§1), so it wires with `server=None`. The tool keeps redsox's `ConfigOption` (`-c/--config`) and its Annotated `out` (`-o/--out`) exactly as `redsox/cli/main.py:42-44` and `:88-91` declare them, and prints the report through a stdout `Console()`, as `main.py:34` and `:101-103` do. It currently imports cisternal through `redsox.compat_cisternal` (`redsox/cli/main.py:16`). That shim exports no `wire` (`compat_cisternal.py:13-17`), and its fallback `tool` accepts only `registry` and `name` (`compat_cisternal.py:35-41`), so it does not forward the new keywords. The example below assumes a direct `import cisternal`, or a shim extended to export `wire` and forward `cli_name`/`cli_contract`.

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
# consumer-provided (stubbed by the T6 prelude): load_config
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
# Unmapped exceptions keep the F1 line and exit 1; redsox has no ConfigError (A15).

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

The module path `redsox.config` stands in for wherever redsox keeps `load_config`. redsox's `main.py` uses `from __future__ import annotations` (`main.py:3`). That makes `ConfigOption` and the `out` annotation strings, and they name `Annotated`, `Path` and `Parameter`, which `wired.py` does not import. Today they would raise `NameError` at `wire()` time (A9). With the A9 fix they resolve against redsox's globals, so this example also demonstrates the fix.

Telemetry: today `derive_seams_cmd` wraps its body in `cisternal.span("redsox.cli.derive_seams")` (`main.py:94`). After migration that span is replaced by the `cli.cmd_*` span that `wire()` opens with `cmd="derive_seams"` (A3), unless the tool body keeps an inner `cisternal.span("redsox.cli.derive_seams")`.

### 6.7 alphex: all five commands, table or `--json-out`

Every contract lives in `alphex/cli.py`. `alphex/mcp.py` keeps only plain `@cisternal.tool(...)` decorators (with `cli_name=` where the CLI name differs) and its existing `wire(app, registry="alphex")` in the `mcp_server()` entry point (`mcp.py:118`). `cli.py` imports `alphex.mcp` to register the tools, and `mcp.py` never imports `cli.py`, so there is no import cycle. This follows the two-entry-point recipe (§8 item 3).

```python
# alphex/mcp.py: only cli_name additions; no contracts, no import of alphex.cli
# (docstrings and the FastMCP setup of mcp.py:20-36 omitted)
from typing import Any
import cisternal
from alphex import _surface                            # consumer-provided (stubbed by the T6 prelude)

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

```python
# alphex/cli.py
import json
import sys
from typing import Any

from cyclopts import App

import cisternal
from cisternal import CliContext, CliContract, CliOption, json_option
import alphex.mcp                                       # registers the "alphex" tools; no wire(mcp) at import
from alphex._render import _render                     # consumer-provided (stubbed by the T6 prelude)

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
        sys.exit(1)                                     # works under any result_action (A19)

CONTRACTS = {
    "list_alphabets": CliContract(format_success=_list_fmt),
    "lint": CliContract(format_success=_lint_fmt,
                        options=[CliOption("strict", bool, False, help="Exit 1 on any finding.")]),
    # Optional: keep today's CLI --help text instead of mcp.py's docstring:
    "perm": CliContract(help="Build the permutation table from `src` to `dst`. ..."),   # cli.py:84-88 text
}

cisternal.wire(None, cli_app, registry="alphex",
               cli_contract=CliContract(options=[json_option("--json-out")], format_success=_emit_fmt),
               cli_contracts=CONTRACTS)
# Each tool's options merge as (*W.options, *T.options): lint gets --json-out and --strict.
# The CLI names list/show/relation/perm/lint and the flag --json-out match today's cli.py:57-116.
# The MCP tool names and signatures are unchanged (e.g. list_alphabets() -> list[dict]).
```

`alphex._render` stands in for wherever alphex keeps `_render`. Consumer-side precondition: after migration `alphex.cli` imports `alphex.mcp`, so the CLI needs the `mcp` extra (cisternal + fastmcp, Python ≥3.13; `mcp.py:20-35`). alphex's stated CLI policy is that the CLI works on Python >=3.11 without cisternal or fastmcp (`alphex/pyproject.toml:14, 62-70`), so that policy excludes this migration unless alphex drops it. The example still shows the pattern for consumers without that constraint.

Output differences from today's hand-written CLI, all accepted:

- `json_option` sets `negative=""`, so the implicit `--no-json-out` goes away. The flag defaults to False.
- `perm` with an invalid policy: today the CLI raises `SystemExit(msg)` (`cli.py:90-91`), which prints `msg` to stderr and exits 1. After migration the tool raises `ValueError(msg)` (`mcp.py:90-92`), which prints `Error (ValueError): msg` to stderr and also exits 1.
- `perm` gains a positional `policy`. Today's CLI declares `*, policy` (`cli.py:83`), while the tool's `policy` is positional-or-keyword (`mcp.py:73`), so `alphex perm a b mask` now parses. `--policy` still works. The alternative is to declare `*, policy` on the tool; MCP callers pass arguments by name, so that is safe for MCP but changes the Python signature.
- `--help` text comes from the `mcp.py` docstrings (A14) for every command that has no `CliContract.help`. The `perm` entry above shows the per-command override.
- `list`, `show`, `relation`, `lint` (incl. `--strict`) and all `--json-out` output are byte-identical, given that the tool bodies return the same `_surface` values (`mcp.py:43,54,70,94,104`).

### 6.8 maraxiom-style rich command with a prompt and `--working-dir`

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
from myxcel import MyxcelError                            # real class with per-subclass exit_code (A21)
from maraxiom.mcp_server import mcp                       # consumer-provided (stubbed by the T6 prelude)

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
    Console().print(t)                                    # print, return None (§5.2)

@cisternal.tool(registry="maraxiom", name="new_presentation", cli_name="new",
    cli_contract=CliContract(prepare=_prepare, format_success=_table,
                    options=[json_option(),
                             CliOption("working_dir", Path | None, None,
                                       help="Run as if started in this directory "
                                            "(relative path arguments resolve against the original cwd).")]))
def new_presentation(title: str | None = None, audience: str = "lab",
                     out: Path = Path("deck")) -> dict: ...

cisternal.wire(mcp, app, registry="maraxiom",
               cli_contract=CliContract(exit_codes={MyxcelError: exit_code_attr(report=_myxcel_report)}))
# A ConfigError raised in the tool -> "[red]Error:[/red] <msg>" on stderr, exit 2 (MRO -> MyxcelError handler).
# Omit report= to get the F1 line instead.
# The T contract's options list is normalised to a tuple and merges over W without error.
```

The tool's own body must not prompt. The MCP path never runs `prepare`. The prompt is untimed (§5.2).

The `exit_code_attr` mapping applies only when the tool body *raises* a `MyxcelError`. myxcel's own tool bodies do not work this way out of the box: they catch every exception and return `_tool_error(e)` (`myxcel/mcp_server.py:111-136`), so they exit 0. A body like that must raise, or put an exit code in its envelope for a §6.10-style formatter (§8 item 5).

### 6.9 contemplex: raised `ContemplexError` → rich Panel + code lookup

contemplex raises `ContemplexError` with a `StrEnum` code (`errors.py:6-22`). `exit_code_attr` covers int attributes only, so the mapping is a handler with a lookup table: the real `_EXIT_CODES` from `cli.py:43-52`. The handler renders the same Panel as `_render_error` (`cli.py:73-84`) and returns the code instead of raising `typer.Exit`. A fallback handler on `Exception` mirrors `_handle_exc`'s non-contemplex branch (`cli.py:89-90`): an `INTERNAL` panel and exit 1.

The recipe requires `@cisternal.tool` to decorate the raw raising tool body, not contemplex's error-shaping `traced_tool` wrapper (`contemplex/telemetry_bridge.py:65-87`, which returns `err_envelope(...)` instead of raising). `wire()` then exposes that raw body on MCP too, so the MCP error shape changes from `err_envelope` dicts to FastMCP errors. That change is the consumer's decision (§8 item 5).

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

### 6.10 Generic result-envelope formatter

This recipe is for a tool that *returns* a flat envelope instead of raising: `{"ok": True, **payload}` on success, and `{"ok": False, "error_code": ..., "error": ..., **context}` on failure. That is the shape of `ok_envelope`/`err_envelope` in `contemplex/errors.py:75-80`. contemplex's tool bodies raise (§6.9); its MCP wrappers (`traced_tool`, `contemplex/telemetry_bridge.py:65-87`) are what return this envelope. The code table belongs to the consumer.

```python
import json
import sys
from typing import Any

from cisternal import CliContext

_CODE_TO_EXIT: dict[str, int] = {"NOT_FOUND": 3, "INVALID_INPUT": 2}   # consumer-defined

def _envelope(result: dict[str, Any], ctx: CliContext) -> None:
    if result.get("ok") is False:
        print(f"Error ({result['error_code']}): {result['error']}", file=sys.stderr)
        sys.exit(_CODE_TO_EXIT.get(result["error_code"], 1))   # works under any result_action (A19)
    print(json.dumps({k: v for k, v in result.items() if k != "ok"}, indent=2))
```

## 7. Orchestration / composite commands: no DSL

A declarative pipeline (`steps=[...]`) is a non-goal. Real composites interleave control flow that a DSL would have to grow into a language: redsox `audit` re-execs under a target interpreter (`main.py:399-420`), and bathos `submit` has 12 conditional stages. That control flow is ordinary Python.

The recommended pattern for a **CLI-only** composite is a plain function registered with `cli_command`, so it shares F1, the contract and telemetry. It calls the **tool functions**, which `@tool` leaves unchanged (`decorator.py:99-110`), and not their CLI callables, which `sys.exit`.

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

**Async sub-tools.** A composite over `async def` tools must itself be `async def` and `await` each tool. It must never call `asyncio.run` per tool: the CLI path already runs the composite under one `asyncio.run` (A5), and a nested `asyncio.run` raises inside a running loop. A sub-tool exception propagates out of the awaited call into F1 and maps through `exit_codes` exactly like a sync one (test 37).

```python
from cyclopts import App

import cisternal
from cisternal import CliContract
from alphex.mcp import alphex_lint, alphex_list_alphabets   # the §6.7 tools

app = App(name="alphex")

async def audit_all() -> dict:
    alphabets = await alphex_list_alphabets()
    findings = await alphex_lint()
    return {"alphabets": len(alphabets), "findings": findings}

app.command(name="audit-all")(cisternal.cli_command(audit_all, contract=CliContract()))
```

**Placement and registration.**

- **CLI and MCP.** A composite that should be both an MCP tool and a CLI command is declared only with `@cisternal.tool(cli_contract=...)` (or a `cli_contracts` entry), and `wire()` mounts it.
- **CLI only.** Hand registration through `cli_command()` is for composites that are CLI-only. Never combine the two on the same name, i.e. a `@cisternal.tool` that `wire()` mounts *and* a hand `cli_command()` registration, unless that tool is wired with `app=None`.
- A bare `app.command(...)(cli_command(...))` registration is **not** recorded in `WiredRegistry.cli_commands`, because no `wire()` call saw it. It gets no `CliContract.help`/`show` forwarding; pass `help=`/`show=` to `app.command` directly.
- To put a CLI-only composite into a group that `wire()` populates, at any depth, register it on `cisternal.cli_group(app, "<group path>")`. That returns the same sub-App object (§5.6).
- Use plain cyclopts with no cisternal involvement only for commands that are pure CLI plumbing (`--version`, shell completion, interactive TUIs).

## 8. Docs

`docs/guides/wire-onboarding.md` is a public guide, linked from README §wire. It has seven parts.

1. **Why.** A single function becomes an MCP tool, a CLI command, telemetry and recovery, so no parallel CLI is needed. Cite the alphex/redsox duplication as an example of the pattern. alphex keeps its parallel CLI deliberately, for its cisternal-free Python >=3.11 CLI policy (`alphex/pyproject.toml:14, 62-70`), so the guide does not present it as something `wire()` removes.
2. **Rules for tool bodies.**
   - Return data and raise domain exceptions.
   - Never print or prompt (MCP has no TTY).
   - Never print a banner to stdout from a tool body (see the banner recipe).
3. **`CliContract` recipes.**
   - The exit map, including `exit_code_attr()`, `exit_code_attr(report=...)` with myxcel's `[red]Error:[/red] {e}` report (§6.8), `default_report`, and the meaning of a handler that returns `None`. **`exit_code_attr` covers int-valued attributes only.** String or enum codes need a handler with a lookup table, as in the contemplex recipe (§6.9: a `{ContemplexError: handler}` that renders a Panel and returns `_EXIT_CODES.get(exc.code.value, 1)`, plus an `Exception` fallback to `INTERNAL`/1).
   - The `--json` formatter, and `CliOption(help=...)` for option help text.
   - `CliContract.help` / `CliContract.show` for per-command help text and hidden commands. There are no aliases (N9).
   - Prepare-prompt.
   - The generic result-envelope recipe (§6.10: `sys.exit(code)` from the formatter, flat `ok` envelope with `error_code`/`error`).
   - Groups via `cli_group_help` / `cli_group()`, including nested paths (`"flow visuals"`), per-level help, and the rules that an unknown `cli_group_help` key and a conflicting second help both raise.
   - The precedence table, including `cli_contracts` (T level; it conflicts with a decorator contract on the same tool).
   - **Two entry points.** The tools and their `@cisternal.tool(...)` decorators live in one module, and nothing there imports the CLI module. The CLI module imports it, keeps every contract in a `cli_contracts` map, and calls `wire(None, cli_app, registry=..., cli_contract=..., cli_contracts=...)`. The MCP entry point calls `wire(mcp, registry=...)` inside its own `main()`. This avoids a tool-module ↔ CLI-module import cycle (§6.7).
   - **Hidden or context-derived argument.** The recommended form is a required keyword-only parameter with no default, `*, token: Annotated[T, Parameter(parse=False)]`. It keeps the MCP parameter required. cyclopts does not accept the flag (A26), and `prepare` fills the value through `ctx.arguments[...]`, from the environment, the cwd, a detected worktree and so on. Until `prepare` sets it, the key is absent from `ctx.arguments`; if `prepare` leaves it unset, `_rebind` fails with `TypeError` before the span (§5.2). `Annotated[T, Parameter(parse=False)] = default` also works, but then MCP callers see the parameter as optional (R6). The MCP schema lists the parameter in both forms, and MCP callers pass it explicitly.
   - **Mid-command confirm.** Split the work into a preflight tool that returns what would happen, and a tool gated on `yes: bool = False` that refuses to act unless `yes`. Chain them with a `cli_command` composite (§7) that calls the preflight, prompts (`rich.prompt.Confirm`), then calls the gated tool with `yes=True`. MCP clients call the two tools themselves.
   - **Banner.** Emit it from `prepare` or the formatter, or through `logging` to stderr. Never `print` it to stdout in a tool body: that would corrupt `--json` output and MCP stdio.
4. **Composite commands** via `cli_command` (§7). Covers the `cli_commands` / `cli_group()` note, the rule that CLI-and-MCP composites use `@cisternal.tool(cli_contract=...)` while `cli_command()` is for CLI-only ones, and the async rule: an `async def` composite that awaits each tool, never `asyncio.run` per tool.
5. **Gotchas.**
   - An `int` or `bool` return becomes the exit code under cyclopts' default action only. A callable `result_action` swallows it, so use `sys.exit` (A6, A19).
   - Formatters should print and return `None`, because a returned renderable is printed after the telemetry span closes.
   - With `recovery`, `to_result()` turns failures into successes.
   - Telemetry `cmd` is the MCP name.
   - `prepare` is never timed, and a crash or exit in `prepare` emits no `cli.cmd_*` event. A `prepare` that sets an unknown argument, removes a required one, or removes a positional argument ahead of a later positional-only or `*args` value fails with `TypeError` before the span.
   - `prepare` sees every argument in `ctx.arguments`, including defaults. When it `chdir`s, it must resolve relative `Path` arguments against the original cwd *before* calling `os.chdir`.
   - Exit handlers may receive `ctx.arguments == {}` when binding failed.
   - With `_cisternal_timed` tools, the formatter is also untimed.
   - **A tool body that catches its exceptions and returns an error envelope exits 0** under the default `result_action`: nothing raises, so `exit_codes` never runs. The same holds for **a tool wrapped by an error-shaping `traced_tool`**, which catches and returns an envelope around an otherwise raising body. Current cases:
     - myxcel's tools end in `except Exception as e: return _tool_error(e)`, and `_tool_error` returns `{"error", "message"}` with no exit code (`myxcel/mcp_server.py:111-136`);
     - maraxiom's flow tools discard the int code their helpers return (`result, _code = ...; return result`, `maraxiom/mcp_server.py:1152-1153`; `FlowError.exit_code` at `maraxiom/flow/errors.py:23`);
     - `traced_tool` wrappers: contemplex (`contemplex/telemetry_bridge.py:65-87`), bathos (`bathos/mcp.py:108`), myxcel (`myxcel/telemetry_bridge.py:102`, under its cisternal cutover) and cisternal's own CH-5 `traced_tool` (`adapters/v2_decorator.py:32`, returning `adapter.shape_error(...)` at `:75` and `:100`). After the cisternal `traced_tool` cutover, `ContemplexAdapter.shape_error` always yields `INTERNAL` (`adapters/base.py:334-346`), so an envelope formatter cannot recover contemplex's exit codes 2-6.

     Such a body must either raise (for a wrapped tool: decorate the raw body with `@cisternal.tool`, §6.9), which changes the MCP error shape (the consumer's decision), or carry an exit code in the envelope for a §6.10-style formatter to read and `sys.exit` with.
   - A `CisternalWireError` from `wire()` leaves the server and the App untouched, so a failed `wire()` can be fixed and retried.
   - Tool modules may use `from __future__ import annotations`: parameter annotations resolve against the tool module's globals, also through `functools.wraps` decorators (verified on CPython 3.13). A return type imported only under `TYPE_CHECKING` is fine. **The bathos workaround is deletable:** mutating `__annotations__` after the `def` (`bathos/mcp.py:313-325, 1929-1945`) still works, but is no longer needed.
   - cyclopts does not detect two parameters that claim the same flag (A24). The contract builder checks option-vs-tool collisions only. `cli_command()` cannot see an App's `default_parameter` (R8).
6. **When to drop to plain cyclopts.**
7. **A migration checklist for typer CLIs** (#2387–#2390), with this translation table:

   | typer | cyclopts / cisternal |
   |---|---|
   | `typer.Argument(...)` | Positional parameter. Use `Annotated[T, Parameter(...)]` for help and metavar |
   | `typer.Option(...)` | Keyword parameter (keyword-only for flag-only). Use `Annotated[T, Parameter(help=...)]` |
   | Aliases and renames (`typer.Option("--from", "-f")`) | `Annotated[T, Parameter(name=["--from", "-f"])]` on the tool parameter. The Python identifier, and therefore the MCP property name, is unchanged |
   | `help=` on Argument/Option | `Parameter(help=...)`, or the docstring's parameter section. For a CLI-only option, `CliOption(help=...)` |
   | `help=` / `hidden=True` on `@app.command` | `CliContract(help=...)` / `CliContract(show=False)` |
   | `@app.callback()` global options | `app.meta` (cyclopts meta-app), recipe below. Not a `CliContract` feature: `CliContract.options` are per-command only (N8) |
   | `--version` callback | `App(version=...)` |
   | `invoke_without_command=True` | `@app.default` |
   | Nested `typer.Typer()` sub-apps (`app.add_typer(visuals, name="visuals")` under `flow`) | `cli_group="flow visuals"` on the tool, or `cisternal.cli_group(app, "flow visuals")` |
   | `typer.prompt` when an option is missing | A `prepare` hook writing `ctx.arguments[...]`. The parameter defaults to `None` (R6) |
   | Hidden or context-derived option (`hidden=True`, `ctx.obj`-derived value) | `*, name: Annotated[T, Parameter(parse=False)]` (required keyword-only, recommended) or `... = default`, filled by `prepare` through `ctx.arguments` |
   | `typer.confirm` mid-command | A preflight tool plus a `yes`-gated tool, chained by a `cli_command` composite that prompts between them |
   | `typer.echo` banner at command start | Emitted from `prepare`/the formatter, or `logging` to stderr; never `print` to stdout in a tool body |
   | `typer.Exit(code)` / `raise SystemExit` | Unchanged passthrough. Prefer a domain exception plus an `exit_codes` entry |

   **Global options via `app.meta`.** This replaces `@app.callback()`:

   ```python
   import logging
   from typing import Annotated

   from cyclopts import App, Parameter

   app = App(name="mytool")
   # ... cisternal.wire(mcp, app, registry=...) ...

   def _setup_logging(verbose: bool) -> None:
       logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)

   @app.meta.default
   def main(*tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
            verbose: bool = False):
       _setup_logging(verbose)
       return app(tokens)        # nested call returns the command's value (A16)

   if __name__ == "__main__":
       app.meta()                # launch through the meta-app, not app()
   ```

   The inner `app(tokens)` returns the command's value, and the outer `app.meta()` applies `result_action` once (A16, verified for this returned-value form only). A global value reaches `prepare` or a formatter only through state the consumer owns, such as a module variable or a contextvar set in `main`. It is never put into `CliContext` (N8).

Also: docstring updates in `wired.py` (the `app` argument is no longer a "pure passthrough" when a contract is given) and a CHANGELOG entry.

## 9. Back-compat

- **Default path.** With `cli_contract=None`, `cli_contracts=None` and no `@tool(cli_contract=...)`, `wire()` emits today's closure (`wired.py:282-319`). It is still defined in `wired.py`, now at module scope (T0b hoist), so its `__globals__` are unchanged. `recovery` and `cli_telemetry` are passed as arguments instead of being closed over, with the same values. `app.command` still receives only `name=`. The single behaviour change is line 318: `__annotations__` holds the per-parameter hints resolved by `_resolve_cli_hints(strict=False)` instead of the raw copy. `__signature__`, `__name__` and `__doc__` are unchanged.
  - **Any tool that registers today** registers after the change. cyclopts already resolved its annotations successfully against `wired.py`'s globals, and the resolver's globals are a superset (tests 9b and 24).
  - **Any tool that fails today** either falls back to the raw copy (`return` key included) and fails the same way in cyclopts, or now registers because its parameter names resolve in its own module, or because only its return annotation was unresolvable (A9; tests 9 and 9d).
  - **`return` is no longer in the CLI callable's `__annotations__`** when resolution succeeds. cyclopts reads only parameter names (A8), and `__signature__` still carries it. Test 25's signature literal and test 24 guard this.
  - **The one semantic difference:** if a tool module binds a name to a *different* object than `wired.py` does, it now resolves to the tool module's binding. No current consumer does this; tests 24 and 25 guard the observable output.
  - **bathos' post-def mutation of `__annotations__`** stores real objects, which pass through unchanged (test 9c).
- **Pre-pass ordering.** The pre-pass (§5.1) moves CLI-callable construction ahead of the first `add_tool`. On the no-contract path no step of it can raise a new error (`_make_cli_cmd` falls back instead of raising, and single-segment group probing raises only in the cases listed under Groups below), so the order and content of registrations are unchanged (tests 24, 25). The one exception is the planned-name check (§5.1): a command/group clash or a duplicate leaf within one call, or a flat or leaf name already present at its existing target level, which today raises `CommandCollisionError` partway through registration, now raises `CisternalWireError` before anything is registered.
- **Invariants.** These are unchanged: the F1 stderr bytes, exit 1, `SystemExit` passthrough, signature equality, telemetry ordering and payloads, and `WiredRegistry` contents. Test 25 pins all of them against literals captured at `8730da8` (T0a): `cli.cmd_*` payloads, `cli_commands`, the registered signature string, and async and recovery stdout/exit.
- **Groups.** Today, wiring into a group name the consumer has already mounted raises `CommandCollisionError` at `wire()` time (A20d/e); it does not produce a duplicate mount. After this change:
  - a user-constructed App at that name is adopted;
  - a function command at that name raises `CisternalWireError` instead of `CommandCollisionError`, before anything is registered.

  No current consumer hits either case: bathos, alynxr and naurmalade let `wire()` create their groups. Whitespace in a `cli_group` string now separates path segments; no consumer uses it (A27). Single-segment group strings behave exactly as today.
- **Unchanged callers.** These pass no new arguments, so their behaviour is unchanged:
  - bathos (`cli_cyclopts.py:52`, App `result_action`);
  - alynxr (`cli.py:21`, `mcp.py:16`);
  - naurmalade (`cyclopts_cli.py:122-135`, App-level `result_action=render_envelope` over `wire(None, app=app, ...)`);
  - alphex (`mcp.py:118`, MCP-only);
  - maraxiom (`mcp_server.py:2891`, MCP-only);
  - redsox.
- **`ToolEntry`** gains a defaulted trailing field (A10), and its `cli_group` type widens to `str | tuple[str, ...] | None`.

## 10. MCP side unchanged

`compose_mcp_callable` and the `Tool.from_function(..., name=entry.name)` path (`wired.py:238-257`) never read `cli_contract`, `cli_contracts` or the resolved CLI hints. C5 holds. Options, `prepare`, formatters, handlers, `help` and `show` exist only on the CLI side. A `Parameter(parse=False)` parameter remains an ordinary MCP parameter (test 34). The `cli_contracts` key validation reads only registry names and does not touch the MCP registration. The only MCP-visible effect of the pre-pass is that a wire-time `CisternalWireError` now prevents *all* MCP registrations of that call, instead of leaving a partially populated server.

## 11. Test plan

New files:
- tests: `tests/test_registration_cli_contract.py`, `tests/test_registration_golden.py` (T0a), `tests/test_docs_examples.py` (T6);
- fixtures: `tests/fixtures/future_annot_tools.py` (it includes a tool whose return type is imported only under `TYPE_CHECKING`), `tests/fixtures/typecheck_any_tools.py`, `tests/fixtures/bathos_style_tools.py`, `tests/fixtures/wrapped_future_tools.py` and `tests/fixtures/docs_prelude.py` (T6).

Tests use `app([...], exit_on_error=False)` and capture stderr, as in `test_registration_telem.py:343-347`.

**Positive controls**

1. A mapped exception with an int value (`{ValueError: 3}`) → exit 3, and stderr is exactly `Error (ValueError): msg\n`.
2. A handler value → the handler's output, its returned code, and no F1 line.
3. MRO specificity:
   - **3a** (pure unit, no wire): `m = CliContract(exit_codes={MyxcelError-like: 9}).merged_over(CliContract(exit_codes={ConfigError-like: 2})).exit_codes`, then `_resolve_exit(exc, CliContext("t", "t"), m)`. `ConfigError` → 2; a sibling subclass → 9.
   - **3b** (wired): the same, with W passed to `wire(cli_contract=)` and T passed to `@tool(cli_contract=)`, invoked through the App.
4. CLI-only options:
   - `json_option()` → the formatter sees `ctx.options["json_out"] is True`.
   - The tool receives no `json_out` kwarg. It has a strict signature with no `**kwargs`, so a leak would raise `TypeError`.
   - **`**kwargs` tool.** A tool `t(a: int, **extra)` with `json_option()` builds. In `inspect.signature(cmd)`, `json_out` comes before `extra` (§5.4). `--json` sets `ctx.options["json_out"]` and does not appear in `ctx.arguments["extra"]`; an unknown `--foo` still reaches `extra`.
   - `app(["<cmd>", "--help"])` output contains the `json_option` help text, and the `help=` text of a `CliOption("working_dir", Path | None, None, help="Run as if started in this directory ...")`.
5. A formatter returning `None` → exit 0, and stdout equals the formatter's output only.
6. `prepare` fills a missing argument. Tool: `f(title: str | None = None, audience: str = "lab")`. `prepare` sets `ctx.arguments["title"]` from a monkeypatched prompt when it is None. Each variant asserts no `TypeError` and the exact values the tool receives:
   - **6a** `--title x` → the prompt is not called; the tool gets `("x", "lab")`.
   - **6b** only `--audience z` → the prompt is called; the tool gets `(<prompted>, "z")`.
   - **6c** no arguments → the prompt is called; the tool gets `(<prompted>, "lab")`.
   - Also: a tool with a positional-only parameter, `*rest` and `**extra` round-trips through `ctx.arguments` and `_rebind` unchanged.
   - Also: a `prepare` that deletes a defaulted positional-or-keyword `a` of `f(a=1, b=2)` while `b` is present → the tool gets `a=1` (default) and `b` by keyword.
7. A grouped tool with a contract → reachable at `app[g][n]`, and `ctx.command == "g n"`.
8. `cli_command()` on a composite: a sub-tool exception maps via the contract.
9. A9, positive: the fixture `future_annot_tools.py` uses `from __future__ import annotations` and `Annotated[Path, Parameter(...)]`. It also has a tool whose return annotation names a type imported only under `TYPE_CHECKING`. Two variants: a **no-contract** variant (T0b) and a **contract** variant (T4).
   - Both tools register and parse through `wire()`.
   - Every value in the registered CLI callable's `__annotations__` is a resolved object, not a `str`. For example, `__annotations__["p"]` is `Annotated[Path, Parameter(...)]` by `==`.
   - `"return" not in registered.__annotations__`.
   - `inspect.signature(registered)` still equals `inspect.signature(original)`, return annotation included.
   - **9b** The fixture `typecheck_any_tools.py` uses `from __future__ import annotations` and imports `Any` only under `if TYPE_CHECKING:`. It registers and parses through `wire()` both at `8730da8`, where the recorded outcome is pinned as a literal in T0a, and after the change.
   - **9c** The fixture `bathos_style_tools.py` uses `from __future__ import annotations` and mutates `fn.__annotations__["x"] = Annotated[int, Parameter(name=["--x", "-n"])]` after the `def`. It registers both before and after the change, and `-n 3` reaches the tool as `3`.
   - **9d** The fixture `wrapped_future_tools.py` uses `from __future__ import annotations` and has a tool decorated with `@timed_command(...)` and annotated with `Path`, a name that `adapters/cli.py` does not import. It registers and parses on both paths: no contract (T0b) and contract (T4). Its `__annotations__["p"] is Path`. A unit case also covers the empty-`__annotations__` fallback: a wrapper with `__annotations__ = {}` and `__wrapped__` set resolves from the unwrapped function.
10. An async tool with a contract → the formatter receives the awaited result.
11. Recovery with `to_result()` → the formatter receives the `to_result` value.
26. `{MyxcelError: exit_code_attr()}`:
    - A subclass with `exit_code = 4` → stderr is exactly the F1 line, and exit is 4.
    - A subclass with `exit_code = 0`, `300`, `True`, `"SESSION_NOT_FOUND"` (a string code) or no attribute → the F1 line, and exit `default` (1).
    - **Custom report:** `exit_code_attr(report=r)` with `r` printing `[red]Error:[/red] {e}` through a no-colour `rich` Console to stderr → stderr is exactly `Error: <msg>\n` with no F1 line, and exit is the subclass code. `exit_code_attr(report=None)` raises `TypeError`.
27. A handler returning `None` → stderr is exactly the F1 line, and exit is 1.
28. Envelope: a formatter that calls `sys.exit(5)` on an error-shaped result under a default `App()` → exit 5. Telemetry `cli.cmd_end` has `ok=False` and `exit_code=5`.
29. The same as 28 under `App(result_action=<dict-only callable>)` → exit 5, with the same telemetry. Control: a formatter *returning* `5` under that App exits 0, which documents A19.
30. Pre-mounted group:
    - **Positive:** `app.command(App(name="jobs", help="Job ops"))`, then `wire()` with a tool where `cli_group="jobs"` → `app["jobs"]` is the original object, its help is still `"Job ops"`, and both the pre-existing command and the wired one are reachable. With `cli_group_help={"jobs": "other"}` the adopted help is still `"Job ops"`.
    - **Negative control:** a pre-registered *function* command `@app.command def jobs(): ...`, plus a tool with `cli_group="jobs"` → `wire()` raises `CisternalWireError` whose message names `jobs`. Nothing is registered (asserted in test 35).
    - **Leaf clash in an adopted group (negative):** a pre-mounted `App(name="jobs")` that already has a command `submit`, plus a tool with `cli_group="jobs"` and `cli_name="submit"` → `wire()` raises `CisternalWireError` naming `submit` (§5.1). The server lists no tools from the call, and `app` and the adopted `jobs` App have the same command sets as before the call.
    - **Legacy record (T0a only):** at `8730da8`, T0a runs the positive setup, checks that it raises `CommandCollisionError`, and records that type in the golden file. The check is computed, and can fail, only in T0a. After the change the literal is a record of the behaviour change and is not asserted by test 25 or test 30.
31. `wire(cli_group_help={"g": "Group help"})` → the created sub-App's help is `"Group help"`.
    - **Unknown key (negative):** `wire(cli_group_help={"nope": "x"})`, where no entry's normalised group path starts with `("nope",)` → `CisternalWireError` naming `nope`, and nothing is registered on the server or the App. A key that is a strict prefix (`{"flow": ...}` for an entry in `"flow visuals"`) does not raise.
32. `cisternal.cli_group(app, "g")` returns the same object `wire()` used (`is`), whether it is called before or after `wire()`. A command registered on it is reachable at `app["g"]`.
    - **Help in both call orders.** `cli_group(app, "g", help="H")` called *before* a `wire()` that creates no help for `g` → `app["g"].help == "H"`. Called *after* such a `wire()` → `app["g"].help == "H"` as well, and the root `--help` lists `g` with `H`.
    - Calling `cli_group(app, "g", help="H")` again is a no-op. `cli_group(app, "g", help="other")` afterwards → `CisternalWireError`. A `wire(cli_group_help={"g": "other"})` after `cli_group(app, "g", help="H")` → `CisternalWireError` from the pre-pass, with nothing registered.
33. Nested groups:
    - A tool with `cli_group="flow visuals"` and `cli_name="show"` → reachable at `app["flow"]["visuals"]["show"]`, with `ctx.command == "flow visuals show"` and `"flow visuals show" in wired.cli_commands`.
    - `cli_group(app, "flow visuals") is cli_group(cli_group(app, "flow"), "visuals") is cli_group(app, ("flow", "visuals"))`.
    - `wire(cli_group_help={"flow": "F", "flow visuals": "V"})` gives each level its help.
    - Adoption applies at the inner level: a pre-mounted `App(name="visuals", help="pre")` under a pre-mounted `flow` is adopted, and its help stays `"pre"`.
    - Negative: `cli_group(app, "flow  ")` is fine (whitespace-split), but `cli_group(app, ("flow", ""))`, `cli_group(app, "")` and `cli_group(app, ("a b",))` each raise `CisternalWireError`.
34. Hidden or context-derived argument. The tool is `f(name: str, token: Annotated[str | None, Parameter(parse=False)] = None)`, with a `prepare` that records `ctx.arguments["token"]` and then sets it to `"from-env"`.
    - `app(["f", "x", "--token", "t"])` raises cyclopts `UnknownOptionError`.
    - `app(["f", "x"])`: `prepare` sees `None`, and the tool receives `token == "from-env"`.
    - The FastMCP tool's parameter schema still lists `token`.
    - **Required variant.** The tool is `g(name: str, *, token: Annotated[str, Parameter(parse=False)])` (no default), with a `prepare` that records whether `"token" in ctx.arguments` and then sets it to `"from-env"`. `wire()` registers it without error; `app(["g", "x"])`: `prepare` sees the key absent, and the tool receives `token == "from-env"`; `app(["g", "x", "--token", "t"])` raises `UnknownOptionError`. With a `prepare` that does not set `token` → `Error (TypeError): prepare removed required argument 'token'`, exit 1, and no `cli.cmd_*` event. The FastMCP tool's parameter schema lists `token` as required.
35. `wire(cli_contracts=...)` and the untouched-on-failure guarantee:
    - **Map path (positive):** `wire(None, app, cli_contract=W, cli_contracts={"t": T})`, where tool `t` has no decorator contract → `t` behaves as with `@tool(cli_contract=T)`: T's formatter wins, and the options are `(*W.options, *T.options)`. A tool without a map entry gets W only.
    - **Conflict (negative):** a tool with `@tool(cli_contract=A)` plus `cli_contracts={"t": B}` → `CisternalWireError` naming `t`.
    - **Unknown key (negative):** `cli_contracts={"nope": C}` → `CisternalWireError` naming `nope`. The same holds with `app=None`.
    - **Planned-name clashes (negative):** in one `wire()` call, a flat tool with `cli_name="jobs"` followed by a tool with `cli_group="jobs"`, the same two in the reverse order, a flat tool with `cli_name="flow"` plus a tool with `cli_group="flow visuals"`, and two tools with the same `cli_name` in one group → each raises `CisternalWireError` naming the clashing name (§5.1).
    - **Name already on the root (negative):** a first `wire()` call registers a flat tool `t1` on `app`; a second `wire()` call on the same `app`, from another registry, has a flat tool whose `cli_name` is also `t1` → `CisternalWireError` naming `t1`. Assert that the second call's server lists no tools and that `app`'s command set equals the snapshot taken before the second call.
    - **Nothing registered.** Assert after the error that the FastMCP server lists no tools from the call, that `app` has no new commands or groups (its command set equals the snapshot taken before the call), and that `_CLI_SUBAPPS` has no new keys. The cases are:
      - the conflict case;
      - a 16a collision raised through `wire()` on the *second* of two entries;
      - the flat-`jobs`-then-`cli_group="jobs"` case and its reverse order;
      - the duplicate-leaf case.

      **T4g extension.** The assertion also requires that `_CLI_CREATED_HELP` has no new keys. It adds two cases: the test-30 function-command negative control, and the flat-`flow` plus `cli_group="flow visuals"` case.
36. `CliContract.help` / `show`:
    - `@tool(cli_contract=CliContract(help="Custom help"))` → `app(["t", "--help"])` shows `Custom help` and not the docstring.
    - **Docstring passthrough.** A contract with `help=None` on a tool whose docstring has a summary line and an `Args:` section → `app([cmd, "--help"])` shows the docstring summary and the `Args`-section description of one parameter. The contract callable's `__name__`/`__doc__` equal the tool's, and it has no `__wrapped__` attribute.
    - `CliContract(show=False)` → the command is absent from the root `--help` listing but still runs.
    - Merge: W `help="w"` with T `help=None` → `"w"`; T `help="t"` → `"t"`.
    - **Control:** a contract with `help=None, show=None`, and the no-contract path, call `app.command` with `name=` only. A spy on `App.command` records the kwargs.
    - Construction: `CliContract(help=3)` and `CliContract(show="no")` → `TypeError`.
    - **Collision derivation (negatives, through `wire()`):**
      - a tool parameter `f: Annotated[bool, Parameter(name="foo")] = False` plus an option claiming `--no-foo` → `CisternalWireError` (the normalised `--foo` wins in the combine chain, so its negative is `--no-foo`; §5.4);
      - an unannotated tool parameter `flag=False` plus an option claiming `--no-flag` → `CisternalWireError` (`type(default)` is `bool`; §5.4);
      - a tool parameter `x: Any = False` plus an option claiming `--no-x` → `CisternalWireError` (an `Any` hint with a non-`None` default derives as `type(default)`, as `_negatives_hint` does; §5.4).
37. Async composite through `cli_command`. An `async def` composite awaits two async tools; the second raises `MyErr`. Registered as `app.command(name="c")(cli_command(composite, contract=CliContract(exit_codes={MyErr: 4})))` → exit 4 and the F1 line. A success run returns the combined result to the formatter.

**Negative controls (must fail or raise)**

12. An unmapped exception → exit 1 with the F1 line. This guards against a mapping that matches everything.
    - **12b** A forced bind failure (calling the built contract CLI callable directly with an unexpected kwarg, `cmd(bogus=1)`) → stderr is the F1 line `Error (TypeError): ...` and exit is 1. With `{TypeError: handler}` mapped, the handler receives `ctx.arguments == {}`.
13. `SystemExit(4)` from the tool → passthrough 4, never remapped, even when `{Exception: 7}` is present.
14. `KeyboardInterrupt` is not caught by `{Exception: 7}`.
15. Each of these raises at construction:
    - `CliContract(exit_codes={SystemExit: 2})` → TypeError
    - `{ValueError: 300}` → ValueError
    - `{ValueError: "x"}` → TypeError
    - `{ValueError: True}` → TypeError
    - `{ValueError: 0}` → ValueError
    - `CliOption("x", "bool")` → TypeError (string annotation)
    - `CliOption("1x", bool)` → ValueError
    - `CliOption("class", bool)` → ValueError
    - `CliOption("x", ForwardRef("bool"))` → TypeError
    - `CliOption("x", Annotated[bool, Parameter(help="a")], help="b")` → ValueError
    - two options with the same name in one contract → ValueError
    - `merged_over` with a duplicate option name across self/base → ValueError

    Normalisation, which must not raise:
    - `CliContract(options=[json_option()]).options` is a `tuple`.
    - `exit_codes` is a `MappingProxyType` and does not alias the dict passed in: mutating the original afterwards does not change the contract.
    - `hash(CliContract())` raises `TypeError`.
    - `c.merged_over(None) is c` for a non-trivial contract `c`.
    - The §6.8 pair `T.merged_over(W)` succeeds, where W is `CliContract(exit_codes={MyxcelError-like: exit_code_attr()})` and T has a list of options. Its `options` is a tuple of the two T options.
16. Collisions raise `CisternalWireError`, and its message names the tool.
    - **16a**, in two halves: one through `cli_command()` (T3) and one through `wire()` (T4).
      - an option identifier equal to a tool parameter;
      - a tool with `json: bool` plus `json_option()` (flag collision on `--json`);
      - an option `CliOption("x2", Annotated[bool, Parameter(name="--no-x")], False)` against a bool tool parameter `x` (collides with the derived negative);
      - a tool parameter with an explicit `Parameter(name="--json")` plus `json_option()`;
      - a tool parameter with a user negative `Parameter(negative="off")` (normalised to `--off`) plus an option claiming `--off`;
      - a `list[str]` tool parameter `items` plus an option claiming `--empty-items`;
      - a bool option `CliOption("x2", bool, False)` plus a tool parameter `Annotated[bool, Parameter(name="--no-x2")]` (collides with the option's derived negative).

      A **16a variant** (`cli_command()` half, T3) builds every case above from a fixture module that uses `from __future__ import annotations`. The check runs on resolved hints, so the results are identical.

      **`wire()` half only** (A28), under `App(default_parameter=Parameter(negative=()))`. Neither of these raises:
      - a bool tool parameter `x` plus an option claiming `--no-x`;
      - a bool option `x2` plus a tool parameter claiming `--no-x2`.

      The same pairs raise through `cli_command()`, which documents R8.

      Controls that must *not* raise: an option named `json_out` on a tool whose `*args` is named `json` (the flag check skips `*args`); an option claiming `-j` when a tool parameter also uses `-j` (short flags are out of scope); a tool parameter `*, working_dir: Annotated[str, Parameter(parse=False)]` plus `CliOption("chdir_to", Annotated[Path | None, Parameter(name="--working-dir")], None)` (a `parse=False` parameter claims no flag, §5.4 item 2; the identifiers differ), which builds through `cli_command()` and wires through `wire()` without error.
    - **16b**, via `wire()`: a duplicate option name across W and T.
    - **16c** has two halves:
      - **Contract half (T3):** a future-annotations tool whose *parameter* annotation names an import that does not exist → `CisternalWireError` naming the tool and the parameter. A tool whose parameter annotation is the malformed string `"list[int"` → `CisternalWireError` naming the tool and the parameter (the `SyntaxError` is wrapped, not leaked). The `future_annot_tools.py` tool whose *return* type is imported only under `TYPE_CHECKING` does **not** raise on the contract path.
      - **No-contract half (T0b, alongside 18):** the unresolvable-parameter tool with no contract reproduces the legacy `NameError` from cyclopts. The `"list[int"` tool with no contract falls back to the raw copy (`_resolve_cli_hints(strict=False)` returns `dict(fn.__annotations__)` and does not raise), and registration then fails in cyclopts exactly as at `8730da8`.
17. A handler that raises → the F1 line, exit 1 and a logged WARNING. A handler returning `True` or `-1` → exit 1 and a WARNING.
18. Fixture-validity check only: the test-9 fixture registered through a closure that copies raw `__annotations__` (the `8730da8` line 318) reproduces `NameError`, for both the parameter-annotation tool and the `TYPE_CHECKING` return-type tool. This proves the fixture exercises A9; it is not a test of cisternal code.

**Telemetry**

19. A mapped failure → `cli.cmd_end exc_type` is the original type, not `SystemExit`.
20. A formatter crash (tool not `_cisternal_timed`) → `ok=False`, and `exc_type` is the formatter's exception.
    - **20b** `prepare`, `_rebind` and the span. Each failing case below must emit **zero** `cli.cmd_*` events:
      - A `prepare` that raises `RuntimeError` → the F1 line and exit 1.
      - A `prepare` that calls `sys.exit(3)` → exit 3.
      - A `prepare` that sets `ctx.arguments["bogus"] = 1` → `Error (TypeError): prepare set unknown argument 'bogus'` and exit 1.
      - A `prepare` that deletes a required, no-default argument → `Error (TypeError): prepare removed required argument '<name>'` and exit 1.
      - **Positional-only after a gap:** tool `f(a=1, b=2, /)`; a `prepare` that deletes `a` while `b` is present → `Error (TypeError): prepare removed argument 'a' ahead of 'b'` and exit 1.
      - **`*args` after a gap:** tool `f(a=1, *rest)` invoked with `rest` non-empty; a `prepare` that deletes `a` → `Error (TypeError): prepare removed argument 'a' ahead of 'rest'` and exit 1.
      - A `prepare` that succeeds appends a marker to a shared list before the span opens, and an adapter spy shows `cli.cmd_start` after the marker. That proves `prepare` is untimed.
21. `cli_telemetry=False` with a contract → no events.
22. A `_cisternal_timed` tool with a contract → exactly one `cli.cmd_start`/`cli.cmd_end` pair per invocation. When the formatter crashes in this branch, there is no `ok=False` event, and the failure is visible only as the F1 exit (stderr line, exit 1).

**MCP**

23. A tool with options and a contract (both decorator and `cli_contracts` forms) → the FastMCP tool's parameter schema equals the no-contract schema. The spy adapter still gets zero calls (reuses the `TestAdapterNotCalled` pattern).

**Preservation**

24. Every existing test passes unmodified in `test_registration_wire.py` (including the signature-equality test at `:550-567`), `test_registration_cli_telemetry.py`, `test_registration_recovery.py`, `test_registration_telem.py` and `test_mcp.py`.
25. Golden: the test asserts every T0a literal recorded at `8730da8` in `tests/test_registration_golden.py`, and never computes expected values at test time:
    - stderr, stdout and exit for one failing and one succeeding no-contract command;
    - the `cli.cmd_start`/`cli.cmd_end` event payloads for both, with the timing fields stripped (e.g. the duration);
    - `WiredRegistry.cli_commands` for one grouped and one flat tool;
    - `str(inspect.signature(registered))` of the registered CLI callable for a future-annotations tool that registers at `8730da8` (builtin annotations only);
    - stdout and exit for one async tool and for one `recovery` tool whose final failure has `to_result()`;
    - the 9b registration outcome.

    The test-30 legacy exception type is recorded in the same file but is verified only in T0a (test 30, legacy record); test 25 does not assert it.

Run narrowly (`uv run pytest tests/test_registration_*.py`), never the whole suite locally.

## 12. Fixer task decomposition

Order: T0a → T0b → T1 → T2 → T3 → T4 → T4g → T5 → T6 → T7. T0a and T0b can ship alone in the release cut.

**T0a. Golden capture.** Before any source edit, at `8730da8`, run and record as literals everything test 25 lists, plus the test-30 legacy record:
- one failing and one succeeding no-contract wired command: stderr, stdout and exit, plus their `cli.cmd_start`/`cli.cmd_end` payloads with the timing fields stripped;
- `cli_commands` for one grouped and one flat tool;
- `str(inspect.signature(...))` of the registered callable for a future-annotations tool that registers today;
- stdout and exit for one async tool and one recovery `to_result()` tool;
- the 9b fixture's registration outcome;
- the exception type raised by the test-30 pre-mounted-group setup.

Commit.
- **Files:** `tests/test_registration_golden.py`, `tests/fixtures/typecheck_any_tools.py`
- **Acceptance:** test 25 passes on unmodified `8730da8`. The test-30 legacy check, run at `8730da8`, computes the exception type the pre-mounted-group setup raises and confirms it is `CommandCollisionError`, which the golden file then records. This is the only place that literal is verified. The commit lands before any `src/` change (the order is visible in `git log`).

**T0b. Hoist and A9 fix.** Two commits in this order.
1. **Hoist (no behaviour change).** Move `_make_cli_cmd` verbatim from inside `wire()`'s entry loop (`wired.py:273`, under `if app is not None`) to module scope in `wired.py`, as `_make_cli_cmd(original_fn, cmd_name, *, recovery, telemetry)`. The free variables `recovery` and `cli_telemetry` become the parameters `recovery` and `telemetry`. The call site becomes `_make_cli_cmd(_fn, _name, recovery=recovery, telemetry=cli_telemetry)`. The T0a goldens (test 25) and test 24 guard the hoist and must pass on this commit alone.
2. **A9 fix.** Add `_resolve_cli_hints` per §4/§5.5: per-parameter resolution, `src = inspect.unwrap(fn)`, `globalns={**vars(wired_module), **getattr(src, "__globals__", {})}`, the empty-`__annotations__` `__wrapped__` fallback, `include_extras=True`, and a fallback on `NameError`/`AttributeError`/`TypeError`/`SyntaxError`. Replace line 318 with `_resolve_cli_hints(original_fn, strict=False)`. Keep `__signature__`, `__name__` and `__doc__` unchanged and add no `__wrapped__`.
- **Files:** `wired.py`, the full `_resolve_cli_hints` (§4) in the new `cli_contract.py`, the fixtures `future_annot_tools.py` (incl. the `TYPE_CHECKING` return-type tool), `bathos_style_tools.py` and `wrapped_future_tools.py`, new tests
- **Acceptance:** test 9 (no-contract variant only), 9b, 9c, 9d (no-contract half, incl. the fallback unit case), 16c (no-contract half), 18 and 25 pass on CPython 3.13. All existing registration tests pass unchanged (24), including `test_registration_wire.py:550-567`. **3.14 spike:** run test 9d once under CPython 3.14 (`uv run --python 3.14 pytest tests/test_registration_cli_contract.py -k 9d`); record the result in the PR. If no 3.14 interpreter is available, the PR states that the 3.14 wrapped case is unverified.

**T1. Contract types.** In `cli_contract.py`:
- `CliContext` (the §4 dataclass);
- `CliOption` (incl. `help` and its validation) and `CliContract` (incl. `help`/`show`), with `__post_init__` normalisation (tuple options, `MappingProxyType` exit codes, `__hash__ = None`) and validation;
- `json_option` defined over `CliOption.help`;
- `default_report`, `exit_code_attr(attr="exit_code", *, default=1, report=default_report)`, a pure `merged_over` producing `(*W.options, *T.options)` and merging `help`/`show` T-wins-if-not-None, with `merged_over(None)` returning `self`;
- `_resolve_exit(exc, ctx, exit_codes)` tolerating `arguments={}`.

The module scope imports only `registration.errors`.
- **Files:** `cli_contract.py`
- **Acceptance:** tests 3a and 15 (incl. the `merged_over(None)` case) pass, plus the construction and merge cases of 36. The module imports without fastmcp (`python -c` with `sys.modules["fastmcp"]=None`). `grep -n "^from\|^import" cli_contract.py` shows only stdlib, `__future__` and `cisternal.registration.errors`.

**T2. Registration plumbing.** Add `ToolEntry.cli_contract`, `register(cli_contract=)`, `tool(cli_contract=)` plus overloads, and widen the `cli_group` type.
- **Files:** `registry.py`, `decorator.py`
- **Acceptance:** a unit test shows that `@tool(cli_contract=c)` stores `c` on the `ToolEntry` (`entry.cli_contract is c`), and `decorated is fn` still holds. The A10 grep spike is done and recorded in the PR.

**T3. Builder.** Run the A23, A25 and A26 spikes first. Then implement `_build_cli_callable`:
- the no-contract branch delegates to `wired._make_cli_cmd`;
- the contract branch follows §5.2, with every step inside F1, `prepare` and `_rebind` before the span, and `ctx.arguments` bound and rebound (unknown-key, positional-after-gap and missing-required `TypeError`s);
- `__name__`/`__doc__` copied from `fn`, and no `__wrapped__`/`__qualname__`/`__module__`;
- option injection with `CliOption.help` wrapping, `strict=True` per-parameter hint resolution, and the long-flag collision check over resolved hints per §5.4, applying the same name and negative derivation (incl. the `_negatives_hint` rule) to tool parameters and options, skipping `parse=False` tool parameters, using `default_name_transform`, `get_negatives` and the `app_default_parameter` slot (always `None` from `cli_command`).

Add the public `cli_command` over it.
- **Files:** `cli_contract.py`, `wired.py`
- **Acceptance:** these `cli_command()`-level tests pass:
  - 1, 2, 4–6 (incl. 6a–6c), 8, 10–14 (incl. 12b);
  - the `cli_command()` half of 16a plus its variant, and the contract half of 16c;
  - 17, 19, 20, 20b (incl. both positional-after-gap cases), 22;
  - 26 (incl. custom report and the string-code case), 27–29 and 37.

  Tests 24 and 25 still pass. The spike results are recorded in the PR.

**T4. Wire integration.** In `wire()`:
- the pre-pass of §5.1, all before the first `add_tool`/`app.command`. It runs the `cli_contracts` checks (always), then, when `app is not None`, these steps:
  - effective-contract resolution;
  - the planned-name check, including the already-present check against the root and against single-segment groups found in `wired._CLI_SUBAPPS` (adopted levels are T4g's);
  - a read-only probe of each single-segment group against the existing `wired._CLI_SUBAPPS` and `app` (`wired.py:62`). It introduces no new symbol and mounts or caches nothing. Adoption and rejection are T4g's;
  - the `default_parameter` computation (run the A28 spike first) from the root App and, when the probe finds the group already exists, that sub-App;
  - construction of every CLI callable.
- `cli_contract=` merges through `merged_over`, and the W/T duplicate-option error is raised as `CisternalWireError`;
- `cli_contracts=` is applied at T precedence;
- `help=`/`show=` are forwarded to `app.command` only when set;
- `ctx.command` is set to the joined path.
- **Files:** `wired.py`
- **Acceptance:** these tests pass:
  - the contract variant of test 9, and the contract half of 9d;
  - the `wire()` half of 16a (incl. both `default_parameter` cases);
  - 21, 34, 35 (incl. the planned-name clashes that need no nested group, the name-already-on-the-root case, and the nothing-registered assertions for the conflict, 16a, `jobs`-clash and duplicate-leaf cases, checking `_CLI_SUBAPPS` only), 36 (incl. docstring passthrough and the collision-derivation negatives), 3b, 7, 16b and 23.

  Tests 24 and 25 still pass. The A28 spike result is recorded in the PR.

**T4g. Groups.** Assert the A20 discriminator and A29 as tests first: a user App has `default_command is None`, a function wrapper's `default_command` is the function, an unset `App.help` reads `""`, and a post-mount `help` assignment shows in the parent's `--help`. Then move `_CLI_SUBAPPS` and `_get_or_create_subapp` into `cli_contract.py`, adding `_CLI_CREATED_HELP`, path normalisation, a per-level walk keyed `(id(parent), segment)`, per-level adoption/rejection, per-level help (create, apply-if-unset, conflict), and `_probe_group_path`. `wired.py` imports them from there. Replace T4's single-segment probe in the pre-pass with `_probe_group_path`, and extend the `default_parameter` computation to every existing App the probe returns along a multi-level path (A28). Add `wire(cli_group_help=)` with path keys and the prefix check in the pre-pass, and the public `cli_group()`.
- **Files:** `cli_contract.py`, `wired.py`
- **Acceptance:** tests 30–33 pass (incl. the adopted-group leaf-clash negative of 30, the unknown-key negative of 31 and both call orders of 32). Test 35's T4g extension passes: the test-30 function-command case and the flat-`flow` plus `cli_group="flow visuals"` case, with the nothing-registered assertion now also requiring that `_CLI_CREATED_HELP` has no new keys. Tests 7 and 24 still pass. `wired._CLI_SUBAPPS is cli_contract._CLI_SUBAPPS`.

**T5. Exports, cycle checks and the cyclopts bound.** Export the §4 names eagerly from `registration/__init__.py` and `cisternal/__init__.py`, and set the cyclopts upper bound.
- **Files:** `registration/__init__.py`, `cisternal/__init__.py`, `pyproject.toml`, `uv.lock`
- **Acceptance:**
  1. `"CliContract"`, `"cli_group"`, `"exit_code_attr"` and `"default_report"` are in `dir(cisternal)`, and `test_registration_init` passes.
  2. `python -c 'import sys; sys.modules["fastmcp"]=None; import cisternal; cisternal.CliContract; cisternal.cli_group'` succeeds.
  3. In fresh interpreters, both import orders work with no `ImportError` or partially-initialised-module error: `import cisternal.adapters.cli; import cisternal` and `import cisternal; import cisternal.adapters.cli`.
  4. The PR records that `cli_group`, `_get_or_create_subapp` and `_CLI_SUBAPPS` were moved into the fastmcp-free `cli_contract.py`, and which names, if any, failed check 2 or 3 and were routed through `_lazy_import`/`__dir__`.
  5. `pyproject.toml` reads `cyclopts>=4.18.0,<5`, and `uv lock` has been refreshed. If the release owner declines the bound, the release notes explicitly flag it instead.

**T6. Docs.** The onboarding guide, the README link, the `wire` docstring and the CHANGELOG. The guide includes the §8 item 3 recipes (incl. two entry points, `exit_code_attr(report=)`, the int-only note with the contemplex lookup-table handler, and `help`/`show`), the item 4 async-composite rule, the item 5 gotchas with the bathos-workaround note, and the item 7 table with the `app.meta` recipe.
- **Files:** `docs/guides/wire-onboarding.md`, `README.md`, `wired.py`, `CHANGELOG.md`, `tests/test_docs_examples.py`, `tests/fixtures/docs_prelude.py`
- **Acceptance:** the guide contains the §6.6, §6.7, §6.8, §6.9 and §6.10 examples, the §7 async composite, the §8 hidden-argument and confirm recipes, and the §8 item 7 `app.meta` recipe. Of these, the §6.6–§6.10 examples, the §7 async composite and the `app.meta` recipe are executed in `tests/test_docs_examples.py`; the hidden-argument and confirm recipes are prose only and are not executed. The §6.7 `alphex/mcp.py` snippet runs as module `alphex.mcp` before `alphex/cli.py` and the §7 composite. Consumer imports are satisfied by a named stub prelude, `tests/fixtures/docs_prelude.py`, installed into `sys.modules` under the module paths each example imports. The prelude provides:
  - `load_config` (returning an object with `sibling_parity_governed` and `target_package` attributes), `enforce_no_sibling_parity_leak` (a no-op, under `redsox.core.guard`), `derive_seams`, `SeamExplosionError` (bare `Exception` subclass, per A15);
  - `_render`;
  - alphex tool stubs for `list_alphabets`, `show_alphabet`, `relation`, `perm` and `lint`: an `alphex._surface` stub whose `catalog`, `describe`, `classify`, `table` and `lint` return fixture data, plus `POLICIES`. Its `catalog` rows carry `name`, `size`, `offset`, `specials` and `warnings`, as `_list_fmt` reads them;
  - `MyxcelError` (`exit_code = 1`) and `ConfigError(MyxcelError)` (`exit_code = 2`), per A21;
  - `ContemplexError` and `ErrorCode`, mirroring `contemplex/errors.py:6-22` (the full `StrEnum`, including `STAGING_FAILED`, and `code`/`context` attributes);
  - `mcp`, a stand-in server object accepted by `wire()`.

  The §6.9 test uses the real `_EXIT_CODES` table (`contemplex/cli.py:43-52`) as written in the example. It asserts that `SessionNotFound`-coded → exit 3, `GATE_BLOCKED` → 4, `STAGING_FAILED` → 1, and that a non-contemplex `RuntimeError` → an `INTERNAL` panel and exit 1. The `app.meta` test asserts that `--verbose <cmd>` reaches the consumer's module state and that the inner command's result reaches the outer `result_action`.

**T7. Audit gate.** Re-run all registration, MCP and telemetry tests, and review the diff for any change to `compose.py`.
- **Files:** none
- **Acceptance:** the `compose.py` diff is empty, and tests 24 and 25 pass.

## 13. Risks

- **R1.** Handler-chosen exit codes are not visible in `cli.cmd_end`, because the span closes first. If this matters, add a follow-up `cli.cmd_exit` event (out of scope). A formatter `sys.exit` *is* recorded, except in the `_cisternal_timed` branch. A `prepare` or `_rebind` exit or crash is never recorded (§5.2).
- **R2.** Hooks don't chain: a tool-level `prepare` or `format_success` silently replaces the wire-level one. Mitigation: document it, and keep `merged_over` public so consumers can compose by hand.
- **R3.** The cyclopts 5.x signature and `result_action` semantics are unverified (N6), and the builder calls cyclopts internals (`utils.default_name_transform`, `Parameter.get_negatives`, `Parameter.combine`). T5 pins `cyclopts>=4.18.0,<5` and refreshes `uv.lock`. If the release owner declines, the release notes flag the missing bound explicitly.
- **R4.** With `recovery` set, `to_result()` reroutes failures to `format_success` (§5.2), so a formatter must tolerate error-shaped results. Documented.
- **R5.** `CliOption.annotation` must be a real object, not a string or a `ForwardRef`. Option annotations are added after hint resolution, so a string would reach cyclopts unresolved and be evaluated against the closure's globals. Mitigation: `CliOption.__post_init__` rejects both.
- **R6.** `prepare` runs only on the CLI path, so a tool whose required parameters are filled by prompts must default them to `None`. MCP callers then see those parameters as optional. That is a schema change the consumer opts into. Documented. A `Parameter(parse=False)` argument does not need that change: it may, and preferably should, be declared required keyword-only with no default (`*, token: Annotated[T, Parameter(parse=False)]`), which cyclopts accepts (`parameter.py:533-540`, A26) and which keeps the MCP parameter required. `prepare` must then set it, or `_rebind` raises `TypeError` before the span (§5.2). A defaulted `parse=False` argument is optional on MCP, like a prompted one. In both forms MCP callers pass it explicitly.
- **R7.** The sub-app cache (and `_CLI_CREATED_HELP`) is keyed by `id(parent)`. This is an existing issue, not a new one; it now applies at each level.
- **R8.** The long-flag collision check (§5.4) uses cyclopts' default name transform. Three gaps:
  - An `App` with a custom `name_transform` can produce flags the check does not predict, and so can cyclopts naming features beyond `Parameter(name=, negative=)` and the default negative prefixes. One example is `Parameter.alias`, the field for extra long names (`parameter.py:209-213`): names declared through it are not in the long-flag set.
  - `wire()` puts the target sub-App's resolved `default_parameter` first in the `Parameter.combine` chain (A28). **`cli_command()` cannot model an App's `default_parameter`**, because it builds a callable before any App is known. A composite registered by hand on an App whose `default_parameter` changes names or negatives is checked against cyclopts' defaults only.
  - There is **no backstop** in either case: cyclopts 4.18 does not reject duplicate flags and silently lets the first-declared parameter win (A24, spiked). Short flags are not checked.
- **R9.** Group adoption (§5.6) uses `isinstance(entry, App) and entry.default_command is None` to tell a user App from cyclopts' function-command wrapper (A20, spiked).
  - **Known false negative:** a user sub-App that declares its own `@default` is rejected with `CisternalWireError`. Workaround: call `cisternal.cli_group()` before adding the `@default`, so the group comes from the cache.
  - **Conditional:** if the T4g discriminator test contradicts A20 on the pinned cyclopts, adoption falls back to "only through `cli_group()` called before `wire()`", and the fallback is documented.
- **R10.** Import cycles: `cisternal.adapters.cli` imports `from cisternal import emit_event` (`adapters/cli.py:15`), so an eager top-level import of `cli_contract` must not pull in `adapters.cli` at module scope. Mitigation: `cli_contract.py` imports `timed_command`, `compose`, `wired` and `cyclopts` inside functions only, and T5 checks both import orders.
- **R11.** The A9 fix and the `functools.wraps` behaviour it relies on are verified on CPython 3.13 only. Under 3.14's lazy annotations, a wrapper's `__annotations__` may be empty or differ. The `__wrapped__` fallback in `_resolve_cli_hints` targets that case, but it stays unverified unless the T0b 3.14 spike runs.
- **R12.** The pre-pass validates groups with a read-only probe and then mounts them in a second walk. That is sound because `wire()` is single-threaded and nothing between the two walks changes the App, except the call's own registrations, which the planned-name check (§5.1) has already shown cannot collide with each other or with the names already present at existing levels. Concurrent mutation of the same App from another thread during `wire()` is unsupported, as it is today.