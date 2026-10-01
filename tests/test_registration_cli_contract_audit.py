"""Regression tests for the confirmed audit findings of cisternal #30 (wire CLI contract).

Each test here failed before its fix (or, for the test-only findings, kills the
mutation named in its docstring).

* correctness-1: a flattened dataclass parameter claims its fields' flags.
* correctness-2: an option may not claim cyclopts' built-in ``--help`` / ``--version``.
* correctness-3: a decorator ``cli_contract`` is type-checked.
* correctness-4: a tool parameter named ``fn`` or ``recovery`` reaches the tool.
* tests-docs-3: the tool module's globals override ``wired.py``'s in annotation resolution.
* tests-docs-4: an adopted group given ``cli_group_help`` (cache hit), and the
  ``cli_group()``-before-``@default`` recipe.
* tests-docs-5: ``exit_code_attr`` ignores a ``bool`` ``exit_code``.
* tests-docs-6: the documented ``TypeError`` validations on the public API.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

import pytest
from cyclopts import App, Parameter

from cisternal import tool
from cisternal.registration.cli_contract import (
    CliContext,
    CliContract,
    CliOption,
    _claimed_long_flags,
    _resolve_cli_hints,
    cli_command,
    cli_group,
    exit_code_attr,
)
from cisternal.registration.compose import apply_recovery_sync, compose_mcp_callable
from cisternal.registration.errors import CisternalWireError
from cisternal.registration.registry import (
    ToolEntry,
    _registry,
    clear_registry,
    register,
)
from cisternal.registration.shim import cli_dispatch, dispatch
from cisternal.registration.wired import wire

REGISTRY = "cli-contract-audit-test"


@pytest.fixture(autouse=True)
def _isolation():
    clear_registry(REGISTRY)
    yield
    clear_registry(REGISTRY)


def _stdout(capsys: pytest.CaptureFixture[str]) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)


def _run(app: App, argv: list[str]) -> int | None:
    try:
        app(argv, exit_on_error=False)
    except SystemExit as e:
        return cast("int | None", e.code)
    return None


def _show_options(result: Any, ctx: CliContext) -> None:
    print(f"{result}|{ctx.options}")


# ---------------------------------------------------------------------------
# correctness-1: Parameter(name="*") flattening
# ---------------------------------------------------------------------------


@dataclass
class Cfg:
    verbose: bool = False
    level: int = 1


@dataclass
class Outer:
    inner: Cfg = field(default_factory=Cfg)
    top: int = 0


def flat_tool(
    cfg: Annotated[Cfg, Parameter(name="*")] = Cfg(), *, other: int = 0
) -> str:
    return f"{cfg.verbose}/{cfg.level}/{other}"


def nested_flat_tool(outer: Annotated[Outer, Parameter(name="*")] = Outer()) -> str:
    return f"{outer.top}"


def test_1_flattened_fields_claim_their_own_flags():
    hints = _resolve_cli_hints(flat_tool, strict=True, tool_name="flat_tool")
    flags = _claimed_long_flags("cfg", hints["cfg"], Cfg(), None)
    assert flags == {"--verbose", "--no-verbose", "--level"}
    assert "--*" not in flags


def test_1_flattened_nested_dataclass_flags_are_claimed():
    hints = _resolve_cli_hints(nested_flat_tool, strict=True, tool_name="t")
    flags = _claimed_long_flags("outer", hints["outer"], Outer(), None)
    assert {"--top", "--inner.verbose", "--inner.level"} <= flags
    assert "--*" not in flags


@pytest.mark.parametrize(
    ("option", "flag"),
    [
        (CliOption("verbose", bool, False), "--(no-)?verbose"),
        (
            CliOption("no_verbose", Annotated[bool, Parameter(name="--no-verbose")], False),
            "--no-verbose",
        ),
        (CliOption("lvl", Annotated[int, Parameter(name="--level")], 0), "--level"),
    ],
    ids=["field-name", "negative-flag", "explicit-name"],
)
def test_1_an_option_colliding_with_a_flattened_field_is_rejected_by_wire(option, flag):
    register(flat_tool, registry=REGISTRY)
    app = App(name="cli")
    with pytest.raises(CisternalWireError, match=flag) as excinfo:
        wire(None, app, registry=REGISTRY, cli_contract=CliContract(options=[option]))
    assert "'cfg'" in str(excinfo.value)
    assert "flat_tool" not in app


def test_1_an_option_colliding_with_a_flattened_field_is_rejected_by_cli_command():
    contract = CliContract(options=[CliOption("verbose", bool, False)])
    with pytest.raises(CisternalWireError, match="--(no-)?verbose"):
        cli_command(flat_tool, contract=contract)


def test_1_an_option_that_does_not_collide_with_a_flattened_tool_works(capsys):
    """Control: the flattened fields still reach the tool and the option still fires."""
    register(flat_tool, registry=REGISTRY)
    app = App(name="cli")
    wire(
        None,
        app,
        registry=REGISTRY,
        cli_contract=CliContract(
            options=[CliOption("quiet", bool, False)], format_success=_show_options
        ),
    )
    assert _run(app, ["flat_tool", "--verbose", "--quiet"]) == 0
    assert _stdout(capsys) == "True/1/0|{'quiet': True}\n"


# ---------------------------------------------------------------------------
# correctness-2: cyclopts' built-in flags
# ---------------------------------------------------------------------------


def plain_tool(x: int = 0) -> str:
    return f"x={x}"


@pytest.mark.parametrize("name", ["help", "version"])
def test_2_an_option_named_like_a_builtin_flag_is_rejected_by_wire(name):
    register(plain_tool, registry=REGISTRY)
    app = App(name="cli")
    with pytest.raises(CisternalWireError, match=f"--{name}") as excinfo:
        wire(
            None,
            app,
            registry=REGISTRY,
            cli_contract=CliContract(options=[CliOption(name, bool, False)]),
        )
    assert "built-in" in str(excinfo.value)
    assert "plain_tool" in str(excinfo.value)
    assert "plain_tool" not in app


@pytest.mark.parametrize("name", ["help", "version"])
def test_2_an_option_named_like_a_builtin_flag_is_rejected_by_cli_command(name):
    contract = CliContract(options=[CliOption(name, bool, False)])
    with pytest.raises(CisternalWireError, match="built-in"):
        cli_command(plain_tool, contract=contract)


def test_2_an_explicit_builtin_flag_name_is_rejected_too():
    contract = CliContract(
        options=[CliOption("h", Annotated[bool, Parameter(name="--help")], False)]
    )
    with pytest.raises(CisternalWireError, match="--help"):
        cli_command(plain_tool, contract=contract)


def test_2_the_apps_own_flag_names_are_reserved_not_cyclopts_defaults(capsys):
    """An App that renamed its help flag frees ``--help`` and reserves ``--aid``."""
    register(plain_tool, registry=REGISTRY)
    app = App(name="cli", help_flags=["--aid"], version_flags=[])
    wire(
        None,
        app,
        registry=REGISTRY,
        cli_contract=CliContract(
            options=[CliOption("help", bool, False)], format_success=_show_options
        ),
    )
    # --help is an ordinary option here: it is delivered, not intercepted.
    assert _run(app, ["plain_tool", "--help"]) == 0
    assert _stdout(capsys) == "x=0|{'help': True}\n"

    clear_registry(REGISTRY)
    register(plain_tool, registry=REGISTRY)
    other = App(name="cli2", help_flags=["--aid"], version_flags=[])
    with pytest.raises(CisternalWireError, match="--aid"):
        wire(
            None,
            other,
            registry=REGISTRY,
            cli_contract=CliContract(options=[CliOption("aid", bool, False)]),
        )


def test_2_a_group_cisternal_creates_carries_the_default_flags():
    """The new leaf App answers to ``--help`` even if the root renamed its own."""
    register(plain_tool, registry=REGISTRY, cli_group="g")
    app = App(name="cli", help_flags=["--aid"], version_flags=[])
    with pytest.raises(CisternalWireError, match="--help"):
        wire(
            None,
            app,
            registry=REGISTRY,
            cli_contract=CliContract(options=[CliOption("help", bool, False)]),
        )
    assert "g" not in app


def test_2_an_adopted_group_still_reserves_the_flags_of_the_root():
    register(plain_tool, registry=REGISTRY, cli_group="g")
    app = App(name="cli")
    app.command(App(name="g"))
    with pytest.raises(CisternalWireError, match="--version"):
        wire(
            None,
            app,
            registry=REGISTRY,
            cli_contract=CliContract(options=[CliOption("version", bool, False)]),
        )


# ---------------------------------------------------------------------------
# correctness-3: decorator-supplied cli_contract is type-checked
# ---------------------------------------------------------------------------


def _bad_contract() -> Any:
    return {"exit_codes": {}}


def test_3_the_decorator_rejects_a_non_contract():
    def t() -> str:
        return "x"

    with pytest.raises(TypeError, match="cli_contract must be a CliContract"):
        tool(registry=REGISTRY, cli_contract=_bad_contract())(t)

    assert dict(_registry(REGISTRY)) == {}
    assert not hasattr(t, "__cisternal_tool__")


def test_3_register_rejects_a_non_contract():
    with pytest.raises(TypeError, match="cli_contract must be a CliContract"):
        register(plain_tool, registry=REGISTRY, cli_contract=cast("Any", "nope"))
    assert dict(_registry(REGISTRY)) == {}


def test_3_the_decorator_accepts_a_contract_and_stores_it_as_given():
    contract = CliContract()

    @tool(registry=REGISTRY, cli_contract=contract)
    def t() -> str:
        return "x"

    assert _registry(REGISTRY)["t"].cli_contract is contract


@pytest.mark.parametrize("with_app", [False, True], ids=["app-none", "app"])
def test_3_wire_rejects_a_bad_contract_on_an_entry_built_by_hand(with_app):
    """An entry that bypassed ``register()`` is still caught, and by a TypeError."""
    _registry(REGISTRY)["t"] = ToolEntry(
        name="t",
        fn=plain_tool,
        registry=REGISTRY,
        cli_contract=_bad_contract(),
    )
    app = App(name="cli") if with_app else None
    with pytest.raises(TypeError, match="tool 't': cli_contract must be a CliContract"):
        wire(None, app, registry=REGISTRY)
    if app is not None:
        assert "t" not in app


# ---------------------------------------------------------------------------
# correctness-4: tool parameters named like the dispatch helpers' own
# ---------------------------------------------------------------------------


def fn_param_tool(*, fn: str = "x") -> str:
    return f"fn={fn}"


def recovery_param_tool(*, recovery: str = "x") -> str:
    return f"recovery={recovery}"


async def async_fn_param_tool(*, fn: str = "x") -> str:
    return f"fn={fn}"


_NEVER_RECOVER = (lambda exc: False, lambda: None)


@pytest.mark.parametrize(
    ("tool_fn", "kwarg"),
    [(fn_param_tool, "fn"), (recovery_param_tool, "recovery")],
    ids=["fn", "recovery"],
)
@pytest.mark.parametrize(
    "contract", [None, CliContract()], ids=["no-contract", "contract"]
)
@pytest.mark.parametrize("recovery", [None, _NEVER_RECOVER], ids=["no-recovery", "recovery"])
def test_4_cli_command_delivers_a_parameter_named_like_a_helper_argument(
    tool_fn, kwarg, contract, recovery
):
    cmd = cli_command(tool_fn, contract=contract, recovery=recovery, telemetry=False)
    assert cmd(**{kwarg: "hello"}) == f"{kwarg}=hello"


@pytest.mark.parametrize(
    ("tool_fn", "flag", "expected"),
    [
        (fn_param_tool, "--fn", "fn=hello"),
        (recovery_param_tool, "--recovery", "recovery=hello"),
    ],
    ids=["fn", "recovery"],
)
@pytest.mark.parametrize("contract", [None, CliContract()], ids=["no-contract", "contract"])
def test_4_wire_runs_a_tool_with_such_a_parameter_from_the_cli(
    capsys, tool_fn, flag, expected, contract
):
    register(tool_fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=contract, recovery=_NEVER_RECOVER)
    assert _run(app, [tool_fn.__name__, flag, "hello"]) == 0
    captured = capsys.readouterr()
    assert re.sub(r"\x1b\[[0-9;]*m", "", captured.out) == expected + "\n"
    assert captured.err == ""


def test_4_the_dispatch_helpers_take_their_own_arguments_positionally():
    assert cli_dispatch(fn_param_tool, fn="a") == "fn=a"
    assert cli_dispatch(recovery_param_tool, recovery="a") == "recovery=a"
    assert apply_recovery_sync(fn_param_tool, None, fn="a") == "fn=a"
    assert apply_recovery_sync(fn_param_tool, _NEVER_RECOVER, fn="a") == "fn=a"
    assert (
        apply_recovery_sync(recovery_param_tool, _NEVER_RECOVER, recovery="a")
        == "recovery=a"
    )
    assert cli_dispatch(async_fn_param_tool, fn="a") == "fn=a"


def test_4_the_mcp_path_delivers_them_too():
    assert asyncio.run(dispatch(fn_param_tool, fn="a")) == "fn=a"
    generated = compose_mcp_callable(fn_param_tool)
    assert asyncio.run(generated(fn="a")) == "fn=a"
    with_recovery = compose_mcp_callable(
        recovery_param_tool, recovery=_NEVER_RECOVER, tool_name="recovery_param_tool"
    )
    assert asyncio.run(with_recovery(recovery="a")) == "recovery=a"


# ---------------------------------------------------------------------------
# tests-docs-3: the tool module's globals override wired.py's
# ---------------------------------------------------------------------------


def _tool_from_a_module_that_rebinds_any() -> Any:
    """A tool whose module binds ``Any`` to ``int`` (wired.py binds typing.Any)."""
    namespace: dict[str, Any] = {"__name__": "rebinding_tool_module", "Any": int}
    exec(  # noqa: S102
        "def rebinding_tool(x: 'Any') -> str:\n"
        "    return type(x).__name__\n",
        namespace,
    )
    return namespace["rebinding_tool"]


def test_9_the_tool_modules_binding_wins_over_wired_pys():
    fn = _tool_from_a_module_that_rebinds_any()
    # Control: the name really does resolve in wired.py to something else.
    from cisternal.registration import wired as wired_module

    assert vars(wired_module)["Any"] is Any
    assert _resolve_cli_hints(fn, strict=True, tool_name="rebinding_tool") == {"x": int}
    assert _resolve_cli_hints(fn, strict=False) == {"x": int}


def test_9_the_tool_modules_binding_wins_end_to_end(capsys):
    fn = _tool_from_a_module_that_rebinds_any()
    register(fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    # int, not str: cyclopts converted "3" through the tool module's ``Any``.
    assert _run(app, ["rebinding_tool", "3"]) == 0
    assert _stdout(capsys) == "int\n"


def test_9_a_name_only_wired_py_binds_still_resolves():
    """The other half of the merge: names the tool module lacks fall back to wired.py's."""
    namespace: dict[str, Any] = {"__name__": "falls_back_module"}
    exec("def falls_back(x: 'Mapping') -> None: ...", namespace)  # noqa: S102
    from cisternal.registration import wired as wired_module

    resolved = _resolve_cli_hints(namespace["falls_back"], strict=True, tool_name="t")
    assert resolved["x"] is vars(wired_module)["Mapping"]


# ---------------------------------------------------------------------------
# tests-docs-4: group help on an adopted level (cache hit) and the recipe
# ---------------------------------------------------------------------------


def _sub_a() -> str:
    return "a"


def _sub_b() -> str:
    return "b"


def _premounted(app: App, name: str = "jobs", **kwargs: Any) -> App:
    sub = App(name=name, **kwargs)
    app.command(sub)
    return sub


def test_30_two_tools_in_an_adopted_group_given_help_leave_the_help_alone():
    """A second tool in the adopted group hits the cache with a help entry present."""
    register(_sub_a, registry=REGISTRY, cli_group="jobs")
    register(_sub_b, registry=REGISTRY, cli_group="jobs")
    app = App(name="cli")
    jobs = _premounted(app, help="User help")
    wired = wire(None, app, registry=REGISTRY, cli_group_help={"jobs": "Cisternal help"})

    assert wired.cli_commands == ["jobs _sub_a", "jobs _sub_b"]
    assert jobs.help == "User help"
    assert "_sub_a" in jobs and "_sub_b" in jobs


def test_30_a_second_wire_call_with_help_reuses_the_adopted_group():
    app = App(name="cli")
    jobs = _premounted(app, help="User help")
    register(_sub_a, registry=REGISTRY, cli_group="jobs")
    wire(None, app, registry=REGISTRY, cli_group_help={"jobs": "H1"})
    clear_registry(REGISTRY)
    register(_sub_b, registry=REGISTRY, cli_group="jobs")
    wire(None, app, registry=REGISTRY, cli_group_help={"jobs": "H2"})

    assert jobs.help == "User help"
    assert "_sub_a" in jobs and "_sub_b" in jobs


def test_30_cli_group_help_on_an_adopted_level_is_ignored_on_a_cache_hit():
    app = App(name="cli")
    jobs = _premounted(app, help="User help")
    assert cli_group(app, "jobs") is jobs  # adopts and caches
    assert cli_group(app, "jobs", help="Other") is jobs  # cache hit, help given
    assert jobs.help == "User help"


def test_32_the_documented_default_recipe_cli_group_before_default(capsys):
    """Guide recipe: call ``cli_group()`` first, then add the user ``@default``.

    wire() would reject a pre-mounted App that declares its own ``@default``; the
    group already in the cache is reused instead, so wiring into it succeeds.
    """
    app = App(name="cli")
    group = cli_group(app, "g")

    @group.default
    def landing() -> None:
        print("landing")

    register(_sub_a, registry=REGISTRY, cli_group="g")
    wired = wire(None, app, registry=REGISTRY, cli_group_help={"g": "G help"})

    assert wired.cli_commands == ["g _sub_a"]
    assert group.help == "G help"
    assert _run(app, ["g"]) == 0
    assert _stdout(capsys) == "landing\n"
    assert _run(app, ["g", "_sub_a"]) == 0
    assert _stdout(capsys) == "a\n"


def test_32_control_a_user_app_with_its_own_default_is_rejected_without_the_recipe():
    app = App(name="cli")
    group = _premounted(app, "g")

    @group.default
    def landing() -> None: ...

    register(_sub_a, registry=REGISTRY, cli_group="g")
    with pytest.raises(CisternalWireError, match="'g'"):
        wire(None, app, registry=REGISTRY)


# ---------------------------------------------------------------------------
# tests-docs-5: exit_code_attr ignores a bool attribute
# ---------------------------------------------------------------------------


class _Boolish(Exception):
    exit_code = True  # int(True) == 1: only a non-default fallback can tell


def _ctx() -> CliContext:
    return CliContext("t", "t")


@pytest.mark.parametrize("default", [7, 2, 255])
def test_26_a_bool_exit_code_attribute_falls_back_to_the_default(default, capsys):
    handler = exit_code_attr(default=default)
    assert handler(_Boolish("x"), _ctx()) == default
    capsys.readouterr()


def test_26_a_false_attribute_falls_back_to_the_default(capsys):
    class _Falsy(Exception):
        exit_code = False

    assert exit_code_attr(default=7)(_Falsy("x"), _ctx()) == 7
    capsys.readouterr()


def test_26_control_a_real_int_attribute_is_used(capsys):
    class _Coded(Exception):
        exit_code = 3

    assert exit_code_attr(default=7)(_Coded("x"), _ctx()) == 3
    capsys.readouterr()


# ---------------------------------------------------------------------------
# tests-docs-6: the documented TypeErrors of the public API
# ---------------------------------------------------------------------------


def test_6_wire_rejects_a_non_contract_cli_contract():
    register(plain_tool, registry=REGISTRY)
    app = App(name="cli")
    with pytest.raises(TypeError, match="cli_contract must be a CliContract or None"):
        wire(None, app, registry=REGISTRY, cli_contract=cast("Any", {"exit_codes": {}}))
    assert "plain_tool" not in app


def test_6_wire_rejects_a_non_contract_cli_contracts_value():
    register(plain_tool, registry=REGISTRY)
    app = App(name="cli")
    bad = cast("Any", {"plain_tool": object()})
    with pytest.raises(TypeError, match=r"cli_contracts\['plain_tool'\] must be a CliContract"):
        wire(None, app, registry=REGISTRY, cli_contracts=bad)
    with pytest.raises(TypeError, match=r"cli_contracts\['plain_tool'\] must be a CliContract"):
        wire(None, None, registry=REGISTRY, cli_contracts=bad)
    assert "plain_tool" not in app


@pytest.mark.parametrize("bad", [3, None, b"x", ["H"]], ids=repr)
def test_6_wire_rejects_a_non_str_cli_group_help_value(bad):
    register(plain_tool, registry=REGISTRY, cli_group="flow")
    app = App(name="cli")
    with pytest.raises(TypeError, match=r"cli_group_help\['flow'\] must be a str"):
        wire(None, app, registry=REGISTRY, cli_group_help=cast("Any", {"flow": bad}))
    assert "flow" not in app


def test_6_cli_command_rejects_a_non_contract():
    with pytest.raises(TypeError, match="contract must be a CliContract or None"):
        cli_command(plain_tool, contract=cast("Any", {"exit_codes": {}}))


@pytest.mark.parametrize("bad", [3, b"x", ["H"]], ids=repr)
def test_6_cli_group_rejects_a_non_str_help_keyword(bad):
    app = App(name="cli")
    with pytest.raises(TypeError, match="help must be a str or None"):
        cli_group(app, "g", help=cast("Any", bad))
    assert "g" not in app


def test_6_cli_group_rejects_a_bad_help_before_it_walks_the_path():
    """The check runs first, so a bad help cannot half-mount a multi-level path."""
    app = App(name="cli")
    with pytest.raises(TypeError):
        cli_group(app, "flow visuals", help=cast("Any", 3))
    assert "flow" not in app
