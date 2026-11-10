"""CLI integration tests for `cisternal usage` command (Spec §C0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisternal.cli import app


def test_cli_usage_help() -> None:
    """`cisternal usage --help` exits 0."""
    with pytest.raises(SystemExit) as exc:
        app(["usage", "--help"])
    assert exc.value.code == 0


def test_cli_usage_show_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`cisternal usage --show-paths` prints resolved paths and winning layer."""
    sess_dir = tmp_path / "my_sessions"
    sess_dir.mkdir()
    with pytest.raises(SystemExit) as exc:
        app(["usage", "--show-paths", "--sessions-dir", str(sess_dir), "--no-summary"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Sessions directory:" in captured.out
    assert str(sess_dir) in captured.out
    assert "argument" in captured.out


def test_cli_usage_off_switch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`CISTERNAL_SESSIONS_DIR=off` reports sessions disabled."""
    monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", "off")
    with pytest.raises(SystemExit) as exc:
        app(["usage"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Sessions telemetry disabled (layer: off)" in captured.out


def test_cli_usage_json_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`cisternal usage --json` outputs valid JSON adhering to telemetry schema."""
    projects_dir = tmp_path / "projects"
    sess_file = projects_dir / "my-repo" / "session1.jsonl"
    sess_file.parent.mkdir(parents=True)
    sess_file.write_text(
        """{"type": "init", "session_id": "s1", "cwd": "/home/user/my-repo"}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "c1", "name": "mcp__bathos__run_sql", "input": {}}]}}
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        app(["usage", "--json", "--projects-dir", str(projects_dir)])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["version"] == "1.0"
    assert doc["metadata"]["sessions_total"] == 1
    assert "main_interactive" in doc["stratified"]
    assert "bathos/run_sql" in doc["stratified"]["combined"]["mcp_calls"]


def test_cli_usage_invalid_option_exit_2() -> None:
    """Cyclopts raises SystemExit(2) on invalid command options."""
    with pytest.raises(SystemExit) as exc:
        app(["usage", "--invalid-nonexistent-flag"])
    assert exc.value.code == 2
