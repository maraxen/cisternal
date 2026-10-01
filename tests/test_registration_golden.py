"""Golden baseline tests for wire() at commit 8730da8 (release/0.1.1a14).

These tests capture the exact behavior before the wire-cli-contract implementation,
ensuring backward compatibility and documenting what byte-identical means.

Golden values are recorded at 8730da8 and re-verified after each change.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path

import pytest
from cyclopts import App

from cisternal import init, tool
from cisternal.registration.registry import clear_registry
from cisternal.registration.wired import wire

REGISTRY = "golden-test"


@pytest.fixture
def log_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def _isolation():
    clear_registry(REGISTRY)
    yield
    clear_registry(REGISTRY)
    from cisternal.telemetry import pipeline as pipeline_module

    if pipeline_module._global_pipeline is not None:
        pipeline_module._global_pipeline.shutdown()
        pipeline_module._global_pipeline = None


def _events(d: Path) -> list[dict]:
    time.sleep(0.3)
    out: list[dict] = []
    for f in sorted(d.rglob("*")):
        if f.is_file():
            for line in f.read_text().splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _strip_timing(e: dict) -> dict:
    """Remove timing fields from an event for stable comparison."""
    e = dict(e)
    fields = e.get("fields", {})
    if isinstance(fields, dict):
        fields = {k: v for k, v in fields.items() if k not in ("duration", "timestamp")}
        e["fields"] = fields
    return e


def _name_of(e: dict) -> str | None:
    return e.get("event") or e.get("name") or e.get("event_name")


def test_no_contract_wired_command_succeeds(log_dir, capsys):
    """Test 25: Golden capture of success path.

    A wired command with no contract: tool returns str -> printed and exits 0.
    Spec §7 G9: signature and metadata identity.
    """
    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    def greet(name: str) -> str:
        """Greet a person."""
        return f"hello {name}"

    app = App(name="cli")
    wired = wire(None, app, registry=REGISTRY)

    try:
        app(["greet", "world"], exit_on_error=False)
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    captured = capsys.readouterr()

    # Golden values at 8730da8:
    # A string result is printed and exits 0
    assert exit_code == 0, f"Expected exit 0 on string result, got {exit_code}"
    assert "hello world" in captured.out
    assert captured.err == "", "stderr should be empty on success"

    # Golden: CLI command is in registry
    assert "greet" in wired.cli_commands


def test_no_contract_wired_command_failure(log_dir, capsys):
    """Test 25: Golden capture of failure path.

    An unmapped exception should exit 1 with the F1 line.
    Spec §7 G9: byte-identical F1 output.
    """
    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    def divide(a: int, b: int) -> int:
        return a // b

    app = App(name="cli")
    wire(None, app, registry=REGISTRY)

    try:
        app(["divide", "10", "0"], exit_on_error=False)
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    captured = capsys.readouterr()

    # Golden values at 8730da8: F1 line exact format
    assert exit_code == 1, "Expected exit 1 on ZeroDivisionError"
    assert (
        captured.err
        == "Error (ZeroDivisionError): integer division or modulo by zero\n"
    )
    assert captured.out == "", "stdout must be empty on error"


def test_golden_cli_commands_flat():
    """Test 25: WiredRegistry.cli_commands for a flat tool."""

    @tool(registry=REGISTRY)
    def flat_cmd() -> str:
        return "done"

    app = App(name="test")
    wired = wire(None, app, registry=REGISTRY)

    # Golden: cli_commands should list the command
    assert "flat_cmd" in wired.cli_commands


def test_golden_cli_commands_grouped():
    """Test 25: WiredRegistry.cli_commands for a grouped tool."""

    @tool(registry=REGISTRY, cli_group="jobs")
    def list_jobs() -> list:
        return []

    app = App(name="test")
    wired = wire(None, app, registry=REGISTRY)

    # Golden: grouped command recorded as "group name"
    assert "jobs list_jobs" in wired.cli_commands


def test_golden_async_tool(capsys):
    """Test 25: Async tool success path."""

    @tool(registry=REGISTRY)
    async def async_greet(name: str) -> str:
        return f"hello {name}"

    app = App(name="test")
    wire(None, app, registry=REGISTRY)

    try:
        app(["async_greet", "async"], exit_on_error=False)
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    captured = capsys.readouterr()

    # Golden: async tool should succeed and print result
    assert exit_code == 0, f"Expected exit 0, got {exit_code}"
    assert "hello async" in captured.out


# What wiring a tool into a group name that is already taken raised at 8730da8.
# T0a verified this (the pre-mounted-group setup raised cyclopts'
# CommandCollisionError, from the unconditional mount in the old
# _get_or_create_subapp) and recorded it here. T4g changed the behaviour on
# purpose, so this literal is now a RECORD of the change: nothing below asserts
# that CommandCollisionError is still raised.
_LEGACY_8730DA8_PRE_MOUNTED_GROUP_EXCEPTION = "CommandCollisionError"


def test_golden_pre_mounted_group_rejection():
    """Test 30: behaviour change record for a group name that is a function command.

    At 8730da8, pre-registering a function command and then wiring a tool into
    that group name raised ``CommandCollisionError``
    (``_LEGACY_8730DA8_PRE_MOUNTED_GROUP_EXCEPTION``), from the mount in the
    registration loop. Since T4g the pre-pass rejects it before any registration
    with ``CisternalWireError`` (spec 5.6, step 2: a function command is not a
    group), and the untouched-on-failure guarantee still holds (spec 5.1).
    """
    app = App(name="test")

    # Pre-register a function command named "jobs"
    @app.command(name="jobs")
    def pre_existing() -> str:
        return "pre"

    commands_before = len(app._commands)

    @tool(registry=REGISTRY, cli_group="jobs", name="list_jobs")
    def list_jobs() -> str:
        return "list"

    from cisternal.registration.cli_contract import _CLI_CREATED_HELP, _CLI_SUBAPPS
    from cisternal.registration.errors import CisternalWireError

    subapps_before = set(_CLI_SUBAPPS)
    helps_before = set(_CLI_CREATED_HELP)

    with pytest.raises(CisternalWireError, match="jobs") as excinfo:
        wire(None, app, registry=REGISTRY)

    assert _LEGACY_8730DA8_PRE_MOUNTED_GROUP_EXCEPTION == "CommandCollisionError"
    assert type(excinfo.value).__name__ != _LEGACY_8730DA8_PRE_MOUNTED_GROUP_EXCEPTION

    # Untouched-on-failure: no new commands, no cached or recorded group.
    assert len(app._commands) == commands_before, (
        "wire() should not register any commands if a group is rejected"
    )
    assert set(_CLI_SUBAPPS) == subapps_before
    assert set(_CLI_CREATED_HELP) == helps_before


def test_golden_no_contract_int_return_becomes_exit(capsys):
    """Test 25: Int return value becomes exit code under default action."""

    @tool(registry=REGISTRY)
    def exit_with_code(code: int = 0) -> int:
        """Tool that returns an exit code."""
        return code

    app = App(name="test")
    wire(None, app, registry=REGISTRY)

    # Per spec A6: int result becomes the exit code
    try:
        app(["exit_with_code", "--code", "42"], exit_on_error=False)
    except SystemExit as e:
        exit_code = e.code
    else:
        exit_code = None

    # Golden: int return becomes the exit code
    assert exit_code == 42, f"Expected exit 42, got {exit_code}"


def test_golden_wrapped_tool_with_future_annotations():
    """Test 25: Baseline for wrapped tools using functools.wraps + future annotations.

    This captures the baseline behavior at 8730da8 before the A9 annotation
    resolution fix. The wrapped_future_tools fixture tests that wrapped_tool
    (which uses functools.wraps to preserve the original signature) can be
    wired without error.

    Spec A9 fix (T0b) will improve annotation resolution for wrapped tools,
    but this baseline ensures it is preserved.
    """
    from tests.fixtures.wrapped_future_tools import wrapped_tool

    @tool(registry=REGISTRY, name="wrapped_tool_reg")
    def my_wrapped_tool(p):
        """A tool using the wrapped fixture."""
        return wrapped_tool(p)

    app = App(name="test")
    # At baseline (8730da8), this should succeed without raising NameError
    wired = wire(None, app, registry=REGISTRY)

    # Golden: wrapped tool is registered
    assert "wrapped_tool_reg" in wired.cli_commands


def test_golden_9b_typecheck_any_registers_and_parses(capsys):
    """Tests 9b / 25: ``Any`` imported only under TYPE_CHECKING in the tool module.

    Recorded at 8730da8 (src identical at the T0b hoist commit): the tool
    registers and parses through wire(), because ``Any`` resolves through
    wired.py's own globals. Outcome literal: registers, runs, exit 0, stdout
    carries the tool's print.
    """
    from cisternal.registration.registry import register
    from tests.fixtures.typecheck_any_tools import tool_with_any_param

    register(tool_with_any_param, registry=REGISTRY)
    app = App(name="test")
    wired = wire(None, app, registry=REGISTRY)

    with pytest.raises(SystemExit) as excinfo:
        app(["tool_with_any_param", "3"], exit_on_error=False)

    captured = capsys.readouterr()
    assert wired.cli_commands == ["tool_with_any_param"]
    assert excinfo.value.code == 0
    # rich colourises the printed str; strip ANSI escapes before comparing.
    assert re.sub(r"\x1b\[[0-9;]*m", "", captured.out) == "x=3\n"
    assert captured.err == ""


def test_golden_registered_signature_string_future_annotations():
    """Test 25: ``str(inspect.signature(registered))`` for a tool that registers today.

    Recorded at 8730da8. A future-annotations tool with builtin annotations only;
    the registered CLI callable's signature keeps the raw string annotations and
    the return annotation.
    """
    import inspect

    from cisternal.registration.registry import register
    from tests.fixtures.wrapped_future_tools import simple_tool

    register(simple_tool, registry=REGISTRY)
    app = App(name="test")
    wire(None, app, registry=REGISTRY)

    registered = app["simple_tool"].default_command
    assert str(inspect.signature(registered)) == "(x: 'int') -> 'int'"
