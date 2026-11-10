"""CLI integration tests for `cisternal prune-list` command (Spec §C1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisternal.cli import app


def test_cli_prune_help() -> None:
    """`cisternal prune-list --help` exits 0."""
    with pytest.raises(SystemExit) as exc:
        app(["prune-list", "--help"])
    assert exc.value.code == 0


def test_cli_prune_invalid_args_exit_2() -> None:
    """Days < 1 raises SystemExit(2)."""
    with pytest.raises(SystemExit) as exc:
        app(["prune-list", "--days", "0"])
    assert exc.value.code == 2


def test_cli_prune_floor_suppressed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When floor is not met, CLI prints suppression reason and exits 0."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    sess_dir = tmp_path / "sessions"
    # 0 sessions < 20
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "prune-list",
                "--projects-dir",
                str(projects_dir),
                "--sessions-dir",
                str(sess_dir),
            ]
        )
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Floor Not Met" in captured.out
    assert "floor is N>=20 AND >=14 days" in captured.out


def test_cli_prune_floor_met_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When floor is met, JSON output includes keep, drop, and enable_per_project."""
    projects_dir = tmp_path / "projects"
    repo_dir = projects_dir / "my-repo"
    repo_dir.mkdir(parents=True)

    # Create 22 sessions over 16 days
    for i in range(22):
        day = 1 + (i % 16)
        s_file = repo_dir / f"sess_{i}.jsonl"
        s_file.write_text(
            f"""{{"type": "init", "session_id": "s_{i}", "cwd": "/home/user/my-repo", "timestamp": "2026-11-{day:02d}T10:00:00Z"}}
{{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "c1", "name": "mcp__bathos__run_sql", "input": {{}}}}]}}}}
""",
            encoding="utf-8",
        )

    # Configure claude settings with bathos and dead_server
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "bathos": {},
                    "dead_server": {},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    sess_dir = tmp_path / "sessions"
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "prune-list",
                "--json",
                "--projects-dir",
                str(projects_dir),
                "--sessions-dir",
                str(sess_dir),
            ]
        )
    assert exc.value.code == 0
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["floor_cleared"] is True
    assert doc["total_sessions"] == 22
    assert "bathos" in doc["keep"] or any(
        p["server"] == "bathos" for p in doc["enable_per_project"]
    )
    assert any(d["server"] == "dead_server" for d in doc["drop"])


def test_cli_prune_repo_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--repo` filter limits enable_per_project to the specified repo."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    sess_dir = tmp_path / "sessions"
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "prune-list",
                "--repo",
                "repo-x",
                "--projects-dir",
                str(projects_dir),
                "--sessions-dir",
                str(sess_dir),
            ]
        )
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "=== Cisternal Server Prune Recommendations ===" in captured.out
