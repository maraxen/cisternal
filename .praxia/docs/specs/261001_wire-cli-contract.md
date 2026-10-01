---
title: "wire() rich CLI contract"
description: "Declarative CLI contract with exception mapping, rich formatters, and group interop for cisternal #30"
task_id: 261001_wire-cli-contract
status: accepted
---

# Spec: `wire()` rich CLI contract (cisternal #30)

task_id: `261001_wire-cli-contract` · status: draft rev 5 (adversarial coherence round 4 and fitness round 4 applied) · base: `release/0.1.1a14` @ `8730da8`

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
   - redsox exits 2 on `SeamExplosionError`.
   - myxcel carries `exit_code` as an integer class attribute.
   - contemplex carries a *string-valued* code.
2. **Rich or structured output**: tables, colours, `--json` / `--json-out`.
3. **CLI-only parameters** that the MCP tool signature must not gain: `--json`, `--working-dir`, and interactive fallbacks.
4. **Composite commands** that chain several tools and write intermediate files.
5. **Pre-existing and nested command groups.**

As a result, alphex and redsox use `wire()` only for MCP and hand-write a parallel CLI.

**A latent bug (§3, A9) blocks the migration on its own.**

## 2. Goals / Non-goals

**Goals**

- **G1.** A declarative `CliContract` with defined precedence.
- **G2.** Exception-to-exit-code mapping with handlers.
- **G3.** A success formatter for rich, plain or JSON output.
- **G4.** CLI-only options are injected into the CLI signature only.
- **G5.** An optional `prepare(ctx)` hook that runs before dispatch.
- **G6.** A public `cli_command(fn, ...)` helper for composite commands.
- **G7.** Fix A9 (annotation resolution) for tools using `from __future__ import annotations`.
- **G8.** A consumer-onboarding doc.
- **G9.** With no contract supplied, behaviour is byte-identical to today.
- **G10.** Group interop: adopting existing App groups, help text, nesting, and a public `cisternal.cli_group()`.
- **G11.** Per-command `--help` text and visibility overrides through `CliContract`.

**Non-goals**

- **N1.** Any change to the MCP surface.
- **N2.** A pipeline/DAG DSL for composite commands.
- **N3.** Bundling or mandating a rendering library.

## 3. Assumptions

Key assumptions verified against the codebase at `release/0.1.1a14` (8730da8):

| # | Assumption | Status |
|---|---|---|
| A1 | The CLI closure is built per entry, with success/failure paths and identity attributes | VERIFIED |
| A2 | timed_command wraps _dispatch and applies functools.wraps | VERIFIED |
| A9 | **Bug:** tool modules using `from __future__ import annotations` break wire() due to unresolved annotations | VERIFIED |
| A20 | Cyclopts' group collision rules: user App has `default_command is None`, function wrappers have the function as `default_command` | VERIFIED |

See full spec document for complete assumption table.

## 4. API design

The new module is `src/cisternal/registration/cli_contract.py`.

Key types:

```python
@dataclass(frozen=True)
class CliOption:
    """A CLI-only keyword option injected into the CLI callable's signature."""
    name: str
    annotation: Any
    default: Any = None
    help: str | None = None

@dataclass(frozen=True)
class CliContract:
    format_success: SuccessFormatter | None = None
    exit_codes: Mapping[type[Exception], int | ExitHandler] = field(default_factory=dict)
    options: Sequence[CliOption] = ()
    prepare: PrepareHook | None = None
    help: str | None = None
    show: bool | None = None

def cli_command(fn: Callable, *, name=None, command=None, contract=None, recovery=None, telemetry=True) -> Callable: ...
def cli_group(app: Any, path: GroupPath, *, help: str | None = None) -> Any: ...
```

Changed signatures:

```python
def tool(fn=None, *, registry="default", name=None,
         cli_group=None, cli_name=None,
         cli_contract: CliContract | None = None): ...

def wire(server, app=None, *, adapter=None, registry="default", expected=None,
         validate=True, recovery=None, cli_telemetry=True,
         cli_contract: CliContract | None = None,
         cli_contracts: Mapping[str, CliContract] | None = None,
         cli_group_help: Mapping[str | tuple[str, ...], str] | None = None) -> WiredRegistry: ...
```

## 5. Semantics

### 5.1 Effective contract precedence

Tool contract (T) merges over wire contract (W):
- `format_success`, `prepare`, `help`, `show`: T's if not None, else W's
- `exit_codes`: merged via `{**W.exit_codes, **T.exit_codes}`
- `options`: `(*W.options, *T.options)` as a tuple

### 5.2 Call layering

With a contract, the CLI callable:

1. Builds `CliContext(tool_name, command)`
2. Pops CLI-only options from kwargs
3. Binds tool parameters
4. Runs `prepare` hook (untimed)
5. Runs rebind check
6. Calls tool with span (timed via timed_command)
7. Runs formatter on result
8. Catches exceptions and resolves exit codes

### 5.3 Exception → exit code resolution

```python
def _resolve_exit(exc, ctx, exit_codes):
    for klass in type(exc).__mro__:
        if klass in exit_codes:
            v = exit_codes[klass]
            break
    else:
        v = None
    
    if v is None or isinstance(v, int):
        default_report(exc)
        return 1 if v is None else v
    
    code = v(exc, ctx)  # handler
    if code is None:
        default_report(exc)
        return 1
    return code
```

### 5.4 CLI-only options

Options are injected as `KEYWORD_ONLY` parameters. Collision validation checks:
- Option identifier vs. tool parameter name
- Long CLI flags (names starting with `--`)

### 5.5 A9 fix

Annotation resolution per-parameter only, with fallback to raw copy on error in no-contract path. Strict path raises `CisternalWireError`.

### 5.6 Groups

Path normalisation, per-level adoption/creation, help application at each level, and nesting support.

## 6. Worked examples

See the full spec document for complete examples: redsox, alphex, myxcel/maraxiom, contemplex, and generic result envelopes.

## 7. Back-compat

- Default path (no contract): emits today's closure (verbatim except line 318: A9 fix)
- Pre-pass ordering: register in same order
- F1 bytes, exit 1, SystemExit passthrough unchanged
- Signature equality, telemetry payloads unchanged
- Groups: adoption of user Apps; rejected function commands

## 8. Docs

Public guide: `docs/guides/wire-onboarding.md` with seven sections, covering why, tool rules, recipes, composites, gotchas, when to drop to plain cyclopts, and a typer migration table with examples.

## 9. Test plan

Over 40 positive and negative control tests, plus preservation tests.

Key test categories:
- Exception mapping and MRO
- CLI-only options
- Formatters and return values
- prepare hooks and rebinding
- Group adoption and nesting
- A9 annotation fix (future annotations, wrapped tools, TYPE_CHECKING imports)
- Collision detection
- Pre-pass and untouched-on-failure guarantee
- Telemetry before/after span
- Composite commands
- App-level result_action composition

## 10. Fixer task decomposition

Order: **T0a → T0b → T1 → T2 → T3 → T4 → T4g → T5 → T6 → T7**

**T0a. Golden capture.** Record baseline behavior at `8730da8` before any changes.

**T0b. Hoist and A9 fix.** Move `_make_cli_cmd` to module scope and add per-parameter annotation resolution.

**T1. Contract types.** Implement `CliOption`, `CliContract`, helpers, and `_resolve_exit`.

**T2. Registration plumbing.** Add `ToolEntry.cli_contract` field and `@tool(cli_contract=)`.

**T3. Builder.** Implement `_build_cli_callable` with prepare hooks, option injection, and collision checks.

**T4. Wire integration.** Pre-pass, effective contract merging, CLI callable construction before registration.

**T4g. Groups.** Group adoption, help application, nested paths, and public `cli_group()`.

**T5. Exports.** Public API exports, cycle checks, cyclopts upper bound.

**T6. Docs.** Consumer onboarding guide with recipes, migration table, and examples.

**T7. Audit gate.** Final test run and review.

## 11. Risks

- **R1:** Handler-chosen exit codes not in telemetry (use sys.exit in formatter)
- **R2:** Hooks don't chain (document and use merged_over)
- **R3:** Cyclopts 5.x unverified; upper bound `<5` in pyproject.toml
- **R8:** Collision check limited to default names; custom name_transform out of scope
- **R11:** A9 fix verified on CPython 3.13 only
