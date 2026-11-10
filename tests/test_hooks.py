"""Tests for Claude Code client hooks: PreToolUse and PostToolUse (Spec §C5)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import time
from typing import Any

import pytest

from cisternal.cli import app
from cisternal.usage.hooks import (
    handle_post_tool_use,
    handle_pre_tool_use,
)
from cisternal.usage.paths import resolve_sessions_dir
from cisternal.usage.registrations import ActiveRegistrations, scan_active_registrations

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hooks" / "post_tool_use"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _REPO_ROOT / ".praxia" / "manifest.toml"


def _load_fixture(name: str) -> dict[str, Any]:
    fixture_path = _FIXTURES_DIR / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _invoke_cli(args: list[str]) -> None:
    """Invoke CLI app and assert exit code 0 (cyclopts raises SystemExit(0))."""
    try:
        app(args)
    except SystemExit as exc:
        assert exc.code == 0, f"CLI exited with non-zero code {exc.code}"


@pytest.fixture()
def mock_hook_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Hermetic hook environment with mock settings and manifest registrations."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True)
    fake_xdg = tmp_path / "xdg"
    fake_xdg.mkdir(parents=True)
    fake_sessions = tmp_path / "sessions"
    fake_sessions.mkdir(parents=True)
    fake_claude = fake_home / ".claude"
    fake_claude.mkdir(parents=True)

    fake_mkt = tmp_path / "marketplace"
    for p in ("bathos", "contemplex", "myxcel"):
        p_dir = fake_mkt / "plugins" / p / ".claude-plugin"
        p_dir.mkdir(parents=True)
        (p_dir / "plugin.json").write_text(
            json.dumps({"mcpServers": {p: {}}}),
            encoding="utf-8",
        )

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(fake_xdg))
    monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", str(fake_sessions))
    monkeypatch.setenv("CISTERNAL_PLUGIN_MARKETPLACE", str(fake_mkt))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    # Write mock settings enabling bathos, contemplex, and myxcel plugins
    settings_file = fake_claude / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "enabledPlugins": {
                    "bathos": True,
                    "contemplex": True,
                    "myxcel": True,
                }
            }
        ),
        encoding="utf-8",
    )

    return {
        "home": fake_home,
        "xdg": fake_xdg,
        "sessions": fake_sessions,
        "claude": fake_claude,
        "marketplace": fake_mkt,
    }


class TestPostToolUseFixturesAndControls:
    """Test error classification, fixtures, and control behaviors per Spec §C5."""

    @pytest.mark.parametrize(
        ("adapter", "expected_tool", "expected_code", "expected_family"),
        [
            ("bathos", "bathos/run_sql", "SQLITE_ERROR", "bathos_query"),
            (
                "contemplex",
                "contemplex/brainstorm_reply",
                "GATE_BLOCKED",
                "contemplex_brainstorm",
            ),
            ("xperiri", "xperiri/run_experiment", "INVALID_CONFIG", None),
            ("myxcel", "myxcel/job_status", "JobNotFoundError", "myxcel_slurm"),
            ("passthrough", "passthrough/echo", "PROTOCOL_ERROR", None),
        ],
    )
    def test_adapter_fixtures_success_and_error(
        self,
        mock_hook_env: dict[str, Path],
        adapter: str,
        expected_tool: str,
        expected_code: str,
        expected_family: str | None,
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]

        # 1. Success fixture: must return False and write NO ledger record
        succ_payload = _load_fixture(f"{adapter}_success.json")
        res_succ = handle_post_tool_use(
            succ_payload,
            sessions_dir=sessions_dir,
            families={
                "bathos_query": ("bathos/run_sql",),
                "contemplex_brainstorm": ("contemplex/brainstorm_reply",),
                "myxcel_slurm": ("myxcel/job_status",),
            },
        )
        assert res_succ is False
        succ_session = succ_payload["session_id"]
        assert not (sessions_dir / succ_session / "errors.jsonl").exists()

        # 2. Error fixture: must return True and append exactly 1 record to errors.jsonl
        err_payload = _load_fixture(f"{adapter}_error.json")
        res_err = handle_post_tool_use(
            err_payload,
            sessions_dir=sessions_dir,
            families={
                "bathos_query": ("bathos/run_sql",),
                "contemplex_brainstorm": ("contemplex/brainstorm_reply",),
                "myxcel_slurm": ("myxcel/job_status",),
            },
        )
        assert res_err is True

        err_session = err_payload["session_id"]
        ledger_path = sessions_dir / err_session / "errors.jsonl"
        assert ledger_path.is_file()

        lines = [
            line.strip()
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        record = json.loads(lines[0])

        assert record["session_id"] == err_session
        assert record["tool"] == expected_tool
        assert record["error_code"] == expected_code
        assert record["family"] == expected_family
        assert record["source"] == "post_tool_use"
        assert "timestamp" in record

    def test_control_bash_error_negative(self, mock_hook_env: dict[str, Path]) -> None:
        """Control 1 (Negative): Non-MCP tool (Bash) error must NEVER be logged."""
        sessions_dir = mock_hook_env["sessions"]
        payload = _load_fixture("control_bash_error.json")
        result = handle_post_tool_use(payload, sessions_dir=sessions_dir)
        assert result is False
        assert not (sessions_dir / payload["session_id"] / "errors.jsonl").exists()

    def test_control_nested_error_success_positive(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        """Control 2 (Positive): Result rows containing 'error' column when ok=true is not an error."""
        sessions_dir = mock_hook_env["sessions"]
        payload = _load_fixture("control_nested_error_success.json")
        result = handle_post_tool_use(payload, sessions_dir=sessions_dir)
        assert result is False
        assert not (sessions_dir / payload["session_id"] / "errors.jsonl").exists()

    def test_non_mcp_tool_ignored(self, mock_hook_env: dict[str, Path]) -> None:
        sessions_dir = mock_hook_env["sessions"]
        payload = {
            "session_id": "sess_misc_01",
            "tool_name": "Read",
            "tool_response": {"error": "file not found", "is_error": True},
        }
        assert handle_post_tool_use(payload, sessions_dir=sessions_dir) is False
        assert not (sessions_dir / "sess_misc_01" / "errors.jsonl").exists()

    def test_post_tool_use_failure_event_handling(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        """Wire event PostToolUseFailure is recognized as protocol error (RISK-01)."""
        sessions_dir = mock_hook_env["sessions"]
        payload = {
            "session_id": "sess_fail_01",
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "mcp__bathos__run_sql",
            "tool_response": {"text": "Process crashed: exit code 1"},
        }
        res = handle_post_tool_use(payload, sessions_dir=sessions_dir)
        assert res is True
        ledger = sessions_dir / "sess_fail_01" / "errors.jsonl"
        assert ledger.is_file()
        rec = json.loads(ledger.read_text(encoding="utf-8").strip())
        assert rec["error_code"] == "PROTOCOL_ERROR"
        assert rec["tool"] == "bathos/run_sql"

    def test_fail_open_on_disabled_sessions_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When sessions_dir is off, hook fails open returning False."""
        monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", "off")
        payload = _load_fixture("bathos_error.json")
        assert handle_post_tool_use(payload) is False

    def test_post_tool_use_declared_servers_longest_suffix(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        """Finding D1: handle_post_tool_use resolves multi-segment plugin names via declared_servers."""
        sessions_dir = mock_hook_env["sessions"]
        regs = ActiveRegistrations(
            servers=("bathos",),
            tools={"bathos/run_sql": "mcp__plugin_mycustomplugin_bathos__run_sql"},
            families={"bathos_query": ("bathos/run_sql",)},
        )
        payload = {
            "session_id": "sess_d1_01",
            "tool_name": "mcp__plugin_mycustomplugin_bathos__run_sql",
            "tool_response": {"ok": False, "error_code": "SQL_ERROR", "message": "table missing"},
        }
        res = handle_post_tool_use(payload, sessions_dir=sessions_dir, registrations=regs)
        assert res is True
        ledger = sessions_dir / "sess_d1_01" / "errors.jsonl"
        assert ledger.is_file()
        rec = json.loads(ledger.read_text(encoding="utf-8").strip())
        assert rec["tool"] == "bathos/run_sql"
        assert rec["family"] == "bathos_query"
        assert rec["error_code"] == "SQL_ERROR"

    def test_post_tool_use_tool_result_proto_error(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        """Finding D3: handle_post_tool_use inspects tool_result payload key for protocol errors."""
        sessions_dir = mock_hook_env["sessions"]
        payload = {
            "session_id": "sess_d3_01",
            "tool_name": "mcp__bathos__run_sql",
            "tool_result": {
                "is_error": True,
                "text": "Subprocess crashed with SIGSEGV",
            },
        }
        res = handle_post_tool_use(payload, sessions_dir=sessions_dir)
        assert res is True
        ledger = sessions_dir / "sess_d3_01" / "errors.jsonl"
        assert ledger.is_file()
        rec = json.loads(ledger.read_text(encoding="utf-8").strip())
        assert rec["error_code"] == "PROTOCOL_ERROR"
        assert rec["tool"] == "bathos/run_sql"
        assert rec["message"] == "Subprocess crashed with SIGSEGV"

    def test_is_suppressed_unicode_decode_error_resilience(
        self, tmp_path: Path
    ) -> None:
        """Finding D2: is_suppressed is resilient against corrupt non-UTF-8 bytes in error ledger."""
        from cisternal.usage.hooks import is_suppressed

        ledger = tmp_path / "corrupt_errors.jsonl"
        # File with corrupt binary bytes before a valid line
        ledger.write_bytes(b"\x80\x81\xff\xfe\n{\"tool\": \"bathos/run_sql\", \"family\": \"bathos_query\"}\n")
        assert is_suppressed(ledger, "bathos/run_sql", "bathos_query") is True

        # Pure corrupt bytes without valid line fails open (returns False, does not crash)
        ledger_garbage = tmp_path / "garbage.jsonl"
        ledger_garbage.write_bytes(b"\x80\x81\x82\x90\x91\xff\xfe")
        assert is_suppressed(ledger_garbage, "bathos/run_sql", "bathos_query") is False


class TestPreToolUseNudgeAndParsing:
    """Test PreToolUse CLI interception, wrapper stripping, and advisory delivery."""

    @pytest.fixture()
    def active_regs(self) -> ActiveRegistrations:
        return ActiveRegistrations(
            servers=("bathos", "contemplex", "myxcel"),
            tools={
                "bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql",
                "bathos/get_run": "mcp__plugin_bathos_bathos__get_run",
                "contemplex/brainstorm_start": "mcp__plugin_contemplex_contemplex__brainstorm_start",
                "myxcel/job_status": "mcp__plugin_myxcel_myxcel__job_status",
            },
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {
                        "sql": "bathos/run_sql",
                        "show": "bathos/get_run",
                    },
                    "exclude": ["run"],
                    "tool_family": "bathos_query",
                },
                "ctxp": {
                    "binary": "ctxp",
                    "subcommands": {
                        "start": "contemplex/brainstorm_start",
                    },
                    "exclude": [],
                    "tool_family": "contemplex_brainstorm",
                },
                "myxcel": {
                    "binary": "myxcel",
                    "subcommands": {
                        "status": "myxcel/job_status",
                    },
                    "exclude": ["submit", "cancel"],
                    "tool_family": "myxcel_slurm",
                },
            },
            families={
                "bathos_query": ("bathos/run_sql", "bathos/get_run"),
                "contemplex_brainstorm": ("contemplex/brainstorm_start",),
                "myxcel_slurm": ("myxcel/job_status",),
            },
            plugins={},
        )

    def test_nudge_fires_on_cli_command(
        self, mock_hook_env: dict[str, Path], active_regs: ActiveRegistrations
    ) -> None:
        payload = {
            "session_id": "sess_pre_01",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=mock_hook_env["sessions"],
            registrations=active_regs,
        )
        assert res is not None
        assert "hookSpecificOutput" in res
        output = res["hookSpecificOutput"]
        assert output["hookEventName"] == "PreToolUse"
        assert output["additionalContext"] == (
            "An equivalent MCP tool is available: mcp__plugin_bathos_bathos__run_sql (bathos/run_sql)."
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "rtk bth sql 'SELECT 1'",
            "env X=1 bth sql 'SELECT 1'",
            "cd /tmp && bth sql 'SELECT 1'",
            "bth run foo && bth sql 'SELECT 1'",
        ],
    )
    def test_nudge_with_wrappers_and_compounds(
        self,
        mock_hook_env: dict[str, Path],
        active_regs: ActiveRegistrations,
        cmd: str,
    ) -> None:
        payload = {
            "session_id": "sess_pre_02",
            "tool_name": "Bash",
            "tool_input": {"command": cmd},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=mock_hook_env["sessions"],
            registrations=active_regs,
        )
        assert res is not None
        assert (
            "mcp__plugin_bathos_bathos__run_sql (bathos/run_sql)"
            in res["hookSpecificOutput"]["additionalContext"]
        )

    def test_no_nudge_on_excluded_subcommand(
        self, mock_hook_env: dict[str, Path], active_regs: ActiveRegistrations
    ) -> None:
        payload = {
            "session_id": "sess_pre_03",
            "tool_name": "Bash",
            "tool_input": {"command": "bth run exp_01"},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=mock_hook_env["sessions"],
            registrations=active_regs,
        )
        assert res is None

    def test_no_nudge_on_unknown_flags(
        self, mock_hook_env: dict[str, Path], active_regs: ActiveRegistrations
    ) -> None:
        payload = {
            "session_id": "sess_pre_04",
            "tool_name": "Bash",
            "tool_input": {"command": "bth --unknown sql 'SELECT 1'"},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=mock_hook_env["sessions"],
            registrations=active_regs,
        )
        assert res is None

    def test_no_nudge_on_inactive_server(self, mock_hook_env: dict[str, Path]) -> None:
        # Registrations where bathos is inactive
        empty_regs = ActiveRegistrations(
            servers=(),
            tools={},
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {"sql": "bathos/run_sql"},
                    "exclude": [],
                }
            },
            families={},
            plugins={},
        )
        payload = {
            "session_id": "sess_pre_05",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=mock_hook_env["sessions"],
            registrations=empty_regs,
        )
        assert res is None


class TestErrorSuppression:
    """Test session error suppression rules (tool-level, family-level, multi-segment)."""

    def test_tool_error_suppresses_nudge(self, mock_hook_env: dict[str, Path]) -> None:
        sessions_dir = mock_hook_env["sessions"]
        session_id = "sess_supp_01"

        # Log bathos/run_sql error
        err_payload = _load_fixture("bathos_error.json")
        err_payload["session_id"] = session_id
        assert handle_post_tool_use(err_payload, sessions_dir=sessions_dir) is True

        regs = ActiveRegistrations(
            servers=("bathos",),
            tools={"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {"sql": "bathos/run_sql"},
                    "exclude": [],
                    "tool_family": "bathos_query",
                }
            },
            families={"bathos_query": ("bathos/run_sql",)},
            plugins={},
        )

        # PreToolUse on bth sql must now be suppressed
        nudge = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            },
            sessions_dir=sessions_dir,
            registrations=regs,
        )
        assert nudge is None

    def test_family_error_suppresses_family_members(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]
        session_id = "sess_supp_02"

        # Manually create error record for bathos/get_run with family bathos_query
        ledger_path = sessions_dir / session_id / "errors.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-11-09T16:00:00Z",
                    "session_id": session_id,
                    "tool": "bathos/get_run",
                    "family": "bathos_query",
                    "error_code": "NOT_FOUND",
                    "message": "Run not found",
                    "source": "post_tool_use",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        regs = ActiveRegistrations(
            servers=("bathos",),
            tools={"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {"sql": "bathos/run_sql"},
                    "exclude": [],
                    "tool_family": "bathos_query",
                }
            },
            families={"bathos_query": ("bathos/run_sql", "bathos/get_run")},
            plugins={},
        )

        # Nudge for bathos/run_sql is suppressed by family match
        nudge = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            },
            sessions_dir=sessions_dir,
            registrations=regs,
        )
        assert nudge is None

    def test_cross_session_isolation(self, mock_hook_env: dict[str, Path]) -> None:
        sessions_dir = mock_hook_env["sessions"]

        # Log error in session A
        err_payload = _load_fixture("bathos_error.json")
        err_payload["session_id"] = "session_A"
        handle_post_tool_use(err_payload, sessions_dir=sessions_dir)

        regs = ActiveRegistrations(
            servers=("bathos",),
            tools={"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {"sql": "bathos/run_sql"},
                    "exclude": [],
                    "tool_family": "bathos_query",
                }
            },
            families={"bathos_query": ("bathos/run_sql",)},
            plugins={},
        )

        # PreToolUse in session B must NOT be suppressed
        nudge = handle_pre_tool_use(
            {
                "session_id": "session_B",
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            },
            sessions_dir=sessions_dir,
            registrations=regs,
        )
        assert nudge is not None

    def test_multisegment_suppression_falls_through_to_next_active(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        """When first segment is suppressed, hook inspects subsequent segments."""
        sessions_dir = mock_hook_env["sessions"]
        session_id = "sess_supp_03"

        # Suppress bathos/run_sql
        err_payload = _load_fixture("bathos_error.json")
        err_payload["session_id"] = session_id
        handle_post_tool_use(err_payload, sessions_dir=sessions_dir)

        regs = ActiveRegistrations(
            servers=("bathos", "contemplex"),
            tools={
                "bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql",
                "contemplex/brainstorm_start": "mcp__plugin_contemplex_contemplex__brainstorm_start",
            },
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {"sql": "bathos/run_sql"},
                    "exclude": [],
                    "tool_family": "bathos_query",
                },
                "ctxp": {
                    "binary": "ctxp",
                    "subcommands": {"start": "contemplex/brainstorm_start"},
                    "exclude": [],
                    "tool_family": "contemplex_brainstorm",
                },
            },
            families={
                "bathos_query": ("bathos/run_sql",),
                "contemplex_brainstorm": ("contemplex/brainstorm_start",),
            },
            plugins={},
        )

        # Compound: bth sql (suppressed) && ctxp start (not suppressed)
        nudge = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1' && ctxp start"},
            },
            sessions_dir=sessions_dir,
            registrations=regs,
        )
        assert nudge is not None
        assert (
            "contemplex/brainstorm_start"
            in nudge["hookSpecificOutput"]["additionalContext"]
        )


class TestCrossCwdAndColdCacheControls:
    """Test GAP-26 cross-cwd resolution and GAP-23 cold-cache rebuild."""

    def test_cross_cwd_ledger_resolution_control_gap26(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GAP-26: Cross-cwd invocations resolve same sessions dir; decoy pyproject.toml ignored."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        fake_xdg = tmp_path / "xdg"
        fake_xdg.mkdir()
        dir_a = tmp_path / "dir_a"
        dir_a.mkdir()
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()

        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("XDG_STATE_HOME", str(fake_xdg))
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        # Layer 4 is the user config (no baked-in default); point it at fake_xdg.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        (tmp_path / "cfg" / "cisternal").mkdir(parents=True)
        (tmp_path / "cfg" / "cisternal" / "config.toml").write_text(
            f'sessions_dir = "{fake_xdg / "cisternal" / "sessions"}"\n', encoding="utf-8"
        )
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

        # Put a decoy pyproject.toml in dir_b pointing to a fake decoy sessions dir
        decoy_sessions = tmp_path / "decoy_sessions"
        (dir_b / "pyproject.toml").write_text(
            f'[tool.cisternal]\nsessions_dir = "{decoy_sessions}"\n',
            encoding="utf-8",
        )

        session_id = "sess_gap26_01"

        # 1. PostToolUse executed with cwd=dir_a (logs error to Layer 4 XDG sessions dir)
        monkeypatch.chdir(dir_a)
        resolved_a, _ = resolve_sessions_dir(is_hook=True)
        assert resolved_a is not None
        assert resolved_a.is_relative_to(fake_xdg)

        err_payload = _load_fixture("bathos_error.json")
        err_payload["session_id"] = session_id
        res_post = handle_post_tool_use(err_payload)
        assert res_post is True

        # 2. PreToolUse executed with cwd=dir_b (which has decoy pyproject.toml)
        monkeypatch.chdir(dir_b)
        resolved_b, _ = resolve_sessions_dir(is_hook=True)
        # Because is_hook=True and CLAUDE_PROJECT_DIR is unset, Layer 3 is skipped
        assert resolved_b == resolved_a
        assert not decoy_sessions.exists()

        regs = ActiveRegistrations(
            servers=("bathos",),
            tools={"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
            verbs={
                "bth": {
                    "binary": "bth",
                    "subcommands": {"sql": "bathos/run_sql"},
                    "exclude": [],
                    "tool_family": "bathos_query",
                }
            },
            families={"bathos_query": ("bathos/run_sql",)},
            plugins={},
        )

        nudge = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            },
            registrations=regs,
        )
        # Suppressed because both resolved to the same ledger in XDG!
        assert nudge is None

    def test_cold_cache_rebuild_gap23(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        """GAP-23: Missing active_servers.json is rebuilt atomically and emits nudge."""
        sessions_dir = mock_hook_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"
        assert not cache_file.exists()

        payload = {
            "session_id": "sess_gap23_01",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }

        nudge = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
        assert nudge is not None
        assert cache_file.is_file()
        assert "bathos/run_sql" in nudge["hookSpecificOutput"]["additionalContext"]


class TestCliHookCommands:
    """Test CLI commands: cisternal hook {pre-tool-use, post-tool-use, post-tool-failure}."""

    def test_cli_pre_tool_use_stdout(
        self,
        mock_hook_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"
        cache_file.write_text(
            json.dumps(
                {
                    "servers": ["bathos"],
                    "tools": {"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
                    "verbs": {
                        "bth": {
                            "binary": "bth",
                            "subcommands": {"sql": "bathos/run_sql"},
                            "exclude": [],
                            "tool_family": "bathos_query",
                        }
                    },
                    "families": {"bathos_query": ["bathos/run_sql"]},
                    "plugins": {},
                }
            ),
            encoding="utf-8",
        )

        stdin_payload = json.dumps(
            {
                "session_id": "sess_cli_01",
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            }
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)

        _invoke_cli(["hook", "pre-tool-use"])
        out_str = stdout_buf.getvalue().strip()
        assert out_str
        doc = json.loads(out_str)
        assert doc["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "bathos/run_sql" in doc["hookSpecificOutput"]["additionalContext"]

    def test_cli_post_tool_use_ledger_write(
        self,
        mock_hook_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]
        payload = _load_fixture("bathos_error.json")
        payload["session_id"] = "sess_cli_02"

        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)

        _invoke_cli(["hook", "post-tool-use"])
        assert stdout_buf.getvalue() == ""

        ledger = sessions_dir / "sess_cli_02" / "errors.jsonl"
        assert ledger.is_file()

    def test_cli_post_tool_failure_command(
        self,
        mock_hook_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]
        payload = {
            "session_id": "sess_cli_03",
            "tool_name": "mcp__bathos__run_sql",
            "tool_response": {"text": "Fatal server crash"},
        }

        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)

        _invoke_cli(["hook", "post-tool-failure"])
        assert stdout_buf.getvalue() == ""

        ledger = sessions_dir / "sess_cli_03" / "errors.jsonl"
        assert ledger.is_file()
        rec = json.loads(ledger.read_text(encoding="utf-8").strip())
        assert rec["error_code"] == "PROTOCOL_ERROR"

    def test_cli_hooks_alias(
        self,
        mock_hook_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The 'hooks' plural alias behaves identically to 'hook'."""
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)

        _invoke_cli(["hooks", "pre-tool-use"])
        assert stdout_buf.getvalue() == ""

    def test_cli_fail_open_on_bad_stdin(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("not-valid-json{{{"))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)

        _invoke_cli(["hook", "pre-tool-use"])
        assert stdout_buf.getvalue() == ""

    def test_cli_hook_entrypoint_direct(
        self,
        mock_hook_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Direct test of cisternal.usage.cli_hook.main entrypoint."""
        from cisternal.usage.cli_hook import main as cli_hook_main

        sessions_dir = mock_hook_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"
        cache_file.write_text(
            json.dumps(
                {
                    "servers": ["bathos"],
                    "tools": {"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
                    "verbs": {
                        "bth": {
                            "binary": "bth",
                            "subcommands": {"sql": "bathos/run_sql"},
                            "exclude": [],
                            "tool_family": "bathos_query",
                        }
                    },
                    "families": {"bathos_query": ["bathos/run_sql"]},
                    "plugins": {},
                }
            ),
            encoding="utf-8",
        )

        stdin_payload = json.dumps(
            {
                "session_id": "sess_cli_hook_01",
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            }
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)

        ret = cli_hook_main(["pre-tool-use"])
        assert ret == 0
        doc = json.loads(stdout_buf.getvalue().strip())
        assert doc["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

        # Edge cases: empty argv, empty stdin, bad json, non-dict json
        assert cli_hook_main([]) == 0
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert cli_hook_main(["pre-tool-use"]) == 0
        monkeypatch.setattr(sys, "stdin", io.StringIO("not-json"))
        assert cli_hook_main(["pre-tool-use"]) == 0
        monkeypatch.setattr(sys, "stdin", io.StringIO("[1, 2]"))
        assert cli_hook_main(["pre-tool-use"]) == 0


class TestHookPerformanceBenchmark:
    """Benchmark asserting p95 latency <= 150 ms over 100 runs for warm cache and cold rebuild."""

    def test_warm_cache_benchmark_100_runs(
        self, mock_hook_env: dict[str, Path]
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"
        cache_file.write_text(
            json.dumps(
                {
                    "servers": ["bathos"],
                    "tools": {"bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql"},
                    "verbs": {
                        "bth": {
                            "binary": "bth",
                            "subcommands": {"sql": "bathos/run_sql"},
                            "exclude": ["run"],
                            "tool_family": "bathos_query",
                        }
                    },
                    "families": {"bathos_query": ["bathos/run_sql"]},
                    "plugins": {},
                }
            ),
            encoding="utf-8",
        )

        payload = {
            "session_id": "sess_bench_warm",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }

        # Warm up JIT / import caches
        res = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
        assert res is not None

        latencies_ms: list[float] = []
        for _ in range(100):
            t0 = time.perf_counter()
            out = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
            t1 = time.perf_counter()
            assert out is not None
            latencies_ms.append((t1 - t0) * 1000.0)

        latencies_ms.sort()
        # 95th percentile index = 95
        p95 = latencies_ms[95]
        mean_lat = sum(latencies_ms) / len(latencies_ms)
        min_lat = latencies_ms[0]
        max_lat = latencies_ms[-1]

        # Spec budget: p95 <= 150 ms
        assert p95 <= 150.0, f"Warm cache p95 exceeded budget: {p95:.2f} ms > 150.0 ms"
        print(
            f"\n[Warm Benchmark] N=100 min={min_lat:.3f}ms mean={mean_lat:.3f}ms p95={p95:.3f}ms max={max_lat:.3f}ms"
        )

    def test_cold_cache_benchmark_100_runs(
        self, mock_hook_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = mock_hook_env["sessions"]
        payload = {
            "session_id": "sess_bench_cold",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }

        orig_scan = scan_active_registrations

        def wrapped_scan(*args: Any, **kwargs: Any) -> ActiveRegistrations:
            kwargs["manifest_path"] = _MANIFEST_PATH
            return orig_scan(*args, **kwargs)

        monkeypatch.setattr(
            "cisternal.usage.hooks.scan_active_registrations", wrapped_scan
        )

        cache_file = sessions_dir / "active_servers.json"

        latencies_ms: list[float] = []
        for _ in range(100):
            if cache_file.exists():
                cache_file.unlink()

            t0 = time.perf_counter()
            out = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
            t1 = time.perf_counter()
            assert out is not None
            latencies_ms.append((t1 - t0) * 1000.0)

        latencies_ms.sort()
        p95 = latencies_ms[95]
        mean_lat = sum(latencies_ms) / len(latencies_ms)
        min_lat = latencies_ms[0]
        max_lat = latencies_ms[-1]

        # Spec budget: p95 <= 150 ms
        assert p95 <= 150.0, f"Cold cache p95 exceeded budget: {p95:.2f} ms > 150.0 ms"
        print(
            f"\n[Cold Benchmark] N=100 min={min_lat:.3f}ms mean={mean_lat:.3f}ms p95={p95:.3f}ms max={max_lat:.3f}ms"
        )
