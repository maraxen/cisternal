"""T0b tests for the A9 fix (``_resolve_cli_hints`` and the no-contract CLI closure)
and T1 tests for the contract types (``CliContext``, ``CliOption``, ``CliContract``,
``json_option``, ``default_report``, ``exit_code_attr``, ``merged_over``,
``_resolve_exit``).

Spec: .praxia/docs/specs/261001_wire-cli-contract.md (rev 8), section 5.5 and
tests 9 (no-contract variant), 9b, 9c, 9d (no-contract half), 16c (no-contract
half) and 18.

T3 tests (the contract-path CLI callable and ``cli_command``) are at the end of
the file. The ``wire()``-level variants (tests 9 contract, 9d contract half, the
``wire()`` half of 16a) belong to T4.
"""

from __future__ import annotations

import ast
import inspect
import logging
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Annotated, Any, ForwardRef, cast
from typing import get_args as typing_get_args
from typing import get_origin as typing_get_origin

import pytest
from cyclopts import App, Parameter

from cisternal.registration import cli_contract as cli_contract_module
from cisternal.registration.cli_contract import (
    CliContext,
    CliContract,
    CliOption,
    _resolve_exit,
    cli_command,
    default_report,
    exit_code_attr,
    json_option,
)
from cisternal.registration.errors import CisternalWireError
from cisternal.registration.registry import clear_registry, register
from cisternal.registration.wired import wire
from tests.fixtures import (
    bathos_style_tools,
    future_annot_tools,
    typecheck_any_tools,
    wrapped_future_tools,
)

REGISTRY = "cli-contract-test"


@pytest.fixture(autouse=True)
def _isolation():
    clear_registry(REGISTRY)
    yield
    clear_registry(REGISTRY)


def _hints(fn: Any, *, strict: bool, tool_name: str = "") -> dict[str, Any]:
    # Imported lazily so that a missing module fails the unit tests that need
    # it, not the collection of this whole file.
    from cisternal.registration.cli_contract import _resolve_cli_hints

    return _resolve_cli_hints(fn, strict=strict, tool_name=tool_name)


def _stdout(capsys: pytest.CaptureFixture[str]) -> str:
    """Captured stdout with rich's ANSI colour escapes removed."""
    return re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)


def _wire_one(fn: Any) -> tuple[App, Any]:
    """Register *fn* alone, wire it onto a fresh App, and return (app, registered)."""
    register(fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    return app, app[fn.__name__].default_command


def _run(app: App, argv: list[str]) -> int | None:
    try:
        app(argv, exit_on_error=False)
    except SystemExit as e:
        return cast("int | None", e.code)
    return None


def _legacy_closure(original_fn: Any) -> Any:
    """The 8730da8 closure's identity lines, verbatim (wired.py:315-318 at that commit).

    Test 18 uses it to prove the fixtures really exercise A9: registered through
    a raw ``__annotations__`` copy they must fail the way they failed before.
    The closure is compiled in a copy of wired.py's namespace so that its
    ``__globals__`` are wired.py's, as the real one's are. Defining it in this
    test module would let cyclopts resolve ``Path`` and ``Annotated`` against
    *this* module's imports and hide the bug.
    """
    from cisternal.registration import wired as wired_module

    namespace = dict(vars(wired_module))
    namespace["_original_fn"] = original_fn
    exec(  # noqa: S102
        "def _cli_cmd(*args, **kwargs):\n    return _original_fn(*args, **kwargs)\n",
        namespace,
    )
    _cli_cmd = namespace["_cli_cmd"]
    _cli_cmd.__name__ = original_fn.__name__
    _cli_cmd.__doc__ = original_fn.__doc__
    _cli_cmd.__signature__ = inspect.signature(original_fn)
    _cli_cmd.__annotations__ = dict(original_fn.__annotations__)
    return _cli_cmd


# ---------------------------------------------------------------------------
# Test 9 (no-contract variant)
# ---------------------------------------------------------------------------


def test_9_cyclopts_parameter_annotation_registers_and_parses(capsys):
    fn = future_annot_tools.tool_with_cyclopts_param
    app, registered = _wire_one(fn)

    expected = Annotated[Path, Parameter(name=["--path", "-p"], help="A path.")]
    assert registered.__annotations__ == {"p": expected}
    assert all(not isinstance(v, str) for v in registered.__annotations__.values())
    assert "return" not in registered.__annotations__
    # The signature is untouched: still the raw string annotations, return included.
    assert inspect.signature(registered) == inspect.signature(fn)
    assert inspect.signature(registered).return_annotation == "str"

    assert _run(app, ["tool_with_cyclopts_param", "-p", "/tmp/x"]) == 0
    assert _stdout(capsys) == "/tmp/x\n"


@pytest.mark.parametrize(
    ("fn", "expected_params"),
    [
        (future_annot_tools.tool_with_path_param, {"p": Path}),
        (
            future_annot_tools.tool_with_annotated_param,
            {"p": Annotated[Path, "description"]},
        ),
        (future_annot_tools.tool_with_type_checking_return, {}),
    ],
    ids=["path", "annotated", "type-checking-return"],
)
def test_9_future_annotations_tools_register(fn, expected_params):
    """Includes the tool whose *return* type exists only under TYPE_CHECKING."""
    app, registered = _wire_one(fn)

    assert registered.__annotations__ == expected_params
    assert "return" not in registered.__annotations__
    assert inspect.signature(registered) == inspect.signature(fn)


def test_9_type_checking_return_tool_parses(capsys):
    app, _ = _wire_one(future_annot_tools.tool_with_type_checking_return)
    # The tool returns a function; cyclopts prints a non-int result and exits 0.
    assert _run(app, ["tool_with_type_checking_return"]) == 0


def test_9_tool_wiring_does_not_mutate_the_original():
    fn = future_annot_tools.tool_with_path_param
    before = dict(fn.__annotations__)
    _wire_one(fn)
    assert fn.__annotations__ == before == {"p": "Path", "return": "str"}


# ---------------------------------------------------------------------------
# Test 9b: ``Any`` imported only under TYPE_CHECKING in the tool module
# ---------------------------------------------------------------------------


def test_9b_any_imported_only_under_type_checking(capsys):
    fn = typecheck_any_tools.tool_with_any_param
    app, registered = _wire_one(fn)

    # Resolved through wired.py's globals, which the resolver keeps merged in.
    assert registered.__annotations__ == {"x": Any}
    assert _run(app, ["tool_with_any_param", "3"]) == 0
    assert _stdout(capsys) == "x=3\n"


# ---------------------------------------------------------------------------
# Test 9c: bathos' post-def ``__annotations__`` mutation keeps working
# ---------------------------------------------------------------------------


def test_9c_post_def_annotation_mutation_still_works():
    fn = bathos_style_tools.tool_with_mutated_annotations
    app, registered = _wire_one(fn)

    expected = Annotated[int, Parameter(name=["--x", "-n"])]
    assert registered.__annotations__ == {"x": expected}
    # The tool returns x * 2 and an int result becomes the exit code (A6), so
    # exit 6 proves that ``-n 3`` reached the tool as 3.
    assert _run(app, ["tool_with_mutated_annotations", "-n", "3"]) == 6


# ---------------------------------------------------------------------------
# Test 9d (no-contract half): tools wrapped with functools.wraps
# ---------------------------------------------------------------------------


def test_9d_wrapped_timed_tool_registers_and_parses(capsys):
    fn = wrapped_future_tools.wrapped_tool
    app, registered = _wire_one(fn)

    # ``Path`` is not a name adapters/cli.py (the wrapper's module) imports; it
    # resolves only through the unwrapped function's globals.
    assert registered.__annotations__["p"] is Path
    assert "return" not in registered.__annotations__
    assert not hasattr(registered, "__wrapped__")

    # functools.wraps gave the wrapper the impl's __name__, so that is the command name.
    assert fn.__name__ == "_wrapped_tool_impl"
    assert _run(app, ["_wrapped_tool_impl", "/tmp/x"]) == 0
    assert _stdout(capsys) == "/tmp/x\n"


def test_9d_empty_annotations_fall_back_to_the_unwrapped_function():
    """CPython 3.14 (PEP 649) may leave a wrapper's ``__annotations__`` empty."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return wrapped_future_tools._wrapped_tool_impl(*args, **kwargs)

    wrapper.__wrapped__ = wrapped_future_tools._wrapped_tool_impl  # type: ignore[attr-defined]
    wrapper.__annotations__ = {}

    assert _hints(wrapper, strict=False) == {"p": Path}


def test_9d_globals_come_from_the_unwrapped_function():
    """A wrapper whose own module cannot resolve ``Path`` still resolves it."""
    wrapper = wrapped_future_tools.wrapped_tool
    # Control: the wrapper's own globals (adapters/cli.py) lack ``Path`` ...
    assert "Path" not in wrapper.__globals__
    # ... so only the unwrapped function's globals can resolve it.
    assert _hints(wrapper, strict=True, tool_name="wrapped_tool") == {"p": Path}


# ---------------------------------------------------------------------------
# Test 16c (no-contract half)
# ---------------------------------------------------------------------------


def test_16c_unresolvable_parameter_reproduces_the_legacy_nameerror():
    fn = future_annot_tools.tool_with_unresolvable_param
    register(fn, registry=REGISTRY)
    with pytest.raises(NameError, match="NotImportedAnywhere"):
        wire(None, App(name="cli"), registry=REGISTRY)


def test_16c_unresolvable_parameter_falls_back_to_the_raw_copy():
    fn = future_annot_tools.tool_with_unresolvable_param
    assert _hints(fn, strict=False) == dict(fn.__annotations__)
    assert _hints(fn, strict=False)["return"] == "str"


def test_16c_malformed_string_annotation_falls_back_and_cyclopts_still_fails():
    fn = future_annot_tools.tool_with_malformed_param
    assert fn.__annotations__["x"] == "list[int"

    # SyntaxError is caught by the resolver, not leaked from it ...
    assert _hints(fn, strict=False) == dict(fn.__annotations__)

    # ... and registration then fails in cyclopts exactly as with the raw copy.
    legacy = _legacy_closure(fn)
    with pytest.raises(SyntaxError):
        App(name="legacy").command(name="x")(legacy)
    register(fn, registry=REGISTRY)
    with pytest.raises(SyntaxError):
        wire(None, App(name="cli"), registry=REGISTRY)


def test_16c_strict_raises_cisternal_wire_error_naming_tool_and_parameter():
    for fn in (
        future_annot_tools.tool_with_unresolvable_param,
        future_annot_tools.tool_with_malformed_param,
    ):
        with pytest.raises(CisternalWireError) as excinfo:
            _hints(fn, strict=True, tool_name="my_tool")
        message = str(excinfo.value)
        assert "my_tool" in message
        assert "'x'" in message


def test_16c_strict_does_not_raise_for_an_unresolvable_return_type():
    fn = future_annot_tools.tool_with_type_checking_return
    assert _hints(fn, strict=True, tool_name="t") == {}


# ---------------------------------------------------------------------------
# Test 18: fixture-validity check (not a test of cisternal code)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [
        future_annot_tools.tool_with_path_param,
        future_annot_tools.tool_with_cyclopts_param,
        future_annot_tools.tool_with_type_checking_return,
    ],
    ids=["path-param", "cyclopts-param", "type-checking-return"],
)
def test_18_raw_annotation_copy_reproduces_nameerror(fn):
    """The 8730da8 closure copies raw string annotations and cyclopts then
    resolves them against wired.py's globals. If this stops raising, the
    fixtures no longer exercise A9 and tests 9/9d prove nothing."""
    legacy = _legacy_closure(fn)
    with pytest.raises(NameError):
        App(name="legacy").command(name="x")(legacy)


# ---------------------------------------------------------------------------
# Resolver unit behaviour (section 5.5)
# ---------------------------------------------------------------------------


def test_resolver_keeps_only_parameter_keys():
    fn = future_annot_tools.tool_with_path_param
    assert _hints(fn, strict=False) == {"p": Path}


def test_resolver_skips_parameters_without_annotation():
    def f(a, b: int = 1) -> int:  # noqa: ANN001
        return b

    assert _hints(f, strict=False) == {"b": int}


def test_resolver_drops_non_parameter_keys_even_when_unresolvable():
    def f(a: int) -> int:
        return a

    f.__annotations__["stray"] = "NoSuchName"
    assert _hints(f, strict=False) == {"a": int}
    assert _hints(f, strict=True, tool_name="f") == {"a": int}


def test_resolver_preserves_annotated_extras():
    hints = _hints(future_annot_tools.tool_with_annotated_param, strict=False)
    assert hints["p"] == Annotated[Path, "description"]


# ---------------------------------------------------------------------------
# T1: contract types (tests 3a, 15, 36 construction/merge, 26 unit-level)
# ---------------------------------------------------------------------------


class MyxcelErrorLike(Exception):
    exit_code = 1


class ConfigErrorLike(MyxcelErrorLike):
    exit_code = 2


class OtherMyxcelErrorLike(MyxcelErrorLike):
    exit_code = 4


def _ctx() -> CliContext:
    return CliContext("t", "t")


def _stderr(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().err


def test_3a_mro_specificity_over_merged_map(capsys):
    merged = (
        CliContract(exit_codes={MyxcelErrorLike: 9})
        .merged_over(CliContract(exit_codes={ConfigErrorLike: 2}))
        .exit_codes
    )
    assert _resolve_exit(ConfigErrorLike("boom"), _ctx(), merged) == 2
    assert _stderr(capsys) == "Error (ConfigErrorLike): boom\n"
    assert _resolve_exit(OtherMyxcelErrorLike("x"), _ctx(), merged) == 9
    assert _stderr(capsys) == "Error (OtherMyxcelErrorLike): x\n"


def test_3a_dict_order_is_irrelevant():
    a = {MyxcelErrorLike: 9, ConfigErrorLike: 2}
    b = {ConfigErrorLike: 2, MyxcelErrorLike: 9}
    for codes in (a, b):
        assert _resolve_exit(ConfigErrorLike("e"), _ctx(), codes) == 2


def test_resolve_exit_unmapped_is_f1_line_and_exit_1(capsys):
    codes = {ValueError: 3}
    assert _resolve_exit(KeyError("k"), _ctx(), codes) == 1
    assert _stderr(capsys) == "Error (KeyError): 'k'\n"


def test_resolve_exit_int_value_is_f1_line_and_that_code(capsys):
    assert _resolve_exit(ValueError("msg"), _ctx(), {ValueError: 3}) == 3
    assert _stderr(capsys) == "Error (ValueError): msg\n"


def test_resolve_exit_handler_renders_its_own_report(capsys):
    seen: list[tuple[Any, CliContext]] = []

    def handler(exc: Any, ctx: CliContext) -> int:
        seen.append((exc, ctx))
        print("custom", file=sys.stderr)
        return 6

    exc, ctx = ValueError("m"), _ctx()
    assert _resolve_exit(exc, ctx, {ValueError: handler}) == 6
    assert _stderr(capsys) == "custom\n"
    assert len(seen) == 1 and seen[0][0] is exc and seen[0][1] is ctx


def test_resolve_exit_handler_none_means_f1_line_exit_1(capsys):
    assert _resolve_exit(ValueError("m"), _ctx(), {ValueError: lambda e, c: None}) == 1
    assert _stderr(capsys) == "Error (ValueError): m\n"


def test_resolve_exit_handler_may_return_zero(capsys):
    assert _resolve_exit(ValueError("m"), _ctx(), {ValueError: lambda e, c: 0}) == 0
    assert _stderr(capsys) == ""


def test_resolve_exit_handler_failure_logs_and_falls_back(capsys, caplog):
    def boom(exc: Any, ctx: CliContext) -> int:
        raise RuntimeError("handler broke")

    with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
        assert _resolve_exit(ValueError("m"), _ctx(), {ValueError: boom}) == 1
    assert _stderr(capsys) == "Error (ValueError): m\n"
    assert any(
        "exit handler for ValueError failed" in r.getMessage() for r in caplog.records
    )


def test_resolve_exit_handler_system_exit_passes_through():
    def bye(exc: Any, ctx: CliContext) -> int:
        raise SystemExit(7)

    with pytest.raises(SystemExit) as ei:
        _resolve_exit(ValueError("m"), _ctx(), {ValueError: bye})
    assert ei.value.code == 7


@pytest.mark.parametrize("bad", [True, False, "3", 3.0, -1, 256, 1000])
def test_resolve_exit_handler_bad_return_uses_1_with_warning(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
        got = _resolve_exit(ValueError("m"), _ctx(), {ValueError: lambda e, c: bad})
    assert got == 1
    assert any("exit handler returned" in r.getMessage() for r in caplog.records)


def test_resolve_exit_tolerates_partial_ctx():
    ctx = _ctx()
    assert ctx.arguments == {} and ctx.options == {}
    seen: list[dict[str, Any]] = []

    def handler(exc: Any, c: CliContext) -> int:
        seen.append(dict(c.arguments))
        return 5

    assert _resolve_exit(TypeError("bind"), ctx, {TypeError: handler}) == 5
    assert seen == [{}]


def test_resolve_exit_empty_map_is_exit_1(capsys):
    assert _resolve_exit(ValueError("m"), _ctx(), {}) == 1
    assert _stderr(capsys) == "Error (ValueError): m\n"


# --- test 15: construction raises -------------------------------------------


@pytest.mark.parametrize(
    ("codes", "exc_type"),
    [
        ({SystemExit: 2}, TypeError),
        ({KeyboardInterrupt: 2}, TypeError),
        ({"ValueError": 2}, TypeError),
        ({ValueError("x"): 2}, TypeError),
        ({ValueError: 300}, ValueError),
        ({ValueError: 256}, ValueError),
        ({ValueError: -1}, ValueError),
        ({ValueError: "x"}, TypeError),
        ({ValueError: True}, TypeError),
        ({ValueError: False}, TypeError),
        ({ValueError: 0}, ValueError),
        ({ValueError: None}, TypeError),
        ({ValueError: 2.0}, TypeError),
    ],
)
def test_15_exit_codes_construction_errors(codes, exc_type):
    with pytest.raises(exc_type):
        CliContract(exit_codes=codes)


@pytest.mark.parametrize("code", [1, 2, 255])
def test_15_exit_codes_bounds_accepted(code):
    assert CliContract(exit_codes={ValueError: code}).exit_codes[ValueError] == code


def test_15_exit_code_handler_callable_accepted():
    def h(exc: Any, ctx: CliContext) -> int:
        return 3

    assert CliContract(exit_codes={ValueError: h}).exit_codes[ValueError] is h


@pytest.mark.parametrize(
    ("name", "annotation", "exc_type"),
    [
        ("x", "bool", TypeError),
        ("1x", bool, ValueError),
        ("class", bool, ValueError),
        ("with space", bool, ValueError),
        ("", bool, ValueError),
        (3, bool, ValueError),
        ("x", ForwardRef("bool"), TypeError),
    ],
)
def test_15_cli_option_construction_errors(name, annotation, exc_type):
    with pytest.raises(exc_type):
        CliOption(name, annotation)


def test_15_cli_option_annotated_help_conflicts_with_help_keyword():
    with pytest.raises(ValueError):
        CliOption("x", Annotated[bool, Parameter(help="a")], help="b")


def test_15_cli_option_help_must_be_str_or_none():
    with pytest.raises(TypeError):
        CliOption("x", bool, help=3)  # type: ignore[arg-type]


def test_15_cli_option_valid_forms_do_not_raise():
    CliOption("x", bool)
    CliOption("x", bool, False, help="h")
    CliOption("x", Annotated[bool, Parameter(name="--ex")], help="h")  # no Parameter help
    CliOption("x", Annotated[bool, Parameter(help="a")])  # help kwarg unset: no conflict
    CliOption("x", Path | None, None, help="Run as if started in this directory")
    CliOption("x", Annotated[bool, "plain metadata"], help="h")


def test_15_cli_option_is_frozen():
    o = CliOption("x", bool)
    with pytest.raises(AttributeError):
        o.name = "y"  # type: ignore[misc]


def test_15_duplicate_option_names_in_one_contract():
    with pytest.raises(ValueError, match="x"):
        CliContract(options=[CliOption("x", bool), CliOption("x", int)])


def test_15_options_must_be_cli_options():
    with pytest.raises(TypeError):
        CliContract(options=["x"])  # type: ignore[list-item]


def test_15_merged_over_duplicate_option_name_raises():
    base = CliContract(options=[CliOption("x", bool)])
    over = CliContract(options=[CliOption("x", int)])
    with pytest.raises(ValueError, match="x"):
        over.merged_over(base)


# --- test 15: normalisation, must not raise ----------------------------------


def test_15_options_list_becomes_tuple():
    c = CliContract(options=[json_option()])
    assert isinstance(c.options, tuple)
    assert c.options == (json_option(),)


def test_15_exit_codes_is_readonly_copy():
    src: dict[type[Exception], int] = {ValueError: 3}
    c = CliContract(exit_codes=src)
    assert isinstance(c.exit_codes, types.MappingProxyType)
    src[KeyError] = 4
    src[ValueError] = 9
    assert dict(c.exit_codes) == {ValueError: 3}
    with pytest.raises(TypeError):
        c.exit_codes[KeyError] = 4  # type: ignore[index]


def test_15_defaults_are_empty_and_normalised():
    c = CliContract()
    assert c.options == () and isinstance(c.options, tuple)
    assert isinstance(c.exit_codes, types.MappingProxyType) and len(c.exit_codes) == 0
    assert (c.format_success, c.prepare, c.help, c.show) == (None, None, None, None)


def test_15_contract_is_unhashable():
    with pytest.raises(TypeError):
        hash(CliContract())
    assert CliContract.__hash__ is None


def test_15_contract_is_frozen():
    c = CliContract()
    with pytest.raises(AttributeError):
        c.help = "x"  # type: ignore[misc]


def test_15_merged_over_none_returns_the_identical_object():
    c = CliContract(
        format_success=lambda r, ctx: None,
        exit_codes={ValueError: 3},
        options=[json_option()],
        help="h",
        show=False,
    )
    assert c.merged_over(None) is c


def test_15_section_6_8_pair_merges_with_tuple_options():
    w = CliContract(exit_codes={MyxcelErrorLike: exit_code_attr()})
    t_opts = [
        CliOption("working_dir", Path | None, None, help="Run as if started here"),
        CliOption("quiet", bool, False),
    ]
    t = CliContract(options=t_opts)
    m = t.merged_over(w)
    assert isinstance(m.options, tuple)
    assert m.options == tuple(t_opts)
    assert MyxcelErrorLike in m.exit_codes


# --- merge semantics (5.1) ---------------------------------------------------


def _fmt_w(result: Any, ctx: CliContext) -> Any:
    return "w"


def _fmt_t(result: Any, ctx: CliContext) -> Any:
    return "t"


def _prep_w(ctx: CliContext) -> None: ...


def _prep_t(ctx: CliContext) -> None: ...


def test_merge_options_order_is_base_then_self():
    ow1, ow2 = CliOption("a", bool), CliOption("b", bool)
    ot1, ot2 = CliOption("c", bool), CliOption("d", bool)
    w = CliContract(options=[ow1, ow2])
    t = CliContract(options=[ot1, ot2])
    assert t.merged_over(w).options == (ow1, ow2, ot1, ot2)


def test_merge_exit_codes_t_wins_on_equal_key_and_unions_the_rest():
    w = CliContract(exit_codes={ValueError: 2, KeyError: 5})
    t = CliContract(exit_codes={ValueError: 9, OSError: 7})
    m = t.merged_over(w).exit_codes
    assert isinstance(m, types.MappingProxyType)
    assert dict(m) == {ValueError: 9, KeyError: 5, OSError: 7}


def test_merge_callables_t_wins_if_not_none():
    w = CliContract(format_success=_fmt_w, prepare=_prep_w)
    both = CliContract(format_success=_fmt_t, prepare=_prep_t).merged_over(w)
    assert both.format_success is _fmt_t and both.prepare is _prep_t
    neither = CliContract().merged_over(w)
    assert neither.format_success is _fmt_w and neither.prepare is _prep_w


def test_merge_help_and_show_t_wins_if_not_none():
    w = CliContract(help="w", show=True)
    unset = CliContract(help=None, show=None).merged_over(w)
    assert unset.help == "w" and unset.show is True
    both = CliContract(help="t", show=False).merged_over(w)
    assert both.help == "t" and both.show is False
    # show=False on T must win even though it is falsy.
    assert CliContract(show=False).merged_over(CliContract(show=True)).show is False
    # Neither side sets them: stay None (builder then passes no keyword).
    m = CliContract().merged_over(CliContract())
    assert m.help is None and m.show is None


def test_merge_is_pure():
    w = CliContract(options=[CliOption("a", bool)], exit_codes={ValueError: 2}, help="w")
    t = CliContract(options=[CliOption("b", bool)], exit_codes={KeyError: 3})
    w_before = (w.options, dict(w.exit_codes))
    t_before = (t.options, dict(t.exit_codes))
    m = t.merged_over(w)
    assert m is not t and m is not w
    assert (w.options, dict(w.exit_codes)) == w_before
    assert (t.options, dict(t.exit_codes)) == t_before
    assert w.help == "w" and t.help is None


# --- test 36: help / show construction ---------------------------------------


@pytest.mark.parametrize("bad", [3, b"x", ["h"], True])
def test_36_help_must_be_str_or_none(bad):
    with pytest.raises(TypeError):
        CliContract(help=bad)


@pytest.mark.parametrize("bad", ["no", 0, 1, [], "False"])
def test_36_show_must_be_bool_or_none(bad):
    with pytest.raises(TypeError):
        CliContract(show=bad)


def test_36_help_show_valid_values():
    assert CliContract(help="Custom help").help == "Custom help"
    assert CliContract(help="").help == ""
    assert CliContract(show=False).show is False
    assert CliContract(show=True).show is True


# --- json_option / default_report / exit_code_attr ---------------------------


def test_json_option_defaults():
    o = json_option()
    assert (o.name, o.default) == ("json_out", False)
    assert o.help == "Emit machine-readable JSON instead of formatted output."
    assert o.annotation == Annotated[bool, Parameter(name="--json", negative="")]


def test_json_option_custom_flag_name_and_help():
    o = json_option("--json-out", name="as_json", help="JSON please")
    assert (o.name, o.help) == ("as_json", "JSON please")
    assert o.annotation == Annotated[bool, Parameter(name="--json-out", negative="")]


def test_default_report_writes_exact_f1_bytes(capsys):
    default_report(ValueError("bad thing"))
    cap = capsys.readouterr()
    assert cap.err == "Error (ValueError): bad thing\n"
    assert cap.out == ""


def test_exit_code_attr_int_attribute(capsys):
    h = exit_code_attr()
    assert h(OtherMyxcelErrorLike("m"), _ctx()) == 4
    assert _stderr(capsys) == "Error (OtherMyxcelErrorLike): m\n"


def test_exit_code_attr_through_mro_uses_subclass_code(capsys):
    codes = {MyxcelErrorLike: exit_code_attr()}
    assert _resolve_exit(ConfigErrorLike("c"), _ctx(), codes) == 2
    assert _stderr(capsys) == "Error (ConfigErrorLike): c\n"


class _NoAttr(Exception):
    pass


def _with_code(value: Any) -> Exception:
    e = Exception("m")
    e.exit_code = value  # type: ignore[attr-defined]
    return e


@pytest.mark.parametrize(
    "value", [0, 300, 256, -1, True, False, "SESSION_NOT_FOUND", 2.0, None]
)
def test_exit_code_attr_invalid_attribute_falls_back_to_default(value, capsys):
    assert exit_code_attr()(_with_code(value), _ctx()) == 1
    assert _stderr(capsys) == "Error (Exception): m\n"


def test_exit_code_attr_missing_attribute_falls_back(capsys):
    assert exit_code_attr()(_NoAttr("m"), _ctx()) == 1
    assert _stderr(capsys) == "Error (_NoAttr): m\n"


def test_exit_code_attr_custom_default_and_attr(capsys):
    h = exit_code_attr("code", default=7)
    e = Exception("m")
    e.code = 3  # type: ignore[attr-defined]
    assert h(e, _ctx()) == 3
    assert h(_NoAttr("m"), _ctx()) == 7
    capsys.readouterr()


def test_exit_code_attr_accepts_bounds(capsys):
    assert exit_code_attr()(_with_code(1), _ctx()) == 1
    assert exit_code_attr()(_with_code(255), _ctx()) == 255
    capsys.readouterr()


def test_exit_code_attr_custom_report_replaces_f1_line(capsys):
    def report(exc: BaseException) -> None:
        print(f"Error: {exc}", file=sys.stderr)

    assert exit_code_attr(report=report)(OtherMyxcelErrorLike("m"), _ctx()) == 4
    assert _stderr(capsys) == "Error: m\n"


def test_exit_code_attr_report_exception_goes_to_handler_failure_path(capsys, caplog):
    def report(exc: BaseException) -> None:
        raise RuntimeError("report broke")

    codes = {MyxcelErrorLike: exit_code_attr(report=report)}
    with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
        assert _resolve_exit(OtherMyxcelErrorLike("m"), _ctx(), codes) == 1
    assert _stderr(capsys) == "Error (OtherMyxcelErrorLike): m\n"
    assert any("exit handler" in r.getMessage() for r in caplog.records)


def test_exit_code_attr_report_must_be_callable():
    with pytest.raises(TypeError):
        exit_code_attr(report=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, 256, -3])
def test_exit_code_attr_default_must_be_1_to_255(bad):
    with pytest.raises(ValueError):
        exit_code_attr(default=bad)


@pytest.mark.parametrize("bad", [True, "1", 1.0])
def test_exit_code_attr_default_must_be_int(bad):
    with pytest.raises(TypeError):
        exit_code_attr(default=bad)  # type: ignore[arg-type]


def test_exit_code_attr_handler_never_reads_ctx(capsys):
    # A ctx that explodes on any attribute access proves the handler is ctx-free.
    class Boom:
        def __getattribute__(self, name: str) -> Any:
            raise AssertionError("ctx was read")

    assert exit_code_attr()(OtherMyxcelErrorLike("m"), Boom()) == 4  # type: ignore[arg-type]
    capsys.readouterr()


# --- CliContext --------------------------------------------------------------


def test_cli_context_defaults_are_independent():
    a, b = CliContext("t", "g t"), CliContext("t", "g t")
    assert (a.tool_name, a.command) == ("t", "g t")
    assert a.arguments == {} and a.options == {}
    a.arguments["x"] = 1
    a.options["y"] = 2
    assert b.arguments == {} and b.options == {}


# --- module hygiene (R10) ----------------------------------------------------


def test_module_scope_imports_are_stdlib_future_and_errors_only():
    tree = ast.parse(Path(cli_contract_module.__file__).read_text())
    stdlib = sys.stdlib_module_names
    seen: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import at module scope"
            mods = [node.module or ""]
        else:
            continue
        for m in mods:
            seen.append(m)
            top = m.split(".")[0]
            assert top in stdlib or m == "cisternal.registration.errors", m
    assert "cisternal.registration.errors" in seen


def test_module_imports_without_fastmcp():
    code = (
        "import sys; sys.modules['fastmcp'] = None; "
        "import cisternal.registration.cli_contract as m; "
        "assert m.CliContract and m.CliOption and m.CliContext"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


# ===========================================================================
# T3: the contract-path CLI callable and the public ``cli_command``
# ===========================================================================
#
# Spec: .praxia/docs/specs/261001_wire-cli-contract.md (rev 8), sections 5.2-5.4
# and tests 1, 2, 4-6, 8, 10-14, 16a (cli_command half + variant), 16c (contract
# half), 17, 19, 20, 20b, 22, 26-29 and 37.
#
# Every test goes through ``cli_command()`` and a hand-registered command; the
# ``wire()`` integration belongs to T4.


class MyErr(Exception):
    """Stand-in for a consumer's mapped error."""


class RecErr(Exception):
    """An error with the duck-typed ``to_result()`` the recovery leg looks for."""

    def to_result(self) -> dict:
        return {"error": "recovered-shape", "msg": str(self)}


_SEEN: list[Any] = []


@pytest.fixture(autouse=True)
def _clear_seen():
    _SEEN.clear()
    yield
    _SEEN.clear()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Spy on the ``emit_event`` that ``timed_command`` calls.

    Patched where ``timed_command`` looks it up (``cisternal.adapters.cli``), and
    proven live by ``test_events_spy_sees_a_successful_command`` below, so a test
    that asserts "zero events" cannot pass vacuously.
    """
    rec: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, **fields: Any) -> None:
        rec.append((name, fields))

    monkeypatch.setattr("cisternal.adapters.cli.emit_event", spy)
    return rec


def _cmd_events(events: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict]]:
    return [(n, f) for n, f in events if n.startswith("cli.cmd_")]


def _app_for(
    fn: Any,
    contract: CliContract | None = None,
    *,
    app: App | None = None,
    **kwargs: Any,
) -> App:
    """A fresh App with ``cli_command(fn, ...)`` registered under ``fn.__name__``."""
    app = app if app is not None else App(name="cli")
    app.command(name=fn.__name__)(cli_command(fn, contract=contract, **kwargs))
    return app


def _exit(app: App, argv: list[str]) -> int | None:
    return _run(app, argv)


def _err(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().err


# --- tools -------------------------------------------------------------------


def fails(msg: str = "boom") -> str:
    """Always raises ValueError(msg)."""
    raise ValueError(msg)


def adds(a: int, b: int = 1) -> dict:
    """Add two numbers.

    Args:
        a: The first addend.
        b: The second addend.
    """
    _SEEN.append((a, b))
    return {"sum": a + b}


def titled(title: str | None = None, audience: str = "lab") -> None:
    _SEEN.append((title, audience))


def sub_tool(x: int) -> int:
    if x < 0:
        raise MyErr(f"negative {x}")
    return x


def composite(x: int) -> int:
    """A hand-written composite that chains two tools."""
    return sub_tool(x) + sub_tool(x - 5)


async def aadd(a: int, b: int) -> dict:
    return {"sum": a + b}


async def acomposite(x: int) -> dict:
    first = await aadd(x, 1)
    if x > 1:
        raise MyErr("second leg failed")
    return {"first": first, "second": await aadd(x, 2)}


def with_extra(a: int, **extra: str) -> dict:
    return {"a": a, "extra": extra}


def mixed(pos, /, mid=5, *rest, kw="k", **extra):  # noqa: ANN001, ANN002, ANN003
    _SEEN.append((pos, mid, rest, kw, extra))


def pair(a=1, b=2):  # noqa: ANN001
    _SEEN.append((a, b))


def pos_only(a=1, b=2, /):  # noqa: ANN001
    _SEEN.append((a, b))


def star(a=1, *rest):  # noqa: ANN001, ANN002
    _SEEN.append((a, rest))


def needs_a(a: int, b: int = 0) -> None:
    _SEEN.append((a, b))


def envelope() -> dict:
    return {"error": "bad thing"}


def hidden_default(
    name: str, token: Annotated[str | None, Parameter(parse=False)] = None
) -> None:
    _SEEN.append((name, token))


def hidden_required(
    name: str, *, token: Annotated[str, Parameter(parse=False)]
) -> None:
    _SEEN.append((name, token))


# --- identity, signature and the no-contract delegation ----------------------


def test_contract_callable_identity_matches_the_tool():
    cmd = cli_command(adds, contract=CliContract())
    assert cmd.__name__ == "adds"
    assert cmd.__doc__ == adds.__doc__
    assert not hasattr(cmd, "__wrapped__")
    # No __qualname__/__module__ copied from the tool (the legacy closure copies none).
    assert cmd.__module__ == cli_contract_module.__name__
    assert cmd.__module__ != adds.__module__


def test_empty_contract_signature_equals_the_tool_signature():
    cmd = cli_command(adds, contract=CliContract())
    assert inspect.signature(cmd) == inspect.signature(adds)
    assert inspect.signature(cmd).return_annotation == "dict"


def test_annotations_are_resolved_objects_without_return():
    cmd = cli_command(adds, contract=CliContract(options=[json_option()]))
    assert cmd.__annotations__["a"] is int
    assert cmd.__annotations__["b"] is int
    assert "return" not in cmd.__annotations__
    assert all(not isinstance(v, str) for v in cmd.__annotations__.values())


def test_options_are_injected_keyword_only_before_var_keyword():
    opt = CliOption("flag", bool, False)
    cmd = cli_command(with_extra, contract=CliContract(options=[json_option(), opt]))
    params = inspect.signature(cmd).parameters
    assert list(params) == ["a", "json_out", "flag", "extra"]
    assert params["json_out"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["flag"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["json_out"].default is False
    assert params["extra"].kind is inspect.Parameter.VAR_KEYWORD
    # The return annotation survives the signature rewrite.
    assert inspect.signature(cmd).return_annotation == "dict"
    # The tool's own signature is untouched.
    assert list(inspect.signature(with_extra).parameters) == ["a", "extra"]


def test_options_are_appended_after_keyword_only_tool_parameters():
    cmd = cli_command(mixed, contract=CliContract(options=[json_option()]))
    assert list(inspect.signature(cmd).parameters) == [
        "pos",
        "mid",
        "rest",
        "kw",
        "json_out",
        "extra",
    ]


def test_option_help_wraps_the_annotation_in_parameter_help():
    opt = CliOption("flag", bool, False, help="Flag help")
    cmd = cli_command(adds, contract=CliContract(options=[opt]))
    hint = cmd.__annotations__["flag"]
    assert typing_get_origin(hint) is Annotated
    assert typing_get_args(hint)[0] is bool
    helps = [m.help for m in typing_get_args(hint)[1:] if isinstance(m, Parameter)]
    assert helps == ["Flag help"]
    # The wrapped hint is what the signature carries, too.
    assert inspect.signature(cmd).parameters["flag"].annotation == hint


def test_option_without_help_keeps_its_annotation_unwrapped():
    opt = CliOption("flag", bool, False)
    cmd = cli_command(adds, contract=CliContract(options=[opt]))
    assert cmd.__annotations__["flag"] is bool


def test_no_contract_delegates_to_make_cli_cmd(monkeypatch: pytest.MonkeyPatch):
    from cisternal.registration import wired

    calls: list[tuple[Any, str, dict[str, Any]]] = []
    sentinel = object()

    def spy(original_fn: Any, cmd_name: str, **kwargs: Any) -> Any:
        calls.append((original_fn, cmd_name, kwargs))
        return sentinel

    monkeypatch.setattr(wired, "_make_cli_cmd", spy)
    recovery = (lambda e: False, lambda: None)
    out = cli_command(adds, name="custom", recovery=recovery, telemetry=False)
    assert out is sentinel
    assert calls == [(adds, "custom", {"recovery": recovery, "telemetry": False})]


def test_no_contract_is_todays_f1_closure(capsys):
    app = _app_for(fails)
    assert _exit(app, ["fails", "--msg", "x"]) == 1
    assert _err(capsys) == "Error (ValueError): x\n"
    cmd = cli_command(adds)
    assert inspect.signature(cmd) == inspect.signature(adds)
    assert not hasattr(cmd, "__wrapped__")


def test_cli_command_does_not_apply_help_or_show():
    """``help``/``show`` belong to registration, which cli_command does not do."""
    app = _app_for(adds, CliContract(help="Custom help", show=False))
    assert "Custom help" not in (app["adds"].help or "")


# --- test 1, 2: mapping ------------------------------------------------------


def test_1_int_mapping_exits_with_the_code_and_the_f1_line(capsys):
    app = _app_for(fails, CliContract(exit_codes={ValueError: 3}))
    assert _exit(app, ["fails", "--msg", "msg"]) == 3
    captured = capsys.readouterr()
    assert captured.err == "Error (ValueError): msg\n"
    assert captured.out == ""


def test_2_handler_renders_its_own_report_and_picks_the_code(capsys):
    seen: list[Any] = []

    def handler(exc: Any, ctx: CliContext) -> int:
        seen.append((str(exc), ctx.tool_name, ctx.command))
        print(f"HANDLED {exc}", file=sys.stderr)
        return 7

    app = _app_for(fails, CliContract(exit_codes={ValueError: handler}))
    assert _exit(app, ["fails", "--msg", "msg"]) == 7
    captured = capsys.readouterr()
    assert captured.err == "HANDLED msg\n"  # and no F1 line
    assert seen == [("msg", "fails", "fails")]


def test_tool_name_and_command_are_configurable():
    seen: list[CliContext] = []

    def handler(exc: Any, ctx: CliContext) -> int:
        seen.append(ctx)
        return 2

    contract = CliContract(exit_codes={ValueError: handler})
    app = _app_for(fails, contract, name="my_tool", command="grp fails")
    assert _exit(app, ["fails"]) == 2
    assert (seen[0].tool_name, seen[0].command) == ("my_tool", "grp fails")


# --- test 4: CLI-only options ------------------------------------------------


def test_4_json_option_reaches_the_formatter_but_not_the_tool(capsys):
    seen: list[dict[str, Any]] = []

    def fmt(result: Any, ctx: CliContext) -> None:
        seen.append(dict(ctx.options))
        print(f"RESULT {result}")

    app = _app_for(adds, CliContract(format_success=fmt, options=[json_option()]))
    assert _exit(app, ["adds", "2", "--json"]) == 0
    assert _exit(app, ["adds", "2"]) == 0
    assert seen == [{"json_out": True}, {"json_out": False}]
    # ``adds`` has a strict signature: a leaked ``json_out`` kwarg would have
    # raised TypeError and exited 1.
    assert _SEEN == [(2, 1), (2, 1)]
    out = capsys.readouterr().out
    assert out.count("RESULT {'sum': 3}") == 2


def test_4_json_option_has_no_negative_flag():
    app = _app_for(adds, CliContract(options=[json_option()]))
    with pytest.raises(Exception, match="no-json"):
        app(["adds", "2", "--no-json"], exit_on_error=False)


def test_4_var_keyword_tool_keeps_options_out_of_extra():
    seen: list[CliContext] = []

    def fmt(result: Any, ctx: CliContext) -> None:
        seen.append(ctx)

    app = _app_for(with_extra, CliContract(format_success=fmt, options=[json_option()]))
    assert _exit(app, ["with_extra", "1", "--json", "--foo", "x"]) == 0
    ctx = seen[0]
    assert ctx.options == {"json_out": True}
    assert ctx.arguments["a"] == 1
    assert ctx.arguments["extra"] == {"foo": "x"}
    assert "json_out" not in ctx.arguments["extra"]


def test_4_help_lists_the_option_help_texts(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    opt = CliOption(
        "working_dir",
        Path | None,
        None,
        help="Run as if started in this directory.",
    )
    app = _app_for(adds, CliContract(options=[json_option(), opt]))
    _exit(app, ["adds", "--help"])
    out = _stdout(capsys)
    assert "Emit machine-readable JSON instead of formatted output." in out
    assert "Run as if started in this directory." in out
    assert "--json" in out
    assert "--working-dir" in out


def test_4_help_passes_the_docstring_through(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    app = _app_for(adds, CliContract(options=[json_option()]))
    _exit(app, ["adds", "--help"])
    out = _stdout(capsys)
    assert "Add two numbers." in out
    assert "The first addend." in out


# --- test 5: formatter -------------------------------------------------------


def test_5_formatter_returning_none_exits_0_with_only_its_output(capsys):
    def fmt(result: Any, ctx: CliContext) -> None:
        print(f"FORMATTED {result['sum']}")

    app = _app_for(adds, CliContract(format_success=fmt))
    assert _exit(app, ["adds", "4", "--b", "5"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "FORMATTED 9\n"
    assert captured.err == ""


def test_formatter_return_value_goes_back_to_cyclopts(capsys):
    app = _app_for(adds, CliContract(format_success=lambda r, c: r["sum"] + 40))
    # The default result_action exits with an int result as the exit code.
    assert _exit(app, ["adds", "1", "--b", "1"]) == 42


def test_no_formatter_returns_the_raw_result(capsys):
    app = _app_for(adds, CliContract())
    assert _exit(app, ["adds", "3"]) == 0
    assert "sum" in _stdout(capsys)


def test_positional_arguments_reach_the_tool_through_binding():
    """A18: cyclopts passes positionally supplied arguments in ``args``."""
    app = _app_for(adds, CliContract(options=[json_option()]))
    assert _exit(app, ["adds", "7", "8"]) == 0
    assert _SEEN == [(7, 8)]


# --- test 6: prepare ---------------------------------------------------------


def _prompting_prepare(prompt: Any) -> Any:
    def prepare(ctx: CliContext) -> None:
        if ctx.arguments.get("title") is None:
            ctx.arguments["title"] = prompt()

    return prepare


def test_6a_prepare_leaves_a_supplied_argument_alone():
    calls: list[int] = []
    prompt = lambda: calls.append(1) or "prompted"  # noqa: E731
    app = _app_for(titled, CliContract(prepare=_prompting_prepare(prompt)))
    assert _exit(app, ["titled", "--title", "x"]) == 0
    assert calls == []
    assert _SEEN == [("x", "lab")]


def test_6b_prepare_fills_the_gap_before_a_supplied_later_argument():
    calls: list[int] = []
    prompt = lambda: calls.append(1) or "prompted"  # noqa: E731
    app = _app_for(titled, CliContract(prepare=_prompting_prepare(prompt)))
    assert _exit(app, ["titled", "--audience", "z"]) == 0
    assert calls == [1]
    assert _SEEN == [("prompted", "z")]


def test_6c_prepare_fills_a_missing_argument_with_no_arguments():
    calls: list[int] = []
    prompt = lambda: calls.append(1) or "prompted"  # noqa: E731
    app = _app_for(titled, CliContract(prepare=_prompting_prepare(prompt)))
    assert _exit(app, ["titled"]) == 0
    assert calls == [1]
    assert _SEEN == [("prompted", "lab")]


def test_6_prepare_sees_defaults_applied():
    captured: list[dict[str, Any]] = []
    contract = CliContract(prepare=lambda ctx: captured.append(dict(ctx.arguments)))
    app = _app_for(titled, contract)
    assert _exit(app, ["titled"]) == 0
    assert captured == [{"title": None, "audience": "lab"}]


def test_6_positional_only_var_positional_and_var_keyword_round_trip():
    captured: list[dict[str, Any]] = []
    contract = CliContract(prepare=lambda ctx: captured.append(dict(ctx.arguments)))
    cmd = cli_command(mixed, contract=contract)

    cmd(1, 2, 3, 4, kw="z", foo="bar")
    assert captured[-1] == {
        "pos": 1,
        "mid": 2,
        "rest": (3, 4),
        "kw": "z",
        "extra": {"foo": "bar"},
    }
    assert _SEEN[-1] == (1, 2, (3, 4), "z", {"foo": "bar"})

    cmd(9)
    assert captured[-1] == {"pos": 9, "mid": 5, "rest": (), "kw": "k", "extra": {}}
    assert _SEEN[-1] == (9, 5, (), "k", {})


def test_6_prepare_deleting_a_defaulted_argument_falls_back_to_its_default():
    def prepare(ctx: CliContext) -> None:
        del ctx.arguments["a"]

    cmd = cli_command(pair, contract=CliContract(prepare=prepare))
    cmd(5, 6)
    assert _SEEN == [(1, 6)]


def test_6_prepare_may_replace_every_value():
    def prepare(ctx: CliContext) -> None:
        ctx.arguments["a"] = 100

    cmd = cli_command(needs_a, contract=CliContract(prepare=prepare))
    cmd(1, 2)
    assert _SEEN == [(100, 2)]


# --- _rebind (spec 5.2) ------------------------------------------------------


def test_rebind_places_arguments_by_kind():
    from cisternal.registration.cli_contract import _rebind

    sig = inspect.signature(mixed)
    b = _rebind(
        sig,
        {"pos": 1, "mid": 2, "rest": (3, 4), "kw": "z", "extra": {"foo": "bar"}},
    )
    assert b.args == (1, 2, 3, 4)
    assert b.kwargs == {"kw": "z", "foo": "bar"}


def test_rebind_drops_an_empty_var_positional_after_a_gap():
    from cisternal.registration.cli_contract import _rebind

    sig = inspect.signature(star)
    b = _rebind(sig, {"rest": ()})
    assert b.arguments == {"a": 1, "rest": ()}


def test_rebind_unknown_key():
    from cisternal.registration.cli_contract import _rebind

    with pytest.raises(TypeError, match="prepare set unknown argument 'zzz'"):
        _rebind(inspect.signature(adds), {"a": 1, "zzz": 2})


def test_rebind_missing_required():
    from cisternal.registration.cli_contract import _rebind

    with pytest.raises(TypeError, match="prepare removed required argument 'a'"):
        _rebind(inspect.signature(adds), {"b": 2})


def test_rebind_positional_only_after_a_gap():
    from cisternal.registration.cli_contract import _rebind

    with pytest.raises(
        TypeError, match="prepare removed argument 'a' ahead of 'b'"
    ):
        _rebind(inspect.signature(pos_only), {"b": 3})


def test_rebind_var_positional_after_a_gap():
    from cisternal.registration.cli_contract import _rebind

    with pytest.raises(
        TypeError, match="prepare removed argument 'a' ahead of 'rest'"
    ):
        _rebind(inspect.signature(star), {"rest": (5,)})


def test_rebind_after_a_gap_a_positional_or_keyword_goes_by_name():
    from cisternal.registration.cli_contract import _rebind

    b = _rebind(inspect.signature(pair), {"b": 7})
    assert b.arguments == {"a": 1, "b": 7}
    assert b.kwargs == {} and b.args == (1, 7)


# --- test 8: composite -------------------------------------------------------


def test_8_composite_exception_maps_through_the_contract(capsys):
    app = _app_for(composite, CliContract(exit_codes={MyErr: 4}))
    assert _exit(app, ["composite", "2"]) == 4
    assert _err(capsys) == "Error (MyErr): negative -3\n"
    assert _exit(app, ["composite", "7"]) == 9  # int result is the exit code (A6)


# --- test 10, 11: async and recovery -----------------------------------------


def test_10_async_tool_formatter_receives_the_awaited_result(capsys):
    got: list[Any] = []

    def fmt(result: Any, ctx: CliContext) -> None:
        got.append(result)

    app = _app_for(aadd, CliContract(format_success=fmt))
    assert _exit(app, ["aadd", "4", "5"]) == 0
    assert got == [{"sum": 9}]


def test_11_recovery_to_result_reaches_the_formatter_not_exit_codes(capsys):
    def thrower(x: int = 0) -> dict:
        raise RecErr("nope")

    got: list[Any] = []
    contract = CliContract(
        format_success=lambda r, c: got.append(r),
        exit_codes={RecErr: 9},
    )
    app = _app_for(
        thrower, contract, recovery=(lambda exc: False, lambda: None)
    )
    assert _exit(app, ["thrower"]) == 0
    assert got == [{"error": "recovered-shape", "msg": "nope"}]
    assert _err(capsys) == ""


def test_11_without_recovery_the_same_error_takes_the_exit_code_route(capsys):
    def thrower(x: int = 0) -> dict:
        raise RecErr("nope")

    app = _app_for(thrower, CliContract(exit_codes={RecErr: 9}))
    assert _exit(app, ["thrower"]) == 9
    assert _err(capsys) == "Error (RecErr): nope\n"


# --- tests 12-14: negative controls ------------------------------------------


def test_12_unmapped_exception_is_the_f1_line_and_exit_1(capsys):
    app = _app_for(fails, CliContract(exit_codes={KeyError: 9, MyErr: 4}))
    assert _exit(app, ["fails", "--msg", "m"]) == 1
    assert _err(capsys) == "Error (ValueError): m\n"


def test_12_empty_contract_is_also_exit_1(capsys):
    app = _app_for(fails, CliContract())
    assert _exit(app, ["fails"]) == 1
    assert _err(capsys) == "Error (ValueError): boom\n"


def test_12b_a_bind_failure_is_the_f1_line_and_exit_1(capsys):
    cmd = cli_command(adds, contract=CliContract())
    with pytest.raises(SystemExit) as excinfo:
        cmd(bogus=1)
    assert excinfo.value.code == 1
    err = _err(capsys)
    assert err.startswith("Error (TypeError): ")
    assert err.endswith("\n") and err.count("\n") == 1


def test_12b_a_mapped_type_error_handler_sees_empty_arguments():
    seen: list[CliContext] = []

    def handler(exc: Any, ctx: CliContext) -> int:
        seen.append(ctx)
        return 6

    cmd = cli_command(adds, contract=CliContract(exit_codes={TypeError: handler}))
    with pytest.raises(SystemExit) as excinfo:
        cmd(bogus=1)
    assert excinfo.value.code == 6
    assert seen[0].arguments == {}


def test_12b_options_are_popped_before_the_bind_failure():
    seen: list[CliContext] = []

    def handler(exc: Any, ctx: CliContext) -> int:
        seen.append(ctx)
        return 6

    contract = CliContract(
        options=[json_option()], exit_codes={TypeError: handler}
    )
    cmd = cli_command(adds, contract=contract)
    with pytest.raises(SystemExit):
        cmd(bogus=1, json_out=True)
    assert seen[0].arguments == {}
    assert seen[0].options == {"json_out": True}


def test_13_system_exit_from_the_tool_is_never_remapped(capsys):
    def exits(code: int = 4) -> None:
        raise SystemExit(code)

    app = _app_for(exits, CliContract(exit_codes={Exception: 7}))
    assert _exit(app, ["exits"]) == 4
    assert _err(capsys) == ""


def test_14_keyboard_interrupt_is_not_caught_by_exception_mapping():
    def interrupted() -> None:
        raise KeyboardInterrupt

    cmd = cli_command(interrupted, contract=CliContract(exit_codes={Exception: 7}))
    with pytest.raises(KeyboardInterrupt):
        cmd()


# --- test 17: failing handlers -----------------------------------------------


def test_17_a_raising_handler_falls_back_to_the_f1_line(capsys, caplog):
    def handler(exc: Any, ctx: CliContext) -> int:
        raise RuntimeError("handler broke")

    app = _app_for(fails, CliContract(exit_codes={ValueError: handler}))
    with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
        assert _exit(app, ["fails", "--msg", "m"]) == 1
    assert _err(capsys) == "Error (ValueError): m\n"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.parametrize("bad", [True, -1], ids=["bool", "negative"])
def test_17_a_bad_handler_return_is_exit_1_with_a_warning(bad, caplog):
    app = _app_for(fails, CliContract(exit_codes={ValueError: lambda e, c: bad}))
    with caplog.at_level(logging.WARNING, logger="cisternal.registration"):
        assert _exit(app, ["fails"]) == 1
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# --- telemetry ---------------------------------------------------------------


def test_events_spy_sees_a_successful_command(events):
    """Positive control for every "zero events" assertion below."""
    app = _app_for(adds, CliContract())
    assert _exit(app, ["adds", "1"]) == 0
    assert [n for n, _ in _cmd_events(events)] == ["cli.cmd_start", "cli.cmd_end"]
    assert _cmd_events(events)[1][1]["ok"] is True
    assert _cmd_events(events)[0][1]["cmd"] == "adds"


def test_telemetry_cmd_is_the_tool_name(events):
    app = _app_for(adds, CliContract(), name="custom")
    assert _exit(app, ["adds", "1"]) == 0
    assert {f["cmd"] for _, f in _cmd_events(events)} == {"custom"}


def test_19_a_mapped_failure_is_recorded_with_the_original_exception_type(events):
    app = _app_for(fails, CliContract(exit_codes={ValueError: 3}))
    assert _exit(app, ["fails"]) == 3
    ends = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"]
    assert len(ends) == 1
    assert ends[0]["exc_type"] == "ValueError"
    assert ends[0]["ok"] is False


def test_19_a_handler_chosen_exit_code_is_not_in_the_event(events):
    """R1: the span closes before the handler runs."""
    app = _app_for(fails, CliContract(exit_codes={ValueError: lambda e, c: 3}))
    assert _exit(app, ["fails"]) == 3
    end = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"][0]
    assert "exit_code" not in end


def test_20_a_formatter_crash_is_recorded_with_the_formatters_exception(
    events, capsys
):
    def fmt(result: Any, ctx: CliContext) -> None:
        raise KeyError("fmt-broke")

    app = _app_for(adds, CliContract(format_success=fmt))
    assert _exit(app, ["adds", "1"]) == 1
    ends = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"]
    assert len(ends) == 1
    assert ends[0]["ok"] is False
    assert ends[0]["exc_type"] == "KeyError"
    assert _err(capsys).startswith("Error (KeyError): ")


def test_20b_prepare_raising_emits_no_events(events, capsys):
    def prepare(ctx: CliContext) -> None:
        raise RuntimeError("prepare broke")

    app = _app_for(adds, CliContract(prepare=prepare))
    assert _exit(app, ["adds", "1"]) == 1
    assert _err(capsys) == "Error (RuntimeError): prepare broke\n"
    assert _cmd_events(events) == []
    assert _SEEN == []


def test_20b_prepare_exiting_emits_no_events(events):
    def prepare(ctx: CliContext) -> None:
        sys.exit(3)

    app = _app_for(adds, CliContract(prepare=prepare))
    assert _exit(app, ["adds", "1"]) == 3
    assert _cmd_events(events) == []


def test_20b_prepare_setting_an_unknown_argument(events, capsys):
    def prepare(ctx: CliContext) -> None:
        ctx.arguments["bogus"] = 1

    app = _app_for(adds, CliContract(prepare=prepare))
    assert _exit(app, ["adds", "1"]) == 1
    assert _err(capsys) == "Error (TypeError): prepare set unknown argument 'bogus'\n"
    assert _cmd_events(events) == []
    assert _SEEN == []


def test_20b_prepare_deleting_a_required_argument(events, capsys):
    def prepare(ctx: CliContext) -> None:
        del ctx.arguments["a"]

    app = _app_for(adds, CliContract(prepare=prepare))
    assert _exit(app, ["adds", "1"]) == 1
    assert (
        _err(capsys) == "Error (TypeError): prepare removed required argument 'a'\n"
    )
    assert _cmd_events(events) == []
    assert _SEEN == []


def test_20b_positional_only_after_a_gap(events, capsys):
    def prepare(ctx: CliContext) -> None:
        del ctx.arguments["a"]

    app = _app_for(pos_only, CliContract(prepare=prepare))
    assert _exit(app, ["pos_only", "3", "4"]) == 1
    assert (
        _err(capsys)
        == "Error (TypeError): prepare removed argument 'a' ahead of 'b'\n"
    )
    assert _cmd_events(events) == []
    assert _SEEN == []


def test_20b_var_positional_after_a_gap(events, capsys):
    def prepare(ctx: CliContext) -> None:
        assert ctx.arguments["rest"] == ("6",)
        del ctx.arguments["a"]

    app = _app_for(star, CliContract(prepare=prepare))
    assert _exit(app, ["star", "5", "6"]) == 1
    assert (
        _err(capsys)
        == "Error (TypeError): prepare removed argument 'a' ahead of 'rest'\n"
    )
    assert _cmd_events(events) == []
    assert _SEEN == []


def test_20b_prepare_runs_before_the_span_opens(events):
    def prepare(ctx: CliContext) -> None:
        events.append(("MARKER", {}))

    app = _app_for(adds, CliContract(prepare=prepare))
    assert _exit(app, ["adds", "1"]) == 0
    names = [n for n, _ in events]
    assert names == ["MARKER", "cli.cmd_start", "cli.cmd_end"]


def test_21_telemetry_false_with_a_contract_emits_no_events(events):
    app = _app_for(adds, CliContract(format_success=lambda r, c: None), telemetry=False)
    assert _exit(app, ["adds", "1"]) == 0
    assert _cmd_events(events) == []
    assert _SEEN == [(1, 1)]


def test_21_telemetry_false_still_maps_failures(events, capsys):
    app = _app_for(fails, CliContract(exit_codes={ValueError: 3}), telemetry=False)
    assert _exit(app, ["fails", "--msg", "m"]) == 3
    assert _err(capsys) == "Error (ValueError): m\n"
    assert _cmd_events(events) == []


# --- test 22: a tool the consumer already instrumented -----------------------

from cisternal.adapters.cli import timed_command  # noqa: E402  (test-local import)


@timed_command("handmade")
def hand_timed(a: int = 1) -> dict:
    return {"a": a}


def test_22_a_cisternal_timed_tool_emits_exactly_one_start_end_pair(events):
    assert hand_timed.__name__ == "hand_timed"  # functools.wraps kept the name
    seen: list[Any] = []
    contract = CliContract(format_success=lambda r, c: seen.append(r))
    app = _app_for(hand_timed, contract)
    assert _exit(app, ["hand_timed"]) == 0
    assert seen == [{"a": 1}]
    cmd_events = _cmd_events(events)
    assert [n for n, _ in cmd_events] == ["cli.cmd_start", "cli.cmd_end"]
    # The tool's own span, under its own name, not the wire-level name.
    assert {f["cmd"] for _, f in cmd_events} == {"handmade"}


def test_22_a_formatter_crash_in_the_cisternal_timed_branch_is_untimed(
    events, capsys
):
    def fmt(result: Any, ctx: CliContext) -> None:
        raise KeyError("fmt-broke")

    app = _app_for(hand_timed, CliContract(format_success=fmt))
    assert _exit(app, ["hand_timed"]) == 1
    assert _err(capsys).startswith("Error (KeyError): ")
    cmd_events = _cmd_events(events)
    # One pair, from the tool's own span, which finished fine: no ok=False event.
    assert [n for n, _ in cmd_events] == ["cli.cmd_start", "cli.cmd_end"]
    assert cmd_events[1][1]["ok"] is True


def test_22_a_formatter_sys_exit_in_the_cisternal_timed_branch_is_untimed(events):
    def fmt(result: Any, ctx: CliContext) -> None:
        sys.exit(5)

    app = _app_for(hand_timed, CliContract(format_success=fmt))
    assert _exit(app, ["hand_timed"]) == 5
    cmd_events = _cmd_events(events)
    assert [n for n, _ in cmd_events] == ["cli.cmd_start", "cli.cmd_end"]
    assert cmd_events[1][1]["ok"] is True


# --- test 26: exit_code_attr through the CLI ---------------------------------


def _raiser(exc: BaseException) -> Any:
    def thrower() -> None:
        raise exc

    return thrower


def _code_error(value: Any) -> Exception:
    err = MyxcelErrorLike("the message")
    err.exit_code = value  # type: ignore[attr-defined]
    return err


def test_26_exit_code_attr_int_attribute(capsys):
    app = _app_for(
        _raiser(_code_error(4)),
        CliContract(exit_codes={MyxcelErrorLike: exit_code_attr()}),
        name="thrower",
    )
    assert _exit(app, ["thrower"]) == 4
    assert _err(capsys) == "Error (MyxcelErrorLike): the message\n"


@pytest.mark.parametrize(
    "value", [0, 300, True, "SESSION_NOT_FOUND", None], ids=repr
)
def test_26_exit_code_attr_invalid_value_falls_back_to_the_default(value, capsys):
    app = _app_for(
        _raiser(_code_error(value)),
        CliContract(exit_codes={MyxcelErrorLike: exit_code_attr()}),
        name="thrower",
    )
    assert _exit(app, ["thrower"]) == 1
    assert _err(capsys) == "Error (MyxcelErrorLike): the message\n"


def test_26_exit_code_attr_missing_attribute_falls_back(capsys):
    class NoAttr(Exception):
        pass

    app = _app_for(
        _raiser(NoAttr("m")),
        CliContract(exit_codes={NoAttr: exit_code_attr()}),
        name="thrower",
    )
    assert _exit(app, ["thrower"]) == 1
    assert _err(capsys) == "Error (NoAttr): m\n"


def test_26_exit_code_attr_custom_report_replaces_the_f1_line(capsys):
    from rich.console import Console

    def report(exc: BaseException) -> None:
        Console(stderr=True, no_color=True, color_system=None).print(
            f"[red]Error:[/red] {exc}"
        )

    app = _app_for(
        _raiser(_code_error(4)),
        CliContract(exit_codes={MyxcelErrorLike: exit_code_attr(report=report)}),
        name="thrower",
    )
    assert _exit(app, ["thrower"]) == 4
    assert _err(capsys) == "Error: the message\n"


def test_26_exit_code_attr_report_must_be_callable():
    with pytest.raises(TypeError):
        exit_code_attr(report=None)  # type: ignore[arg-type]


def test_26_exit_code_attr_resolves_subclass_code_by_mro(capsys):
    err = ConfigErrorLike("cfg")
    err.exit_code = 2  # type: ignore[attr-defined]
    app = _app_for(
        _raiser(err),
        CliContract(exit_codes={MyxcelErrorLike: exit_code_attr()}),
        name="thrower",
    )
    assert _exit(app, ["thrower"]) == 2


# --- test 27: a handler that returns None ------------------------------------


def test_27_handler_returning_none_is_the_f1_line_and_exit_1(capsys):
    app = _app_for(fails, CliContract(exit_codes={ValueError: lambda e, c: None}))
    assert _exit(app, ["fails", "--msg", "m"]) == 1
    assert _err(capsys) == "Error (ValueError): m\n"


def test_27_handler_may_return_zero_for_handled_success(capsys):
    app = _app_for(fails, CliContract(exit_codes={ValueError: lambda e, c: 0}))
    assert _exit(app, ["fails"]) == 0
    assert _err(capsys) == ""


# --- tests 28, 29: result-shaped failures ------------------------------------


def _envelope_formatter(result: Any, ctx: CliContext) -> None:
    if result.get("error"):
        sys.exit(5)
    print("fine")


def test_28_formatter_sys_exit_maps_an_envelope_under_the_default_app(events):
    app = _app_for(envelope, CliContract(format_success=_envelope_formatter))
    assert _exit(app, ["envelope"]) == 5
    end = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"]
    assert len(end) == 1
    assert end[0]["ok"] is False
    assert end[0]["exit_code"] == 5


def _dict_only_action(result: Any) -> None:
    if isinstance(result, dict):
        print("DICT", result)
    return None


def test_29_formatter_sys_exit_works_under_a_callable_result_action(events):
    inner = App(name="cli", result_action=_dict_only_action)
    app = _app_for(envelope, CliContract(format_success=_envelope_formatter), app=inner)
    assert _exit(app, ["envelope"]) == 5
    end = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"]
    assert len(end) == 1
    assert end[0]["ok"] is False
    assert end[0]["exit_code"] == 5


def test_29_control_a_returned_int_is_swallowed_by_a_callable_result_action():
    """A19: documents why formatters must ``sys.exit`` rather than return a code."""
    inner = App(name="cli", result_action=_dict_only_action)
    app = _app_for(envelope, CliContract(format_success=lambda r, c: 5), app=inner)
    assert _exit(app, ["envelope"]) is None  # no SystemExit: the process would exit 0


# --- test 37: async composite through cli_command ----------------------------


def test_37_async_composite_failure_maps_to_the_contract_code(capsys):
    app = _app_for(acomposite, CliContract(exit_codes={MyErr: 4}))
    assert _exit(app, ["acomposite", "5"]) == 4
    assert _err(capsys) == "Error (MyErr): second leg failed\n"


def test_37_async_composite_success_reaches_the_formatter():
    got: list[Any] = []
    app = _app_for(
        acomposite, CliContract(format_success=lambda r, c: got.append(r))
    )
    assert _exit(app, ["acomposite", "1"]) == 0
    assert got == [{"first": {"sum": 2}, "second": {"sum": 3}}]


# --- A26: hidden (parse=False) arguments through the builder -----------------


def test_hidden_defaulted_argument_is_filled_by_prepare():
    seen: list[Any] = []

    def prepare(ctx: CliContext) -> None:
        seen.append(ctx.arguments["token"])
        ctx.arguments["token"] = "from-env"

    app = _app_for(hidden_default, CliContract(prepare=prepare))
    assert _exit(app, ["hidden_default", "x"]) == 0
    assert seen == [None]
    assert _SEEN == [("x", "from-env")]
    with pytest.raises(Exception, match="token"):
        app(["hidden_default", "x", "--token", "t"], exit_on_error=False)


def test_hidden_required_argument_is_absent_until_prepare_sets_it():
    seen: list[bool] = []

    def prepare(ctx: CliContext) -> None:
        seen.append("token" in ctx.arguments)
        ctx.arguments["token"] = "from-env"

    app = _app_for(hidden_required, CliContract(prepare=prepare))
    assert _exit(app, ["hidden_required", "x"]) == 0
    assert seen == [False]
    assert _SEEN == [("x", "from-env")]
    with pytest.raises(Exception, match="token"):
        app(["hidden_required", "x", "--token", "t"], exit_on_error=False)


def test_hidden_required_argument_unset_by_prepare_never_reaches_the_tool(
    events, capsys
):
    app = _app_for(hidden_required, CliContract())
    assert _exit(app, ["hidden_required", "x"]) == 1
    assert (
        _err(capsys)
        == "Error (TypeError): prepare removed required argument 'token'\n"
    )
    assert _cmd_events(events) == []
    assert _SEEN == []


# --- test 16a: collisions (cli_command half + variant) -----------------------

from tests.fixtures import collision_tools, collision_tools_plain  # noqa: E402

_NO_X = Annotated[bool, Parameter(name="--no-x", negative="")]
_OFF = Annotated[bool, Parameter(name="--off", negative="")]
_EMPTY_ITEMS = Annotated[bool, Parameter(name="--empty-items", negative="")]
_NO_FOO = Annotated[bool, Parameter(name="--no-foo", negative="")]
_NO_FLAG = Annotated[bool, Parameter(name="--no-flag", negative="")]

# (case id, tool name, options). Each must raise CisternalWireError naming the tool.
_COLLISIONS: list[tuple[str, str, list[CliOption]]] = [
    ("identifier", "tool_ident", [json_option()]),
    ("flag-json", "tool_json", [json_option()]),
    ("derived-negative", "tool_x", [CliOption("x2", _NO_X, False)]),
    ("explicit-json", "tool_explicit_json", [json_option()]),
    ("user-negative", "tool_user_negative", [CliOption("o", _OFF, False)]),
    ("empty-prefix", "tool_items", [CliOption("e", _EMPTY_ITEMS, False)]),
    ("option-negative", "tool_no_x2", [CliOption("x2", bool, False)]),
    ("hyphenless-name", "tool_foo_named", [CliOption("g", _NO_FOO, False)]),
    ("unannotated-default", "tool_unannotated_flag", [CliOption("g", _NO_FLAG, False)]),
    ("any-default", "tool_any_x", [CliOption("g", _NO_X, False)]),
]

_COLLISION_MODULES = [
    pytest.param(collision_tools_plain, id="real-objects"),
    pytest.param(collision_tools, id="future-annotations"),
]


@pytest.mark.parametrize("module", _COLLISION_MODULES)
@pytest.mark.parametrize(
    ("tool_name", "options"),
    [pytest.param(t, o, id=i) for i, t, o in _COLLISIONS],
)
def test_16a_collision_raises_naming_the_tool(module, tool_name, options):
    fn = getattr(module, tool_name)
    with pytest.raises(CisternalWireError) as excinfo:
        cli_command(fn, contract=CliContract(options=options))
    assert tool_name in str(excinfo.value)


@pytest.mark.parametrize("module", _COLLISION_MODULES)
def test_16a_the_same_tools_build_without_options(module):
    for _, tool_name, _ in _COLLISIONS:
        cli_command(getattr(module, tool_name), contract=CliContract())


@pytest.mark.parametrize("module", _COLLISION_MODULES)
def test_16a_collision_message_names_the_flag(module):
    with pytest.raises(CisternalWireError, match="--json"):
        cli_command(module.tool_json, contract=CliContract(options=[json_option()]))


def test_16a_two_options_claiming_one_flag_collide():
    contract = CliContract(
        options=[
            json_option(),
            json_option(name="other", flag="--json"),
        ]
    )
    with pytest.raises(CisternalWireError, match="--json"):
        cli_command(adds, contract=contract)


@pytest.mark.parametrize("module", _COLLISION_MODULES)
def test_16a_star_args_named_json_does_not_collide(module):
    cmd = cli_command(module.tool_star_json, contract=CliContract(options=[json_option()]))
    assert "json_out" in inspect.signature(cmd).parameters


@pytest.mark.parametrize("module", _COLLISION_MODULES)
def test_16a_short_flags_are_not_compared(module):
    short = CliOption("jj", Annotated[bool, Parameter(name="-j", negative="")], False)
    cli_command(module.tool_short_j, contract=CliContract(options=[short]))


@pytest.mark.parametrize("module", _COLLISION_MODULES)
def test_16a_a_parse_false_parameter_claims_no_flag(module):
    chdir = CliOption(
        "chdir_to",
        Annotated[Path | None, Parameter(name="--working-dir")],
        None,
    )
    seen: list[Any] = []

    def prepare(ctx: CliContext) -> None:
        ctx.arguments["working_dir"] = str(ctx.options["chdir_to"] or ".")

    contract = CliContract(
        options=[chdir],
        prepare=prepare,
        format_success=lambda r, c: seen.append(r),
    )
    app = _app_for(module.tool_parse_false, contract)
    assert _exit(app, ["tool_parse_false", "--working-dir", "/x"]) == 0
    assert seen == ["/x"]


def test_16a_an_identifier_collision_applies_even_to_a_parse_false_parameter():
    clash = CliOption("working_dir", str, "")
    with pytest.raises(CisternalWireError, match="working_dir"):
        cli_command(
            collision_tools_plain.tool_parse_false,
            contract=CliContract(options=[clash]),
        )


def test_16a_identifier_check_covers_var_positional_and_var_keyword():
    for opt_name, fn in [("rest", mixed), ("extra", mixed), ("pos", mixed)]:
        with pytest.raises(CisternalWireError, match=opt_name):
            cli_command(fn, contract=CliContract(options=[CliOption(opt_name, int, 0)]))


def test_16a_app_default_parameter_can_remove_negatives():
    """R8: cli_command() models no App default_parameter, wire() passes one.

    The same pairs raise through ``cli_command()`` (cyclopts' own defaults) and
    build through ``_build_cli_callable`` when the App default drops negatives.
    """
    from cisternal.registration.cli_contract import _build_cli_callable

    pairs = [
        (collision_tools_plain.tool_x, CliOption("x2", _NO_X, False)),
        (collision_tools_plain.tool_no_x2, CliOption("x2", bool, False)),
    ]
    for fn, opt in pairs:
        contract = CliContract(options=[opt])
        with pytest.raises(CisternalWireError):
            cli_command(fn, contract=contract)
        with pytest.raises(CisternalWireError):
            _build_cli_callable(
                fn,
                tool_name=fn.__name__,
                command=fn.__name__,
                contract=contract,
                recovery=None,
                telemetry=True,
                app_default_parameter=None,
            )
        _build_cli_callable(
            fn,
            tool_name=fn.__name__,
            command=fn.__name__,
            contract=contract,
            recovery=None,
            telemetry=True,
            app_default_parameter=Parameter(negative=()),
        )


# --- test 16c: strict hint resolution (contract half) ------------------------


def test_16c_unresolvable_parameter_raises_naming_tool_and_parameter():
    fn = future_annot_tools.tool_with_unresolvable_param
    with pytest.raises(CisternalWireError) as excinfo:
        cli_command(fn, contract=CliContract())
    message = str(excinfo.value)
    assert "tool_with_unresolvable_param" in message
    assert "'x'" in message
    assert "NotImportedAnywhere" in message


def test_16c_malformed_string_annotation_is_wrapped_not_leaked():
    fn = future_annot_tools.tool_with_malformed_param
    with pytest.raises(CisternalWireError) as excinfo:
        cli_command(fn, contract=CliContract())
    message = str(excinfo.value)
    assert "tool_with_malformed_param" in message
    assert "'x'" in message


def test_16c_the_error_names_the_configured_tool_name():
    fn = future_annot_tools.tool_with_unresolvable_param
    with pytest.raises(CisternalWireError, match="renamed"):
        cli_command(fn, name="renamed", contract=CliContract())


def test_16c_unresolvable_return_type_does_not_raise_on_the_contract_path(capsys):
    fn = future_annot_tools.tool_with_type_checking_return
    cmd = cli_command(fn, contract=CliContract())
    assert "return" not in cmd.__annotations__
    app = App(name="cli")
    app.command(name="t")(cmd)
    assert _run(app, ["t"]) == 0


def test_16c_future_annotations_tool_parses_on_the_contract_path(capsys):
    fn = future_annot_tools.tool_with_cyclopts_param
    cmd = cli_command(fn, contract=CliContract(options=[json_option()]))
    assert cmd.__annotations__["p"] == Annotated[
        Path, Parameter(name=["--path", "-p"], help="A path.")
    ]
    app = App(name="cli")
    app.command(name="t")(cmd)
    assert _run(app, ["t", "-p", "/tmp/x"]) == 0
    assert _stdout(capsys) == "/tmp/x\n"


def test_wrapped_future_tool_resolves_on_the_contract_path(capsys):
    fn = wrapped_future_tools.wrapped_tool
    cmd = cli_command(fn, contract=CliContract())
    assert cmd.__annotations__["p"] is Path
    app = App(name="cli")
    app.command(name="t")(cmd)
    assert _run(app, ["t", "/tmp/x"]) == 0
    assert _stdout(capsys) == "/tmp/x\n"


def test_bathos_style_mutated_annotations_work_on_the_contract_path():
    fn = bathos_style_tools.tool_with_mutated_annotations
    app = _app_for(fn, CliContract())
    assert _exit(app, ["tool_with_mutated_annotations", "-n", "3"]) == 6


# =============================================================================
# T4: wire() integration (pre-pass, cli_contract / cli_contracts, help / show)
#
# Spec rev 8, section 5.1 and tests 3b, 7, 9 (contract variant), 9d (contract
# half), 16a (wire() half), 16b, 21, 23, 34, 35, 36. Groups beyond a single
# segment (adoption, nesting, cli_group_help) are T4g's and are not exercised.
# =============================================================================

import asyncio  # noqa: E402

import fastmcp  # noqa: E402

from cisternal.registration import wired as wired_module  # noqa: E402


def _server_tools(server: fastmcp.FastMCP) -> list[str]:
    return sorted(t.name for t in asyncio.run(server.list_tools()))


def _state(server: fastmcp.FastMCP, app: App) -> tuple[list[str], list[str], set[Any]]:
    """What a failed wire() must leave unchanged (spec 5.1, test 35)."""
    return (_server_tools(server), sorted(app), set(wired_module._CLI_SUBAPPS))


@pytest.fixture(autouse=True)
def _clear_subapp_cache():
    """Isolate the module-level sub-app cache between tests."""
    saved = dict(wired_module._CLI_SUBAPPS)
    yield
    wired_module._CLI_SUBAPPS.clear()
    wired_module._CLI_SUBAPPS.update(saved)


def _assert_wire_error_leaves_everything_untouched(
    app: App,
    match: str,
    **wire_kwargs: Any,
) -> CisternalWireError:
    server = fastmcp.FastMCP("t4")
    before = _state(server, app)
    with pytest.raises(CisternalWireError, match=match) as excinfo:
        wire(server, app, registry=REGISTRY, **wire_kwargs)
    assert _state(server, app) == before
    return excinfo.value


# --- test 9 (contract variant) -----------------------------------------------


_PATH_ANNOTATED = Annotated[Path, Parameter(name=["--path", "-p"], help="A path.")]


@pytest.mark.parametrize(
    ("fn", "expected"),
    [
        (future_annot_tools.tool_with_cyclopts_param, {"p": _PATH_ANNOTATED}),
        (future_annot_tools.tool_with_path_param, {"p": Path}),
        (
            future_annot_tools.tool_with_annotated_param,
            {"p": Annotated[Path, "description"]},
        ),
        (future_annot_tools.tool_with_type_checking_return, {}),
    ],
    ids=["cyclopts-param", "path", "annotated", "type-checking-return"],
)
def test_9_contract_variant_registers_with_resolved_hints(fn, expected):
    register(fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    registered = app[fn.__name__].default_command

    assert {k: v for k, v in registered.__annotations__.items() if k != "json_out"} == expected
    assert "json_out" in registered.__annotations__
    assert "return" not in registered.__annotations__
    assert all(not isinstance(v, str) for v in registered.__annotations__.values())
    assert not hasattr(registered, "__wrapped__")


def test_9_contract_variant_empty_contract_keeps_the_signature(capsys):
    fn = future_annot_tools.tool_with_cyclopts_param
    register(fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract())
    registered = app[fn.__name__].default_command

    assert inspect.signature(registered) == inspect.signature(fn)
    assert inspect.signature(registered).return_annotation == "str"
    assert _run(app, ["tool_with_cyclopts_param", "-p", "/tmp/x"]) == 0
    assert _stdout(capsys) == "/tmp/x\n"


def test_9_contract_variant_type_checking_return_tool_parses():
    fn = future_annot_tools.tool_with_type_checking_return
    register(fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract())
    assert _run(app, [fn.__name__]) == 0


def test_9_contract_variant_decorator_contract_resolves_the_same_way(capsys):
    fn = future_annot_tools.tool_with_cyclopts_param
    register(fn, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    registered = app[fn.__name__].default_command
    assert registered.__annotations__["p"] == _PATH_ANNOTATED
    assert "json_out" in registered.__annotations__  # the contract path was taken
    assert _run(app, [fn.__name__, "--path", "/tmp/y"]) == 0
    assert _stdout(capsys) == "/tmp/y\n"


def test_16c_unresolvable_parameter_through_wire_names_tool_and_parameter():
    fn = future_annot_tools.tool_with_unresolvable_param
    register(fn, registry=REGISTRY)
    err = _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), "tool_with_unresolvable_param", cli_contract=CliContract()
    )
    assert "'x'" in str(err)


# --- test 9d (contract half) -------------------------------------------------


def test_9d_contract_half_wrapped_timed_tool_registers_and_parses(capsys):
    fn = wrapped_future_tools.wrapped_tool
    register(fn, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    registered = app[fn.__name__].default_command

    # ``Path`` resolves only through the unwrapped function's globals.
    assert registered.__annotations__["p"] is Path
    assert "return" not in registered.__annotations__
    assert not hasattr(registered, "__wrapped__")
    assert _run(app, ["_wrapped_tool_impl", "/tmp/x"]) == 0
    assert _stdout(capsys) == "/tmp/x\n"


# --- test 16a (wire() half) ----------------------------------------------------


@pytest.mark.parametrize("module", _COLLISION_MODULES)
@pytest.mark.parametrize(
    ("tool_name", "options"),
    [pytest.param(t, o, id=i) for i, t, o in _COLLISIONS],
)
def test_16a_wire_half_collision_raises_naming_the_tool(module, tool_name, options):
    fn = getattr(module, tool_name)
    register(fn, registry=REGISTRY)
    err = _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), tool_name, cli_contract=CliContract(options=options)
    )
    assert tool_name in str(err)


def test_16a_wire_half_collision_through_a_decorator_contract():
    fn = collision_tools_plain.tool_json
    register(fn, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    _assert_wire_error_leaves_everything_untouched(App(name="cli"), "tool_json")


def test_16a_wire_half_collision_on_the_second_of_two_entries_registers_nothing():
    register(adds, registry=REGISTRY)
    register(collision_tools_plain.tool_json, registry=REGISTRY)
    _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), "tool_json", cli_contract=CliContract(options=[json_option()])
    )


def test_16a_wire_half_collision_in_a_grouped_tool_registers_nothing():
    register(adds, registry=REGISTRY, cli_group="g")
    register(collision_tools_plain.tool_json, registry=REGISTRY, cli_group="g")
    _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), "tool_json", cli_contract=CliContract(options=[json_option()])
    )


# The same pairs raise through cli_command() / a plain App (R8) and do not raise
# when the target App's resolved default_parameter drops the negatives (A28).
_DEFAULT_PARAMETER_PAIRS = [
    pytest.param(collision_tools_plain.tool_x, CliOption("x2", _NO_X, False), id="x"),
    pytest.param(collision_tools_plain.tool_no_x2, CliOption("x2", bool, False), id="x2"),
]


@pytest.mark.parametrize(("fn", "opt"), _DEFAULT_PARAMETER_PAIRS)
def test_16a_wire_half_root_default_parameter_removes_negatives(fn, opt):
    contract = CliContract(options=[opt])
    register(fn, registry=REGISTRY)

    # Control: a plain App raises (cyclopts' own defaults).
    with pytest.raises(CisternalWireError):
        wire(None, App(name="cli"), registry=REGISTRY, cli_contract=contract)

    app = App(name="cli", default_parameter=Parameter(negative=()))
    wire(None, app, registry=REGISTRY, cli_contract=contract)
    assert fn.__name__ in app


@pytest.mark.parametrize(("fn", "opt"), _DEFAULT_PARAMETER_PAIRS)
def test_16a_wire_half_existing_subapp_default_parameter_removes_negatives(fn, opt):
    """When the group already exists, its own default_parameter joins the chain."""
    contract = CliContract(options=[opt])
    register(adds, registry=REGISTRY, cli_group="g")
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    sub = wired_module._CLI_SUBAPPS[(id(app), "g")]
    sub.default_parameter = Parameter(negative=())

    clear_registry(REGISTRY)
    register(fn, registry=REGISTRY, cli_group="g")

    # Control: a group that does not exist yet contributes no default_parameter,
    # so the same tool raises when its group is new.
    with pytest.raises(CisternalWireError):
        wire(None, App(name="cli2"), registry=REGISTRY, cli_contract=contract)

    wire(None, app, registry=REGISTRY, cli_contract=contract)
    assert fn.__name__ in sub


def test_16a_wire_half_root_and_subapp_default_parameters_combine_root_first():
    """Root says ``negative=()``; the sub-App then re-adds ``off`` (spike A28)."""
    fn = collision_tools_plain.tool_x
    register(adds, registry=REGISTRY, cli_group="g")
    app = App(name="cli", default_parameter=Parameter(negative=()))
    wire(None, app, registry=REGISTRY)
    sub = wired_module._CLI_SUBAPPS[(id(app), "g")]
    sub.default_parameter = Parameter(negative="off")

    clear_registry(REGISTRY)
    register(fn, registry=REGISTRY, cli_group="g")
    # The combined negative of ``x`` is ``--off``: an option claiming it collides,
    # one claiming ``--no-x`` does not.
    off = CliOption("o", _OFF, False)
    with pytest.raises(CisternalWireError, match="--off"):
        wire(None, app, registry=REGISTRY, cli_contract=CliContract(options=[off]))
    wire(
        None,
        app,
        registry=REGISTRY,
        cli_contract=CliContract(options=[CliOption("n", _NO_X, False)]),
    )
    assert "tool_x" in sub


def test_16a_wire_half_controls_that_must_not_raise():
    contract = CliContract(options=[json_option()])
    register(collision_tools_plain.tool_star_json, registry=REGISTRY)
    short = CliOption("jj", Annotated[bool, Parameter(name="-j", negative="")], False)
    register(
        collision_tools_plain.tool_short_j,
        registry=REGISTRY,
        cli_contract=CliContract(options=[short]),
    )
    chdir = CliOption(
        "chdir_to", Annotated[Path | None, Parameter(name="--working-dir")], None
    )
    register(
        collision_tools_plain.tool_parse_false,
        registry=REGISTRY,
        cli_contract=CliContract(options=[chdir]),
    )
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=contract)
    assert {"tool_star_json", "tool_short_j", "tool_parse_false"} <= set(app)


# --- test 16b ------------------------------------------------------------------


def test_16b_duplicate_option_across_w_and_t_is_a_wire_error_naming_the_tool():
    register(adds, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    err = _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), "adds", cli_contract=CliContract(options=[json_option()])
    )
    assert "json_out" in str(err)


def test_16b_duplicate_option_across_w_and_map_entry():
    register(adds, registry=REGISTRY)
    _assert_wire_error_leaves_everything_untouched(
        App(name="cli"),
        "adds",
        cli_contract=CliContract(options=[json_option()]),
        cli_contracts={"adds": CliContract(options=[json_option()])},
    )


# --- test 3b -------------------------------------------------------------------


def raises_kind(kind: str = "config") -> None:
    raise {"config": ConfigErrorLike, "other": OtherMyxcelErrorLike}[kind]("msg")


def test_3b_mro_specificity_through_wire_w_and_decorator_t(capsys):
    w = CliContract(exit_codes={ConfigErrorLike: 2})
    t = CliContract(exit_codes={MyxcelErrorLike: 9})
    register(raises_kind, registry=REGISTRY, cli_contract=t)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=w)

    assert _run(app, ["raises_kind", "--kind", "config"]) == 2
    assert _run(app, ["raises_kind", "--kind", "other"]) == 9


def test_3b_mro_specificity_through_wire_w_and_map_t():
    w = CliContract(exit_codes={ConfigErrorLike: 2})
    t = CliContract(exit_codes={MyxcelErrorLike: 9})
    register(raises_kind, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=w, cli_contracts={"raises_kind": t})

    assert _run(app, ["raises_kind", "--kind", "config"]) == 2
    assert _run(app, ["raises_kind", "--kind", "other"]) == 9


# --- test 7 --------------------------------------------------------------------


def test_7_grouped_tool_with_a_contract_is_reachable_with_the_joined_command():
    seen: list[str] = []

    def fmt(result: Any, ctx: CliContext) -> None:
        seen.append(ctx.command)

    register(adds, registry=REGISTRY, cli_group="g", cli_name="n")
    register(sub_tool, registry=REGISTRY)
    app = App(name="cli")
    result = wire(None, app, registry=REGISTRY, cli_contract=CliContract(format_success=fmt))

    assert app["g"]["n"].default_command is not None
    assert _run(app, ["g", "n", "1"]) == 0
    assert _run(app, ["sub_tool", "1"]) == 0
    assert seen == ["g n", "sub_tool"]
    assert result.cli_commands == ["g n", "sub_tool"]


def test_7_ctx_command_uses_cli_name_for_a_flat_tool():
    seen: list[str] = []
    contract = CliContract(format_success=lambda r, c: seen.append(c.command))
    register(adds, registry=REGISTRY, cli_name="plus", cli_contract=contract)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    assert _run(app, ["plus", "1"]) == 0
    assert seen == ["plus"]


# --- test 21 (wire half) ------------------------------------------------------


def test_21_cli_telemetry_false_with_a_contract_emits_no_events_via_wire(events):
    register(adds, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_telemetry=False, cli_contract=CliContract())
    assert _run(app, ["adds", "1"]) == 0
    assert _cmd_events(events) == []


def test_21_control_telemetry_on_via_wire_emits_events(events):
    register(adds, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract())
    assert _run(app, ["adds", "1"]) == 0
    assert [n for n, _ in _cmd_events(events)] == ["cli.cmd_start", "cli.cmd_end"]


# --- test 23 -------------------------------------------------------------------


def _schemas(server: fastmcp.FastMCP) -> dict[str, Any]:
    return {t.name: t.parameters for t in asyncio.run(server.list_tools())}


class _CountingAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def record(*a: Any, **k: Any) -> None:
            self.calls.append(name)

        return record


def test_23_mcp_schema_equals_the_no_contract_schema_for_both_contract_forms():
    contract = CliContract(options=[json_option(), CliOption("flag", bool, False)])

    register(adds, registry="t4-plain")
    plain = fastmcp.FastMCP("plain")
    wire(plain, registry="t4-plain")

    register(adds, registry="t4-deco", cli_contract=contract)
    deco = fastmcp.FastMCP("deco")
    adapter = _CountingAdapter()
    wire(deco, App(name="cli"), registry="t4-deco", adapter=adapter)

    register(adds, registry="t4-map")
    mapped = fastmcp.FastMCP("mapped")
    wire(mapped, App(name="cli"), registry="t4-map", cli_contracts={"adds": contract})

    register(adds, registry="t4-w")
    wide = fastmcp.FastMCP("wide")
    wire(wide, App(name="cli"), registry="t4-w", cli_contract=contract)

    try:
        expected = _schemas(plain)
        assert "json_out" not in str(expected)
        assert _schemas(deco) == expected
        assert _schemas(mapped) == expected
        assert _schemas(wide) == expected
        assert adapter.calls == []
    finally:
        for r in ("t4-plain", "t4-deco", "t4-map", "t4-w"):
            clear_registry(r)


# --- test 34 -------------------------------------------------------------------


def test_34_hidden_defaulted_argument_through_wire():
    seen_before: list[Any] = []

    def prepare(ctx: CliContext) -> None:
        seen_before.append(ctx.arguments["token"])
        ctx.arguments["token"] = "from-env"

    register(hidden_default, registry=REGISTRY)
    server = fastmcp.FastMCP("t4")
    app = App(name="cli")
    wire(
        server,
        app,
        registry=REGISTRY,
        cli_contracts={"hidden_default": CliContract(prepare=prepare)},
    )

    with pytest.raises(Exception, match="--token") as excinfo:
        app(["hidden_default", "x", "--token", "t"], exit_on_error=False)
    assert type(excinfo.value).__name__ == "UnknownOptionError"

    assert _run(app, ["hidden_default", "x"]) == 0
    assert seen_before == [None]
    assert _SEEN == [("x", "from-env")]
    assert "token" in _schemas(server)["hidden_default"]["properties"]


def test_34_hidden_required_argument_through_wire(capsys):
    present: list[bool] = []

    def prepare(ctx: CliContext) -> None:
        present.append("token" in ctx.arguments)
        ctx.arguments["token"] = "from-env"

    register(hidden_required, registry=REGISTRY)
    server = fastmcp.FastMCP("t4")
    app = App(name="cli")
    wire(
        server,
        app,
        registry=REGISTRY,
        cli_contracts={"hidden_required": CliContract(prepare=prepare)},
    )

    assert _run(app, ["hidden_required", "x"]) == 0
    assert present == [False]
    assert _SEEN == [("x", "from-env")]
    with pytest.raises(Exception) as excinfo:
        app(["hidden_required", "x", "--token", "t"], exit_on_error=False)
    assert type(excinfo.value).__name__ == "UnknownOptionError"
    schema = _schemas(server)["hidden_required"]
    assert "token" in schema["properties"]
    assert "token" in schema["required"]


def test_34_hidden_required_unset_by_prepare_never_reaches_the_tool(events, capsys):
    register(hidden_required, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract(prepare=lambda ctx: None))
    capsys.readouterr()
    assert _run(app, ["hidden_required", "x"]) == 1
    assert (
        capsys.readouterr().err
        == "Error (TypeError): prepare removed required argument 'token'\n"
    )
    assert _SEEN == []
    assert _cmd_events(events) == []


# --- test 35 -------------------------------------------------------------------


def test_35_map_path_applies_at_t_precedence_and_merges_options():
    def fmt_w(result: Any, ctx: CliContext) -> None:
        print(f"W {sorted(ctx.options)}")

    def fmt_t(result: Any, ctx: CliContext) -> None:
        print(f"T {sorted(ctx.options)}")

    w = CliContract(format_success=fmt_w, options=[json_option()])
    t = CliContract(format_success=fmt_t, options=[CliOption("flag", bool, False)])
    register(adds, registry=REGISTRY)
    register(sub_tool, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=w, cli_contracts={"adds": t})

    params = inspect.signature(app["adds"].default_command).parameters
    assert list(params) == ["a", "b", "json_out", "flag"]
    # A tool without a map entry gets W only.
    assert list(inspect.signature(app["sub_tool"].default_command).parameters) == [
        "x",
        "json_out",
    ]


def test_35_map_path_formatter_wins(capsys):
    seen: list[str] = []
    w = CliContract(format_success=lambda r, c: seen.append("W"))
    t = CliContract(format_success=lambda r, c: seen.append("T"))
    register(adds, registry=REGISTRY)
    register(sub_tool, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=w, cli_contracts={"adds": t})
    assert _run(app, ["adds", "1"]) == 0
    assert _run(app, ["sub_tool", "1"]) == 0
    assert seen == ["T", "W"]


def test_35_conflict_decorator_contract_plus_map_entry():
    register(adds, registry=REGISTRY, cli_contract=CliContract())
    err = _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), "adds", cli_contracts={"adds": CliContract()}
    )
    assert "adds" in str(err)


def test_35_conflict_is_checked_even_with_app_none():
    register(adds, registry=REGISTRY, cli_contract=CliContract())
    server = fastmcp.FastMCP("t4")
    with pytest.raises(CisternalWireError, match="adds"):
        wire(server, None, registry=REGISTRY, cli_contracts={"adds": CliContract()})
    assert _server_tools(server) == []


def test_35_unknown_key_names_the_key():
    register(adds, registry=REGISTRY)
    _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), "nope", cli_contracts={"nope": CliContract()}
    )


def test_35_unknown_key_is_checked_even_with_app_none():
    register(adds, registry=REGISTRY)
    server = fastmcp.FastMCP("t4")
    with pytest.raises(CisternalWireError, match="nope"):
        wire(server, None, registry=REGISTRY, cli_contracts={"nope": CliContract()})
    assert _server_tools(server) == []


def test_35_per_tool_contract_with_app_none_is_inert():
    register(adds, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    register(
        collision_tools_plain.tool_json,
        registry=REGISTRY,
        cli_contract=CliContract(options=[json_option()]),
    )
    server = fastmcp.FastMCP("t4")
    result = wire(server, None, registry=REGISTRY)
    assert sorted(result.mcp_tools) == ["adds", "tool_json"]
    assert result.cli_commands == []


@pytest.mark.parametrize("order", ["flat-first", "group-first"])
def test_35_planned_name_clash_flat_command_versus_group(order):
    flat = {"cli_name": "jobs"}
    group = {"cli_group": "jobs"}
    kwargs = [flat, group] if order == "flat-first" else [group, flat]
    register(adds, registry=REGISTRY, **kwargs[0])
    register(sub_tool, registry=REGISTRY, **kwargs[1])
    err = _assert_wire_error_leaves_everything_untouched(App(name="cli"), "jobs")
    assert "jobs" in str(err)


def test_35_planned_name_clash_duplicate_leaf_in_one_group():
    register(adds, registry=REGISTRY, cli_group="g", cli_name="run")
    register(sub_tool, registry=REGISTRY, cli_group="g", cli_name="run")
    _assert_wire_error_leaves_everything_untouched(App(name="cli"), "run")


def test_35_planned_name_clash_duplicate_flat_name():
    register(adds, registry=REGISTRY, cli_name="run")
    register(sub_tool, registry=REGISTRY, cli_name="run")
    _assert_wire_error_leaves_everything_untouched(App(name="cli"), "run")


def test_35_the_same_leaf_in_different_groups_is_not_a_clash():
    register(adds, registry=REGISTRY, cli_group="g", cli_name="run")
    register(sub_tool, registry=REGISTRY, cli_group="h", cli_name="run")
    register(fails, registry=REGISTRY, cli_name="run")
    app = App(name="cli")
    result = wire(None, app, registry=REGISTRY)
    assert sorted(result.cli_commands) == ["g run", "h run", "run"]


def test_35_name_already_on_the_root_from_an_earlier_wire_call():
    register(adds, registry="t4-first", cli_name="t1")
    register(sub_tool, registry=REGISTRY, cli_name="t1")
    app = App(name="cli")
    try:
        wire(None, app, registry="t4-first")
        assert "t1" in app
        server = fastmcp.FastMCP("t4-second")
        before = _state(server, app)
        with pytest.raises(CisternalWireError, match="t1"):
            wire(server, app, registry=REGISTRY)
        assert _state(server, app) == before
        assert _server_tools(server) == []
    finally:
        clear_registry("t4-first")


def test_35_leaf_already_in_an_existing_group_from_an_earlier_wire_call():
    register(adds, registry="t4-first", cli_group="g", cli_name="run")
    register(sub_tool, registry=REGISTRY, cli_group="g", cli_name="run")
    app = App(name="cli")
    try:
        wire(None, app, registry="t4-first")
        sub = wired_module._CLI_SUBAPPS[(id(app), "g")]
        before = (sorted(app), sorted(sub))
        with pytest.raises(CisternalWireError, match="run"):
            wire(None, app, registry=REGISTRY)
        assert (sorted(app), sorted(sub)) == before
    finally:
        clear_registry("t4-first")


def test_35_flat_name_clashing_with_an_existing_group_from_an_earlier_call():
    register(adds, registry="t4-first", cli_group="jobs")
    register(sub_tool, registry=REGISTRY, cli_name="jobs")
    app = App(name="cli")
    try:
        wire(None, app, registry="t4-first")
        _assert_wire_error_leaves_everything_untouched(app, "jobs")
    finally:
        clear_registry("t4-first")


def test_35_a_group_that_already_exists_in_the_cache_is_reused_not_a_clash():
    register(adds, registry="t4-first", cli_group="g", cli_name="a")
    register(sub_tool, registry=REGISTRY, cli_group="g", cli_name="b")
    app = App(name="cli")
    try:
        wire(None, app, registry="t4-first")
        wire(None, app, registry=REGISTRY)
        assert {"a", "b"} <= set(app["g"])
    finally:
        clear_registry("t4-first")


# --- test 36 -------------------------------------------------------------------


def test_36_contract_help_overrides_the_docstring(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    register(adds, registry=REGISTRY, cli_contract=CliContract(help="Custom help"))
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    _run(app, ["adds", "--help"])
    out = _stdout(capsys)
    assert "Custom help" in out
    assert "Add two numbers." not in out


def test_36_docstring_passthrough_when_help_is_none(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    register(adds, registry=REGISTRY, cli_contract=CliContract(options=[json_option()]))
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    _run(app, ["adds", "--help"])
    out = _stdout(capsys)
    assert "Add two numbers." in out
    assert "The first addend." in out

    cmd = app["adds"].default_command
    assert cmd.__name__ == adds.__name__
    assert cmd.__doc__ == adds.__doc__
    assert not hasattr(cmd, "__wrapped__")


def test_36_show_false_hides_the_command_but_it_still_runs(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    register(adds, registry=REGISTRY, cli_contract=CliContract(show=False))
    register(sub_tool, registry=REGISTRY)
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    _run(app, ["--help"])
    out = _stdout(capsys)
    assert "sub_tool" in out
    assert "adds" not in out
    assert _run(app, ["adds", "1"]) == 0


def test_36_merge_w_help_with_t_help_none_and_t_help_set(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    register(adds, registry=REGISTRY)
    register(sub_tool, registry=REGISTRY, cli_contract=CliContract(help="t-help"))
    register(fails, registry=REGISTRY, cli_contract=CliContract())
    app = App(name="cli")
    wire(None, app, registry=REGISTRY, cli_contract=CliContract(help="w-help"))
    _run(app, ["adds", "--help"])
    assert "w-help" in _stdout(capsys)
    _run(app, ["sub_tool", "--help"])
    out = _stdout(capsys)
    assert "t-help" in out
    assert "w-help" not in out
    _run(app, ["fails", "--help"])
    assert "w-help" in _stdout(capsys)


def test_36_help_and_show_reach_a_grouped_command(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    register(
        adds,
        registry=REGISTRY,
        cli_group="g",
        cli_contract=CliContract(help="grouped help"),
    )
    app = App(name="cli")
    wire(None, app, registry=REGISTRY)
    _run(app, ["g", "adds", "--help"])
    assert "grouped help" in _stdout(capsys)


@pytest.fixture
def command_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the keyword arguments of every named ``App.command`` registration."""
    calls: list[dict[str, Any]] = []
    original = App.command

    def spy(self: App, obj: Any = None, /, **kwargs: Any) -> Any:
        if obj is None:
            calls.append(dict(kwargs))
        return original(self, obj, **kwargs)

    monkeypatch.setattr(App, "command", spy)
    return calls


def test_36_control_unset_help_and_show_pass_name_only(command_calls):
    register(adds, registry=REGISTRY, cli_contract=CliContract())
    register(sub_tool, registry=REGISTRY)
    register(
        fails,
        registry=REGISTRY,
        cli_group="g",
        cli_contract=CliContract(help=None, show=None),
    )
    wire(None, App(name="cli"), registry=REGISTRY)
    assert command_calls == [{"name": "adds"}, {"name": "sub_tool"}, {"name": "fails"}]


def test_36_help_and_show_are_forwarded_only_when_set(command_calls):
    register(adds, registry=REGISTRY, cli_contract=CliContract(help="H"))
    register(sub_tool, registry=REGISTRY, cli_contract=CliContract(show=False))
    register(fails, registry=REGISTRY, cli_contract=CliContract(help="H2", show=True))
    wire(None, App(name="cli"), registry=REGISTRY)
    assert command_calls == [
        {"name": "adds", "help": "H"},
        {"name": "sub_tool", "show": False},
        {"name": "fails", "help": "H2", "show": True},
    ]


_COLLISION_DERIVATION = [
    pytest.param(
        "tool_foo_named", CliOption("g", _NO_FOO, False), id="explicit-name-negative"
    ),
    pytest.param(
        "tool_unannotated_flag", CliOption("g", _NO_FLAG, False), id="unannotated-default"
    ),
    pytest.param("tool_any_x", CliOption("g", _NO_X, False), id="any-default"),
]


@pytest.mark.parametrize("module", _COLLISION_MODULES)
@pytest.mark.parametrize(("tool_name", "opt"), _COLLISION_DERIVATION)
def test_36_collision_derivation_negatives_through_wire(module, tool_name, opt):
    register(getattr(module, tool_name), registry=REGISTRY)
    _assert_wire_error_leaves_everything_untouched(
        App(name="cli"), tool_name, cli_contract=CliContract(options=[opt])
    )
