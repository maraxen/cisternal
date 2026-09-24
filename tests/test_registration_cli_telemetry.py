"""CLI-path telemetry through ``wire()``.

The MCP path's silence is deliberate: ``CisternalMiddleware`` owns telemetry
there, and a composed callable that also emitted would double-count every tool
call. The CLI path had no such owner and therefore emitted nothing at all, so
the same tool invoked the same way produced a complete record through MCP and
silence through the CLI.

NOTE ON METHOD. These tests install a REAL pipeline via ``init(log_dir=...)``
and read the JSONL back. They deliberately do not use the ``shadow_pipeline``
fixture in ``test_registration_telem.py``: that fixture constructs an
``EventPipeline`` but never installs it as the global pipeline, so
``emit_event`` never reaches its spy and every ``assert len(spy.records) == 0``
written against it passes whether telemetry fired or not. A test that cannot
fail cannot support a claim, and the claim here is precisely about whether
events are emitted.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest
from cyclopts import App

from cisternal import init, tool
from cisternal.adapters.cli import timed_command
from cisternal.registration.registry import clear_registry
from cisternal.registration.wired import wire

REGISTRY = "cli-telem-test"


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


def _name_of(e: dict) -> str | None:
    return e.get("event") or e.get("name") or e.get("event_name")


def _field(e: dict, key: str):
    """Emitted payload lands under ``fields``; fall back to top level."""
    return e.get("fields", {}).get(key, e.get(key))


def _names(d: Path) -> list[str]:
    return [_name_of(e) for e in _events(d)]


def _ends(d: Path) -> list[dict]:
    return [e for e in _events(d) if _name_of(e) == "cli.cmd_end"]


def _run(app: App, argv: list[str]) -> None:
    # Cyclopts exits the process after a command; swallow that so the test can
    # go on to inspect the log.
    try:
        app(argv, exit_on_error=False)
    except SystemExit:
        pass


def test_wired_cli_command_emits_start_and_end(log_dir):
    """The claim this change exists to make true."""
    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    def greet(name: str) -> str:
        return f"hi {name}"

    app = App()
    wire(None, app, registry=REGISTRY)
    _run(app, ["greet", "--name", "world"])

    names = _names(log_dir)
    assert "cli.cmd_start" in names
    assert "cli.cmd_end" in names


def test_cli_telemetry_can_be_turned_off(log_dir):
    """Opt-out restores the previous silence, for anyone who depended on it."""
    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    def quiet(name: str) -> str:
        return name

    app = App()
    wire(None, app, registry=REGISTRY, cli_telemetry=False)
    _run(app, ["quiet", "--name", "x"])

    names = _names(log_dir)
    assert "cli.cmd_start" not in names
    assert "cli.cmd_end" not in names


def test_hand_instrumented_command_is_not_wrapped_twice(log_dir):
    """A consumer who already applied @timed_command must not get doubles.

    Without the ``_cisternal_timed`` guard this emits two starts and two ends,
    silently doubling every duration and count downstream.
    """
    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    @timed_command("already_timed")
    def already(name: str) -> str:
        return name

    app = App()
    wire(None, app, registry=REGISTRY)
    _run(app, ["already", "--name", "x"])

    names = _names(log_dir)
    assert names.count("cli.cmd_start") == 1
    assert names.count("cli.cmd_end") == 1


def test_failure_records_the_original_exception_not_systemexit(log_dir):
    """Ordering guarantee: telemetry sits INSIDE the F1 error contract.

    ``wire``'s CLI closure converts any exception into ``sys.exit(1)``. If the
    telemetry wrapper sat outside that conversion it would observe SystemExit
    and record ``exc_type="SystemExit"`` for every failure, which is true and
    useless -- it names cisternal's own error handling rather than what broke.
    """
    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    def explode(x: int) -> int:
        raise ValueError("boom")

    app = App()
    wire(None, app, registry=REGISTRY)
    _run(app, ["explode", "--x", "1"])

    ends = _ends(log_dir)
    assert ends, "a failing command must still close its span"
    end = ends[-1]
    assert _field(end, "ok") is False
    assert _field(end, "exc_type") == "ValueError", (
        f"expected the original exception type, got {_field(end, 'exc_type')!r}"
    )


def test_timed_command_closes_its_span_on_systemexit(log_dir):
    """A command that calls sys.exit() must still emit cli.cmd_end.

    SystemExit is a BaseException, so the original handler let it past and left
    cli.cmd_start with no matching end -- an unclosed span for the most ordinary
    thing a CLI does.
    """
    init(log_dir=log_dir)

    @timed_command("exiting")
    def exiting() -> None:
        raise SystemExit(3)

    with pytest.raises(SystemExit):
        exiting()

    names = _names(log_dir)
    assert names.count("cli.cmd_start") == 1
    assert names.count("cli.cmd_end") == 1
    end = _ends(log_dir)[0]
    assert _field(end, "exc_type") == "SystemExit"
    assert _field(end, "exit_code") == 3
    assert _field(end, "ok") is False


def test_clean_exit_is_not_recorded_as_a_failure(log_dir):
    """sys.exit(0) is how a CLI succeeds; recording it as ok=False would make
    every successful --help look like an error."""
    init(log_dir=log_dir)

    @timed_command("clean")
    def clean() -> None:
        raise SystemExit(0)

    with pytest.raises(SystemExit):
        clean()

    end = _ends(log_dir)[0]
    assert _field(end, "ok") is True
    assert _field(end, "exit_code") == 0


def test_mcp_path_still_emits_nothing_without_middleware(log_dir):
    """C5 / AC-M2-6(a) is unchanged, and this time the check can actually fail.

    The equivalent assertion in test_registration_telem.py uses an uninstalled
    spy pipeline and would pass regardless. This one uses the real pipeline, so
    it genuinely pins that the composed MCP callable stays silent -- which it
    must, or installing CisternalMiddleware would double-count every call.
    """
    import fastmcp

    init(log_dir=log_dir)

    @tool(registry=REGISTRY)
    def add(a: int, b: int) -> int:
        return a + b

    server = fastmcp.FastMCP("test-mcp-silent")
    wire(server, registry=REGISTRY)

    import asyncio

    asyncio.run(server.call_tool("add", {"a": 1, "b": 2}))

    names = _names(log_dir)
    assert "cli.cmd_start" not in names
    assert "cli.cmd_end" not in names
