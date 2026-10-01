"""T0b tests for the A9 fix (``_resolve_cli_hints`` and the no-contract CLI closure)
and T1 tests for the contract types (``CliContext``, ``CliOption``, ``CliContract``,
``json_option``, ``default_report``, ``exit_code_attr``, ``merged_over``,
``_resolve_exit``).

Spec: .praxia/docs/specs/261001_wire-cli-contract.md (rev 8), section 5.5 and
tests 9 (no-contract variant), 9b, 9c, 9d (no-contract half), 16c (no-contract
half) and 18.

The contract-path variants (tests 9 contract, 9d contract half, 16c contract
half) belong to T3/T4 and are not covered here.
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

import pytest
from cyclopts import App, Parameter

from cisternal.registration import cli_contract as cli_contract_module
from cisternal.registration.cli_contract import (
    CliContext,
    CliContract,
    CliOption,
    _resolve_exit,
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
