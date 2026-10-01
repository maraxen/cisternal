"""T0b tests for the A9 fix: ``_resolve_cli_hints`` and the no-contract CLI closure.

Spec: .praxia/docs/specs/261001_wire-cli-contract.md (rev 8), section 5.5 and
tests 9 (no-contract variant), 9b, 9c, 9d (no-contract half), 16c (no-contract
half) and 18.

The contract-path variants (tests 9 contract, 9d contract half, 16c contract
half) belong to T3/T4 and are not covered here.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Annotated, Any, cast

import pytest
from cyclopts import App, Parameter

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
