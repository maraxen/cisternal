"""T6: execute the worked examples of ``docs/guides/wire-onboarding.md``.

Spec: .praxia/docs/specs/261001_wire-cli-contract.md (rev 8), section 12 T6.

The tests do not keep their own copy of the examples. Each fenced ``python``
block that follows an ``<!-- example: <id> -->`` marker in the guide is
extracted and executed as written, so the guide cannot drift from the code:

* sections 6.6 to 6.10 (``redsox``, ``alphex-mcp`` + ``alphex-cli``, ``maraxiom``,
  ``contemplex``, ``envelope``),
* the section 7 async composite (``async-composite``),
* the section 8 item 7 ``app.meta`` recipe (``app-meta``).

The hidden-argument and mid-command-confirm recipes are prose only: the guide
holds them as unmarked blocks, and :func:`test_prose_recipes_are_not_executed`
pins that.

Consumer imports (``redsox``, ``alphex``, ``myxcel``, ``maraxiom``, ``contemplex``)
resolve to the stubs in ``tests/fixtures/docs_prelude.py``. The ``alphex``
examples run in the order the guide gives: the ``alphex/mcp.py`` snippet first,
as module ``alphex.mcp``, then ``alphex/cli.py`` and the composite.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest
from cyclopts import App

import cisternal
from cisternal import CliContract, exit_code_attr
from cisternal.registration.registry import register
from cisternal.registration.wired import wire
from tests.fixtures import docs_prelude

GUIDE = (
    Path(__file__).resolve().parent.parent / "docs" / "guides" / "wire-onboarding.md"
)

_EXAMPLE_RE = re.compile(
    r"<!--\s*example:\s*(?P<id>[\w-]+)\s*-->\s*\n```python\n(?P<code>.*?)\n```",
    re.DOTALL,
)
_ANY_PYTHON_BLOCK_RE = re.compile(r"^```python\n", re.MULTILINE)

EXAMPLE_IDS = (
    "redsox",
    "alphex-mcp",
    "alphex-cli",
    "maraxiom",
    "contemplex",
    "envelope",
    "async-composite",
    "app-meta",
)


def _guide_text() -> str:
    assert GUIDE.is_file(), f"missing {GUIDE}"
    return GUIDE.read_text(encoding="utf-8")


def _examples() -> dict[str, str]:
    return {m["id"]: m["code"] for m in _EXAMPLE_RE.finditer(_guide_text())}


def _exec_example(
    example_id: str, module_name: str, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """Execute guide example *example_id* as module *module_name* and return the module.

    The module is registered in ``sys.modules`` before it runs, which is what lets
    ``cli.py`` do ``import alphex.mcp`` and lets the composite import from it.
    """
    code = _examples()[example_id]
    mod = types.ModuleType(module_name)
    mod.__file__ = f"<guide:{example_id}>"
    monkeypatch.setitem(sys.modules, module_name, mod)
    # dont_inherit: the example's own ``from __future__`` lines decide its annotations,
    # not this test module's.
    exec(
        compile(code, f"<guide:{example_id}>", "exec", dont_inherit=True), mod.__dict__
    )  # noqa: S102
    return mod


@pytest.fixture
def prelude(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    return docs_prelude.install(monkeypatch)


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Spy on the ``emit_event`` that ``timed_command`` calls (as in the contract tests)."""
    rec: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, **fields: Any) -> None:
        rec.append((name, fields))

    monkeypatch.setattr("cisternal.adapters.cli.emit_event", spy)
    return rec


def _cmd_events(
    events: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    return [(n, f) for n, f in events if n.startswith("cli.cmd_")]


def _run(app: App, argv: list[str]) -> int:
    """Invoke *app*; return the exit code (0 when it returns normally)."""
    try:
        app(argv, exit_on_error=False)
    except SystemExit as exc:
        return cast("int", exc.code if exc.code is not None else 0)
    return 0


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# --------------------------------------------------------------------------- the guide itself


def test_guide_contains_every_executed_example() -> None:
    assert set(_examples()) == set(EXAMPLE_IDS)


def test_guide_has_the_prose_recipes_and_the_seven_parts() -> None:
    text = _guide_text()
    for needle in (
        "Hidden or context-derived argument",
        "Mid-command confirm",
        "Parameter(parse=False)",
        "Confirm",  # rich.prompt.Confirm in the confirm recipe
        "Two entry points",
        "exit_code_attr(report=",
        "int-valued",
        "cli_group_help",
        'cli_group(app, "flow visuals")',
        "CliContract(help=",
        "CliContract(show=False)",
        "never `asyncio.run` per tool",
        "bathos",
        "app.meta",
        "to_result()",
    ):
        assert needle in text, needle
    headings = re.findall(r"^## (\d)\. ", text, re.MULTILINE)
    assert headings == [str(i) for i in range(1, 8)]


def test_prose_recipes_are_not_executed() -> None:
    """Executed blocks are exactly the marked ones; the recipes stay unmarked prose."""
    text = _guide_text()
    marked = len(_examples())
    assert len(_ANY_PYTHON_BLOCK_RE.findall(text)) > marked
    for recipe in ("Hidden or context-derived argument", "Mid-command confirm"):
        section = text.split(recipe, 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        assert "<!-- example:" not in section


def test_readme_links_the_guide() -> None:
    readme = (GUIDE.parent.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "docs/guides/wire-onboarding.md" in readme


def test_changelog_entry_for_the_cli_contract() -> None:
    changelog = (GUIDE.parent.parent.parent / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    assert "CliContract" in changelog
    assert "wire-onboarding" in changelog


def test_wire_docstring_describes_the_contract_not_a_passthrough() -> None:
    doc = wire.__doc__ or ""
    assert "pure passthrough to the original function" not in doc
    assert "wire-onboarding" in doc


# --------------------------------------------------------------------------- 6.6 redsox


def _redsox(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, App]:
    mod = _exec_example("redsox", "redsox_example", monkeypatch)
    return mod, mod.app


def test_redsox_success_prints_the_green_summary_and_writes_the_file(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _, app = _redsox(prelude, monkeypatch)
    out = tmp_path / "seams.json"
    assert _run(app, ["derive-seams", "-c", "ok.toml", "-o", str(out)]) == 0
    # rich wraps a long path across lines: compare with all whitespace removed.
    flat = re.sub(r"\s+", "", _plain(capsys.readouterr().out))
    assert f"Derived2seamswrittento{out}" in flat
    assert [s["id"] for s in json.loads(out.read_text())] == [1, 2]


def test_redsox_seam_explosion_exits_2_with_the_report_on_stdout(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    events: list[tuple[str, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    _, app = _redsox(prelude, monkeypatch)
    assert (
        _run(
            app, ["derive-seams", "-c", "explode.toml", "-o", str(tmp_path / "s.json")]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "seam explosion: 4096 seams exceed the cap" in _plain(captured.out)
    assert "Error (" not in captured.err  # the handler rendered it; no F1 line
    ends = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"]
    assert len(ends) == 1
    assert ends[0]["exc_type"] == "SeamExplosionError"
    assert ends[0]["ok"] is False


def test_redsox_attached_report_is_preferred_over_the_message(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _, app = _redsox(prelude, monkeypatch)
    assert (
        _run(
            app,
            [
                "derive-seams",
                "-c",
                "explode-report.toml",
                "-o",
                str(tmp_path / "s.json"),
            ],
        )
        == 2
    )
    assert "REPORT: 4096 seams, cap 1024" in _plain(capsys.readouterr().out)


def test_redsox_unmapped_exception_keeps_the_f1_line_and_exit_1(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Negative control: the mapping must not match everything."""
    _, app = _redsox(prelude, monkeypatch)
    assert (
        _run(
            app, ["derive-seams", "-c", "missing.toml", "-o", str(tmp_path / "s.json")]
        )
        == 1
    )
    assert capsys.readouterr().err == "Error (FileNotFoundError): missing.toml\n"


def test_redsox_help_keeps_the_annotated_options(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The example uses ``from __future__ import annotations`` and names ``Annotated``,
    ``Path`` and ``Parameter``, which ``wired.py`` does not import: it only wires because of
    the A9 fix, and the parameters must still come through with their flags and help."""
    _, app = _redsox(prelude, monkeypatch)
    _run(app, ["derive-seams", "--help"])
    out = _plain(capsys.readouterr().out)
    assert "--config" in out and "-c" in out
    assert "Path to config.yaml or config.toml" in out
    assert "--out" in out and "Output path for seams.json" in out


# --------------------------------------------------------------------------- 6.7 alphex


def _alphex(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any]:
    """Run ``alphex/mcp.py`` as module ``alphex.mcp`` first, then ``alphex/cli.py``."""
    mcp_mod = _exec_example("alphex-mcp", "alphex.mcp", monkeypatch)
    prelude.modules["alphex"].mcp = mcp_mod
    cli_mod = _exec_example("alphex-cli", "alphex.cli", monkeypatch)
    return mcp_mod, cli_mod


def test_alphex_cli_before_mcp_cannot_import(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order control: cli.py needs alphex.mcp to have run (it registers the tools)."""
    with pytest.raises(ImportError):
        _exec_example("alphex-cli", "alphex.cli", monkeypatch)


def test_alphex_list_matches_the_hand_written_line_format(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, cli = _alphex(prelude, monkeypatch)
    assert _run(cli.cli_app, ["list"]) == 0
    lines = _plain(capsys.readouterr().out).splitlines()
    assert lines == [
        "dna        size=4   offset=0  gap@4",
        "protein20  size=20  offset=4  -  (lints)",
    ]


def test_alphex_json_out_is_json_and_renders_otherwise(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, cli = _alphex(prelude, monkeypatch)
    assert _run(cli.cli_app, ["list", "--json-out"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in rows] == ["dna", "protein20"]

    assert _run(cli.cli_app, ["show", "dna", "--json-out"]) == 0
    assert json.loads(capsys.readouterr().out) == {"name": "dna", "size": 4}

    assert _run(cli.cli_app, ["show", "dna"]) == 0
    assert capsys.readouterr().out.startswith("RENDERED ")

    assert _run(cli.cli_app, ["relation", "dna", "rna"]) == 0
    assert capsys.readouterr().out.startswith("RENDERED ")


def test_alphex_perm_policy_is_positional_or_keyword_and_validated(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, cli = _alphex(prelude, monkeypatch)
    assert _run(cli.cli_app, ["perm", "a", "b", "mask", "--json-out"]) == 0
    assert json.loads(capsys.readouterr().out)["policy"] == "mask"
    assert _run(cli.cli_app, ["perm", "a", "b", "--policy", "mask", "--json-out"]) == 0
    assert json.loads(capsys.readouterr().out)["policy"] == "mask"
    # Accepted difference: ValueError, not SystemExit(msg); both exit 1.
    assert _run(cli.cli_app, ["perm", "a", "b", "--policy", "bogus"]) == 1
    assert capsys.readouterr().err == (
        "Error (ValueError): policy must be one of raise, unknown, gap, mask, got 'bogus'\n"
    )


def test_alphex_lint_strict_exits_1_only_with_findings(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, cli = _alphex(prelude, monkeypatch)
    assert _run(cli.cli_app, ["lint", "--strict"]) == 0
    assert capsys.readouterr().out.strip() == "no warnings"
    assert _run(cli.cli_app, ["lint", "--json-out"]) == 0
    assert json.loads(capsys.readouterr().out) == []

    prelude.surface.LINT_FINDINGS.append(
        {"alphabet": "protein20", "warning": "unused letters"}
    )
    assert _run(cli.cli_app, ["lint"]) == 0
    assert capsys.readouterr().out.startswith("RENDERED ")
    assert _run(cli.cli_app, ["lint", "--strict"]) == 1
    assert "unused letters" in capsys.readouterr().out


def test_alphex_help_shows_option_help_and_the_per_command_override(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, cli = _alphex(prelude, monkeypatch)
    _run(cli.cli_app, ["lint", "--help"])
    out = _plain(capsys.readouterr().out)
    assert "--json-out" in out and "--no-json-out" not in out
    assert "Exit 1 on any finding." in out
    _run(cli.cli_app, ["perm", "--help"])
    # cyclopts renders the help as markdown, which drops the backticks.
    assert "Build the permutation table from src to dst." in _plain(
        capsys.readouterr().out
    )
    _run(cli.cli_app, ["--help"])
    names = _plain(capsys.readouterr().out)
    for cli_name in ("list", "show", "relation", "perm", "lint"):
        assert cli_name in names


def test_alphex_mcp_surface_is_unchanged_by_the_cli_contracts(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second entry point: ``wire(server, registry="alphex")`` registers the five MCP
    tools by their MCP names, with no CLI-only parameter in any schema."""
    _alphex(prelude, monkeypatch)
    server = docs_prelude.RecordingServer("alphex")
    wire(server, registry="alphex")
    assert sorted(server.tools) == [
        "lint",
        "list_alphabets",
        "perm",
        "relation",
        "show_alphabet",
    ]
    for name in server.tools:
        props = server.schema(name).get("properties", {})
        assert "json_out" not in props and "strict" not in props, name
    assert sorted(server.schema("perm")["properties"]) == ["dst", "policy", "src"]


# --------------------------------------------------------------------------- 6.8 maraxiom


def _maraxiom(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_tools: bool = False,
) -> Any:
    if extra_tools:

        def config_boom() -> dict:
            raise prelude.modules["myxcel"].ConfigError("bad config")

        def plain_boom() -> dict:
            raise prelude.modules["myxcel"].MyxcelError("plain failure")

        def runtime_boom() -> dict:
            raise RuntimeError("boom")

        for fn in (config_boom, plain_boom, runtime_boom):
            register(fn, registry="maraxiom")
    return _exec_example("maraxiom", "maraxiom_example", monkeypatch)


def test_maraxiom_table_json_and_prompt(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from rich.prompt import Prompt

    asked: list[str] = []

    def fake_ask(question: str, *a: Any, **kw: Any) -> str:
        asked.append(question)
        return "Prompted title"

    monkeypatch.setattr(Prompt, "ask", fake_ask)
    mod = _maraxiom(prelude, monkeypatch)

    assert _run(mod.app, ["new", "--title", "Given"]) == 0
    table = _plain(capsys.readouterr().out)
    assert "slide" in table and "status" in table and "s1" in table
    assert asked == []

    assert _run(mod.app, ["new", "--title", "Given", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Given"

    # No --title: prepare prompts, and the answer reaches the tool.
    assert _run(mod.app, ["new", "--json"]) == 0
    assert asked == ["Title"]
    assert json.loads(capsys.readouterr().out)["title"] == "Prompted title"


def test_maraxiom_working_dir_resolves_relative_paths_before_chdir(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    start = tmp_path / "start"
    elsewhere = tmp_path / "elsewhere"
    start.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(start)  # monkeypatch restores the original cwd at teardown
    mod = _maraxiom(prelude, monkeypatch)
    argv = [
        "new",
        "--title",
        "T",
        "--out",
        "deck",
        "--working-dir",
        str(elsewhere),
        "--json",
    ]
    assert _run(mod.app, argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["out"] == str(start / "deck")  # resolved against the ORIGINAL cwd
    assert Path.cwd() == elsewhere  # and the chdir did happen


def test_maraxiom_exit_code_attr_with_custom_report(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _maraxiom(prelude, monkeypatch, extra_tools=True)
    capsys.readouterr()
    # ConfigError -> MRO -> the MyxcelError handler; the subclass's own exit_code (2).
    assert _run(mod.app, ["config_boom"]) == 2
    assert _plain(capsys.readouterr().err) == "Error: bad config\n"
    # The base class carries exit_code 1.
    assert _run(mod.app, ["plain_boom"]) == 1
    assert _plain(capsys.readouterr().err) == "Error: plain failure\n"
    # Negative control: an unmapped exception keeps the F1 line.
    assert _run(mod.app, ["runtime_boom"]) == 1
    assert capsys.readouterr().err == "Error (RuntimeError): boom\n"


def test_maraxiom_mcp_schema_has_no_cli_only_parameters(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _maraxiom(prelude, monkeypatch)
    schema = prelude.mcp.schema("new_presentation")
    assert sorted(schema["properties"]) == ["audience", "out", "title"]


# --------------------------------------------------------------------------- 6.9 contemplex


def _contemplex(prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> Any:
    return _exec_example("contemplex", "contemplex_example", monkeypatch)


def _wire_contemplex(
    prelude: types.SimpleNamespace, contract: CliContract
) -> tuple[App, types.SimpleNamespace]:
    errors = prelude.modules["contemplex.errors"]

    def session_not_found() -> dict:
        raise errors.SessionNotFound("s1")

    def gate_blocked() -> dict:
        raise errors.GateBlocked("g3", "no winner")

    def staging_failed() -> dict:
        raise errors.StagingFailed("disk full")

    def write_failed() -> dict:
        raise errors.ContemplexError("cannot write", errors.ErrorCode.WRITE_FAILED)

    def runtime_boom() -> dict:
        raise RuntimeError("boom")

    def fine() -> dict:
        return {"ok": True}

    for fn in (
        session_not_found,
        gate_blocked,
        staging_failed,
        write_failed,
        runtime_boom,
        fine,
    ):
        register(fn, registry="contemplex")
    app = App(name="ctxp")
    wire(prelude.mcp, app, registry="contemplex", cli_contract=contract)
    return app, prelude.mcp


def test_contemplex_lookup_table_handler_maps_codes_and_renders_a_panel(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _contemplex(prelude, monkeypatch)
    app, _ = _wire_contemplex(prelude, mod.CONTEMPLEX_CLI)
    capsys.readouterr()

    assert _run(app, ["session_not_found"]) == 3
    captured = capsys.readouterr()
    out = _plain(captured.out)
    assert "contemplex error" in out and "SESSION_NOT_FOUND" in out and "s1" in out
    assert captured.err == ""  # no F1 line: the handler rendered the report

    assert _run(app, ["gate_blocked"]) == 4
    assert "GATE_BLOCKED" in _plain(capsys.readouterr().out)

    assert _run(app, ["write_failed"]) == 6
    capsys.readouterr()

    # STAGING_FAILED is not in _EXIT_CODES: the panel names it, and the exit is 1, as today.
    assert _run(app, ["staging_failed"]) == 1
    out = _plain(capsys.readouterr().out)
    assert "STAGING_FAILED" in out and "disk full" in out

    # A non-contemplex exception: the Exception fallback renders an INTERNAL panel, exit 1.
    assert _run(app, ["runtime_boom"]) == 1
    captured = capsys.readouterr()
    out = _plain(captured.out)
    assert "INTERNAL" in out and "RuntimeError: boom" in out
    assert captured.err == ""

    assert _run(app, ["fine"]) == 0


def test_contemplex_table_is_the_real_exit_codes_table(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The example's ``_EXIT_CODES`` is a copy of ``contemplex/cli.py:43-52``; pin its shape."""
    mod = _contemplex(prelude, monkeypatch)
    assert mod._EXIT_CODES == {
        "INVALID_INPUT": 2,
        "INVALID_TASK_TYPE": 2,
        "SESSION_NOT_FOUND": 3,
        "PHASE_MISMATCH": 4,
        "GATE_BLOCKED": 4,
        "CORRUPT_SESSION": 5,
        "WRITE_FAILED": 6,
        "INTERNAL": 1,
    }
    assert "STAGING_FAILED" not in mod._EXIT_CODES
    assert {c.value for c in mod.ErrorCode} >= set(mod._EXIT_CODES) | {"STAGING_FAILED"}


def test_contemplex_without_the_contract_is_exit_1_with_the_f1_line(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Negative control: the codes above come from the contract, not from the stubs."""
    _contemplex(prelude, monkeypatch)
    app, _ = _wire_contemplex(prelude, CliContract())
    capsys.readouterr()
    assert _run(app, ["session_not_found"]) == 1
    assert capsys.readouterr().err == "Error (SessionNotFound): Session s1 not found\n"


def test_exit_code_attr_covers_int_attributes_only_not_string_codes(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The guide's int-only note: a StrEnum ``code`` falls back to ``default``, so
    contemplex needs the lookup-table handler."""
    _contemplex(prelude, monkeypatch)
    contract = CliContract(
        exit_codes={
            prelude.modules["contemplex.errors"].ContemplexError: exit_code_attr("code")
        }
    )
    app, _ = _wire_contemplex(prelude, contract)
    capsys.readouterr()
    assert _run(app, ["session_not_found"]) == 1  # not 3: SESSION_NOT_FOUND is a str


# --------------------------------------------------------------------------- 6.10 envelope


def _wire_envelope(mod: Any, result: dict[str, Any], *, app: App | None = None) -> App:
    def envelope_tool() -> dict:
        return result

    register(envelope_tool, registry="envelope")
    app = app or App(name="env")
    wire(
        None,
        app,
        registry="envelope",
        cli_contract=CliContract(format_success=mod._envelope),
    )
    return app


def test_envelope_formatter_exits_with_the_table_code(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    mod = _exec_example("envelope", "envelope_example", monkeypatch)
    app = _wire_envelope(
        mod, {"ok": False, "error_code": "NOT_FOUND", "error": "no such thing"}
    )
    assert _run(app, ["envelope_tool"]) == 3
    captured = capsys.readouterr()
    assert captured.err == "Error (NOT_FOUND): no such thing\n"
    assert captured.out == ""
    end = [f for n, f in _cmd_events(events) if n == "cli.cmd_end"][0]
    assert end["ok"] is False and end["exit_code"] == 3


def test_envelope_unknown_code_exits_1_and_success_prints_payload(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _exec_example("envelope", "envelope_example", monkeypatch)
    app = _wire_envelope(mod, {"ok": False, "error_code": "WEIRD", "error": "?"})
    assert _run(app, ["envelope_tool"]) == 1
    assert capsys.readouterr().err == "Error (WEIRD): ?\n"


def test_envelope_success_prints_the_payload_without_ok(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _exec_example("envelope", "envelope_example", monkeypatch)
    app = _wire_envelope(mod, {"ok": True, "count": 2})
    assert _run(app, ["envelope_tool"]) == 0
    assert json.loads(capsys.readouterr().out) == {"count": 2}


def test_envelope_exit_works_under_a_callable_result_action_too(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A19: ``sys.exit`` from the formatter is honoured under any ``result_action``."""
    mod = _exec_example("envelope", "envelope_example", monkeypatch)
    seen: list[Any] = []
    app = _wire_envelope(
        mod,
        {"ok": False, "error_code": "INVALID_INPUT", "error": "bad"},
        app=App(name="env", result_action=lambda result: seen.append(result)),
    )
    assert _run(app, ["envelope_tool"]) == 2
    assert seen == []


# --------------------------------------------------------------------------- 7 async composite


def test_async_composite_awaits_each_tool_under_one_event_loop(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    # Order: alphex.mcp runs first; the composite imports its tools.
    with pytest.raises(ImportError):
        _exec_example("async-composite", "alphex_audit", monkeypatch)
    _alphex(prelude, monkeypatch)
    prelude.surface.LINT_FINDINGS.append(
        {"alphabet": "protein20", "warning": "unused letters"}
    )
    mod = _exec_example("async-composite", "alphex_audit", monkeypatch)

    capsys.readouterr()
    assert _run(mod.app, ["audit-all"]) == 0
    out = capsys.readouterr().out
    assert "alphabets" in out and "unused letters" in out
    pairs = [(n, f.get("cmd")) for n, f in _cmd_events(events)]
    assert pairs == [("cli.cmd_start", "audit_all"), ("cli.cmd_end", "audit_all")]


def test_async_composite_sub_tool_failure_goes_through_f1(
    prelude: types.SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _alphex(prelude, monkeypatch)
    mod = _exec_example("async-composite", "alphex_audit", monkeypatch)

    def boom() -> list:
        raise ValueError("lint backend down")

    monkeypatch.setattr(prelude.surface, "lint", boom)
    capsys.readouterr()
    assert _run(mod.app, ["audit-all"]) == 1
    assert capsys.readouterr().err == "Error (ValueError): lint backend down\n"


# --------------------------------------------------------------------------- 8 item 7 app.meta


def _wire_meta(
    mod: Any, *, prepare_seen: list[Any], tool_returns: Any, registry: str = "meta"
) -> None:
    def hello(name: str, n: int = 1) -> Any:
        return tool_returns(name, n)

    register(hello, registry=registry)
    wire(
        None,
        mod.app,
        registry=registry,
        cli_contract=CliContract(prepare=lambda ctx: prepare_seen.append(mod.VERBOSE)),
    )


def test_app_meta_global_option_reaches_consumer_state_and_the_command(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _exec_example("app-meta", "meta_example", monkeypatch)
    assert mod.VERBOSE is False
    seen: list[Any] = []
    _wire_meta(
        mod, prepare_seen=seen, tool_returns=lambda name, n: {"name": name, "n": n}
    )
    assert _run(mod.app.meta, ["--verbose", "hello", "world", "--n", "3"]) == 0
    assert mod.VERBOSE is True  # the global flag reached module state ...
    assert seen == [True]  # ... before the command's prepare ran.


def test_app_meta_without_the_flag_leaves_state_false(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: the state is set by the flag, not by running the meta-app."""
    mod = _exec_example("app-meta", "meta_example", monkeypatch)
    seen: list[Any] = []
    _wire_meta(
        mod, prepare_seen=seen, tool_returns=lambda name, n: {"name": name, "n": n}
    )
    assert _run(mod.app.meta, ["hello", "world"]) == 0
    assert mod.VERBOSE is False
    assert seen == [False]


def test_app_meta_inner_result_reaches_the_outer_result_action(
    prelude: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default action: an int result of the inner command becomes the outer exit code (A16).
    mod = _exec_example("app-meta", "meta_example", monkeypatch)
    _wire_meta(mod, prepare_seen=[], tool_returns=lambda name, n: 7)
    assert _run(mod.app.meta, ["--verbose", "hello", "world"]) == 7

    # A callable result_action sees the inner command's value, exactly once.
    mod2 = _exec_example("app-meta", "meta_example2", monkeypatch)
    received: list[Any] = []
    mod2.app.result_action = lambda result: received.append(result)
    _wire_meta(
        mod2,
        prepare_seen=[],
        tool_returns=lambda name, n: {"name": name, "n": n},
        registry="meta2",
    )
    assert _run(mod2.app.meta, ["--verbose", "hello", "world", "--n", "3"]) == 0
    assert received == [{"name": "world", "n": 3}]


def test_cisternal_public_names_used_by_the_guide_exist() -> None:
    for name in (
        "CliContract",
        "CliOption",
        "CliContext",
        "json_option",
        "default_report",
        "exit_code_attr",
        "cli_command",
        "cli_group",
    ):
        assert hasattr(cisternal, name), name
