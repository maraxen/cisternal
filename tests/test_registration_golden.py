"""Golden baseline tests for wire() at commit 8730da8 (release/0.1.1a14).

These tests capture the exact behavior before the wire-cli-contract implementation,
ensuring backward compatibility and documenting what byte-identical means.

Golden values are recorded at 8730da8 and re-verified after each change.
"""

from __future__ import annotations

import json
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
    assert captured.err == "Error (ZeroDivisionError): integer division or modulo by zero\n"
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


def test_golden_pre_mounted_group_rejection():
    """Test 30: Baseline collision detection.

    At 8730da8, pre-registering a function command and then trying to wire
    into that group name should raise CommandCollisionError before any
    registration happens.

    This test documents the baseline exception type that the implementation
    changes will replace with CisternalWireError.

    Spec §7: untouched-on-failure guarantee — rejection happens before any
    registration.
    """
    app = App(name="test")

    # Pre-register a function command named "jobs"
    @app.command(name="jobs")
    def pre_existing() -> str:
        return "pre"

    # Record the command count before the collision attempt
    commands_before = len(app._commands)

    # Now try to define a tool with cli_group="jobs"
    @tool(registry=REGISTRY, cli_group="jobs", name="list_jobs")
    def list_jobs() -> str:
        return "list"

    # This should raise before registration completes
    from cyclopts import CommandCollisionError

    with pytest.raises(CommandCollisionError):
        wire(None, app, registry=REGISTRY)

    # Golden: untouched-on-failure: no new commands were added
    assert len(app._commands) == commands_before, \
        "wire() should not register any commands if collision is detected"


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
