"""Adversarial stress test suite for Claude Code PreToolUse nudge, suppression, cross-CWD, and latency.

Author: Milestone M5 Challenger 2 (challenger_m5_2)
Worktree: .claude/worktrees/261106-agy-spec-cycles
"""

from __future__ import annotations

import io
import json
import os
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
from cisternal.usage.registrations import ActiveRegistrations, scan_active_registrations

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _REPO_ROOT / ".praxia" / "manifest.toml"


def _invoke_cli(args: list[str]) -> tuple[int, str]:
    """Invoke CLI capturing exit code and stdout."""
    stdout_buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_buf
    exit_code = 0
    try:
        app(args)
    except SystemExit as exc:
        exit_code = exc.code if exc.code is not None else 0
    finally:
        sys.stdout = old_stdout
    return exit_code, stdout_buf.getvalue()


@pytest.fixture()
def stress_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Hermetic test environment for adversarial tests."""
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


@pytest.fixture()
def sample_regs() -> ActiveRegistrations:
    return ActiveRegistrations(
        servers=("bathos", "contemplex", "myxcel"),
        tools={
            "bathos/run_sql": "mcp__plugin_bathos_bathos__run_sql",
            "bathos/get_run": "mcp__plugin_bathos_bathos__get_run",
            "contemplex/brainstorm_start": "mcp__plugin_contemplex_contemplex__brainstorm_start",
            "contemplex/brainstorm_reply": "mcp__plugin_contemplex_contemplex__brainstorm_reply",
            "myxcel/job_status": "mcp__plugin_myxcel_myxcel__job_status",
            "myxcel/list_jobs": "mcp__plugin_myxcel_myxcel__list_jobs",
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
                    "reply": "contemplex/brainstorm_reply",
                },
                "exclude": [],
                "tool_family": "contemplex_brainstorm",
            },
            "myxcel": {
                "binary": "myxcel",
                "subcommands": {
                    "status": "myxcel/job_status",
                    "list": "myxcel/list_jobs",
                },
                "exclude": ["submit", "cancel"],
                "tool_family": "myxcel_slurm",
            },
        },
        families={
            "bathos_query": ("bathos/run_sql", "bathos/get_run"),
            "contemplex_brainstorm": (
                "contemplex/brainstorm_start",
                "contemplex/brainstorm_reply",
            ),
            "myxcel_slurm": ("myxcel/job_status", "myxcel/list_jobs"),
        },
        plugins={},
    )


class TestAdversarialCompoundCommands:
    """Stress test compound commands, pipelines, redirections, wrappers, and unclosed quotes."""

    @pytest.mark.parametrize(
        ("cmd", "expected_tool_key", "expected_raw_name"),
        [
            # Excluded segment followed by valid segment
            (
                "bth run exp1 && bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # cd segment followed by valid segment
            (
                "cd /tmp && bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Pipe from arbitrary command
            (
                "echo hello | bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # OR operator
            (
                "echo hi || bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Semicolon separated
            (
                "echo 'test'; bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Newline separated
            (
                "export FOO=1\nbth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Chained wrappers: sudo env rtk
            (
                "sudo env VAR=val rtk bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # time + nice + timeout wrappers
            (
                "time nice -n 19 timeout -s 9 30s bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Redirections with 2>&1
            (
                "bth sql 'SELECT 1' 2>&1 > /dev/null",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Three-segment chain: cd -> excluded bth run -> valid bth sql
            (
                "cd /tmp && bth run exp1 || bth sql 'SELECT 1'",
                "bathos/run_sql",
                "mcp__plugin_bathos_bathos__run_sql",
            ),
            # Multi-tool chain: bth run (excluded) -> ctxp start (triggers ctxp)
            (
                "bth run exp1 && ctxp start",
                "contemplex/brainstorm_start",
                "mcp__plugin_contemplex_contemplex__brainstorm_start",
            ),
            # myxcel status with wrapper
            (
                "rtk myxcel status 9999",
                "myxcel/job_status",
                "mcp__plugin_myxcel_myxcel__job_status",
            ),
            # myxcel cancel (excluded) -> myxcel status (nudges)
            (
                "myxcel cancel 1111; myxcel status 2222",
                "myxcel/job_status",
                "mcp__plugin_myxcel_myxcel__job_status",
            ),
        ],
    )
    def test_compound_and_wrapped_commands_nudge(
        self,
        stress_env: dict[str, Path],
        sample_regs: ActiveRegistrations,
        cmd: str,
        expected_tool_key: str,
        expected_raw_name: str,
    ) -> None:
        payload = {
            "session_id": "sess_adv_compound",
            "tool_name": "Bash",
            "tool_input": {"command": cmd},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=stress_env["sessions"],
            registrations=sample_regs,
        )
        assert res is not None, f"Expected nudge for command: {cmd}"
        output = res.get("hookSpecificOutput", {})
        assert output.get("hookEventName") == "PreToolUse"
        context = output.get("additionalContext", "")
        assert expected_raw_name in context
        assert expected_tool_key in context

    @pytest.mark.parametrize(
        "cmd",
        [
            # Excluded commands alone
            "bth run exp01",
            "bth run --flag foo bar",
            "myxcel submit script.slurm",
            "myxcel cancel 9999",
            # Compound of only excluded commands
            "bth run exp01 && myxcel submit job.sh",
            "myxcel cancel 111 && bth run exp02",
            # Unclosed single quote (fail-open)
            "bth sql 'SELECT 1",
            # Unclosed double quote (fail-open)
            'bth sql "SELECT 1',
            # Command substitution before verb (fail-open/skips)
            "echo $(whoami) bth sql 'SELECT 1'",
            # Backtick substitution before verb
            "echo `id` bth sql 'SELECT 1'",
            # Unknown flag before subcommand
            "bth --unknown-flag sql 'SELECT 1'",
            # Unrecognized binary
            "cat /etc/hosts",
            "git status",
            # Non-Bash tool invocation
            "",
        ],
    )
    def test_commands_that_must_not_nudge(
        self,
        stress_env: dict[str, Path],
        sample_regs: ActiveRegistrations,
        cmd: str,
    ) -> None:
        payload = {
            "session_id": "sess_adv_no_nudge",
            "tool_name": "Bash",
            "tool_input": {"command": cmd},
        }
        res = handle_pre_tool_use(
            payload,
            sessions_dir=stress_env["sessions"],
            registrations=sample_regs,
        )
        assert res is None, f"Command should NOT have nudged: {cmd}"


class TestAdversarialSuppressionLogic:
    """Stress test session error suppression, family hierarchy, and multisegment fallthrough."""

    def test_tool_level_suppression_exact_match(
        self, stress_env: dict[str, Path], sample_regs: ActiveRegistrations
    ) -> None:
        sessions_dir = stress_env["sessions"]
        session_id = "sess_supp_tool"
        ledger_path = sessions_dir / session_id / "errors.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # Write error for bathos/run_sql (no family specified)
        ledger_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-11-10T00:00:00Z",
                    "session_id": session_id,
                    "tool": "bathos/run_sql",
                    "family": None,
                    "error_code": "SQLITE_ERROR",
                    "message": "no such table: runs",
                    "source": "post_tool_use",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # bth sql is suppressed
        res_sql = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            },
            sessions_dir=sessions_dir,
            registrations=sample_regs,
        )
        assert res_sql is None

        # bth show (bathos/get_run) is NOT suppressed because family wasn't set in the record
        res_show = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth show run_01"},
            },
            sessions_dir=sessions_dir,
            registrations=sample_regs,
        )
        assert res_show is not None
        assert "bathos/get_run" in res_show["hookSpecificOutput"]["additionalContext"]

    def test_family_level_suppression_suppresses_all_members(
        self, stress_env: dict[str, Path], sample_regs: ActiveRegistrations
    ) -> None:
        sessions_dir = stress_env["sessions"]
        session_id = "sess_supp_family"
        ledger_path = sessions_dir / session_id / "errors.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # Write error with family "bathos_query"
        ledger_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-11-10T00:00:00Z",
                    "session_id": session_id,
                    "tool": "bathos/get_run",
                    "family": "bathos_query",
                    "error_code": "NOT_FOUND",
                    "message": "run not found",
                    "source": "post_tool_use",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Both bth sql and bth show belong to family bathos_query and must be suppressed
        for cmd in ("bth sql 'SELECT 1'", "bth show run_123"):
            res = handle_pre_tool_use(
                {
                    "session_id": session_id,
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                },
                sessions_dir=sessions_dir,
                registrations=sample_regs,
            )
            assert res is None, f"Expected {cmd} to be suppressed by family error"

        # ctxp start is in contemplex_brainstorm, NOT bathos_query -> must NOT be suppressed
        res_ctxp = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "ctxp start"},
            },
            sessions_dir=sessions_dir,
            registrations=sample_regs,
        )
        assert res_ctxp is not None

    def test_valid_lines_before_corrupted_data_are_honored(
        self, stress_env: dict[str, Path], sample_regs: ActiveRegistrations
    ) -> None:
        """Valid error records before any truncated or corrupted line are correctly recognized."""
        sessions_dir = stress_env["sessions"]
        session_id = "sess_valid_before_corrupt"
        ledger_path = sessions_dir / session_id / "errors.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # Valid record followed by trailing corrupt line
        content = (
            json.dumps(
                {
                    "session_id": session_id,
                    "tool": "bathos/run_sql",
                    "family": "bathos_query",
                }
            )
            + "\n"
            + "CORRUPT_TRAILING_LINE_12345\n"
        )
        ledger_path.write_text(content, encoding="utf-8")

        # bth sql is suppressed because the first valid line matched
        res_sql = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            },
            sessions_dir=sessions_dir,
            registrations=sample_regs,
        )
        assert res_sql is None

    def test_multisegment_suppression_cascade(
        self, stress_env: dict[str, Path], sample_regs: ActiveRegistrations
    ) -> None:
        """3 segments: segment 1 suppressed, segment 2 excluded, segment 3 nudges."""
        sessions_dir = stress_env["sessions"]
        session_id = "sess_cascade"
        ledger_path = sessions_dir / session_id / "errors.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # Suppress bathos_query family
        ledger_path.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "tool": "bathos/run_sql",
                    "family": "bathos_query",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Command: bth sql (suppressed) && bth run exp (excluded) && myxcel status 123 (active, not suppressed)
        compound = "bth sql 'SELECT 1' && bth run exp01 && myxcel status 9999"
        res = handle_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": compound},
            },
            sessions_dir=sessions_dir,
            registrations=sample_regs,
        )
        assert res is not None
        assert "myxcel/job_status" in res["hookSpecificOutput"]["additionalContext"]


class TestAdversarialCrossCwdResolution:
    """Stress test GAP-26 cross-CWD ledger resolution and decoy pyproject.toml."""

    def test_cross_cwd_with_multiple_decoys_and_subdirectories(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_regs: ActiveRegistrations,
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        fake_xdg = tmp_path / "xdg"
        fake_xdg.mkdir()

        # Create multiple arbitrary directories with decoys
        dir_work = tmp_path / "workspace" / "sub" / "deep"
        dir_work.mkdir(parents=True)
        decoy_a = tmp_path / "decoy_a"
        decoy_a.mkdir()
        decoy_b = tmp_path / "decoy_b"
        decoy_b.mkdir()

        (dir_work / "pyproject.toml").write_text(
            '[tool.cisternal]\nsessions_dir = "/tmp/fake_dir_work"\n', encoding="utf-8"
        )
        (decoy_a / "pyproject.toml").write_text(
            '[tool.cisternal]\nsessions_dir = "/tmp/fake_decoy_a"\n', encoding="utf-8"
        )
        (decoy_b / "pyproject.toml").write_text(
            '[tool.cisternal]\nsessions_dir = "/tmp/fake_decoy_b"\n', encoding="utf-8"
        )

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

        session_id = "sess_adv_cross_cwd"

        # 1. PostToolUse executed in decoy_a
        monkeypatch.chdir(decoy_a)
        post_payload = {
            "session_id": session_id,
            "tool_name": "mcp__plugin_bathos_bathos__run_sql",
            "tool_response": {
                "ok": False,
                "error_code": "SQLITE_BUSY",
                "error": "database is locked",
            },
        }
        res_post = handle_post_tool_use(
            post_payload,
            families={"bathos_query": ("bathos/run_sql",)},
        )
        assert res_post is True

        # Check that error was written to XDG state directory, NOT decoy_a's /tmp/fake_decoy_a
        expected_xdg_sessions = fake_xdg / "cisternal" / "sessions"
        assert (expected_xdg_sessions / session_id / "errors.jsonl").is_file()
        assert not Path("/tmp/fake_decoy_a").exists()

        # 2. PreToolUse executed in deep subdirectory of dir_work
        monkeypatch.chdir(dir_work)
        pre_payload = {
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        res_pre = handle_pre_tool_use(pre_payload, registrations=sample_regs)
        # Must be suppressed because both resolve to expected_xdg_sessions!
        assert res_pre is None
        assert not Path("/tmp/fake_dir_work").exists()

        # 3. PreToolUse executed in decoy_b
        monkeypatch.chdir(decoy_b)
        res_pre_b = handle_pre_tool_use(pre_payload, registrations=sample_regs)
        assert res_pre_b is None
        assert not Path("/tmp/fake_decoy_b").exists()

    def test_cross_cwd_anchored_to_claude_project_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_regs: ActiveRegistrations,
    ) -> None:
        """When CLAUDE_PROJECT_DIR is set, sessions are anchored to that project root."""
        proj_root = tmp_path / "actual_project"
        proj_root.mkdir()
        decoy_dir = tmp_path / "outside_dir"
        decoy_dir.mkdir()

        custom_sessions = proj_root / "my_sessions"
        (proj_root / "pyproject.toml").write_text(
            f'[tool.cisternal]\nsessions_dir = "{custom_sessions}"\n',
            encoding="utf-8",
        )
        (decoy_dir / "pyproject.toml").write_text(
            '[tool.cisternal]\nsessions_dir = "/tmp/decoy_bad"\n',
            encoding="utf-8",
        )

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj_root))
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)

        session_id = "sess_claude_proj_anchor"

        # Run PostToolUse from decoy_dir
        monkeypatch.chdir(decoy_dir)
        post_payload = {
            "session_id": session_id,
            "tool_name": "mcp__plugin_bathos_bathos__run_sql",
            "tool_response": {"ok": False, "error_code": "ERR", "message": "fail"},
        }
        assert handle_post_tool_use(post_payload) is True
        assert (custom_sessions / session_id / "errors.jsonl").is_file()

        # Run PreToolUse from outside directory
        pre_payload = {
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        assert handle_pre_tool_use(pre_payload, registrations=sample_regs) is None


class TestAdversarialColdCacheAndFreshness:
    """Stress test GAP-23 cold-cache atomic rebuild, cache invalidation on modified settings, and corrupted cache."""

    def test_cold_cache_atomic_creation_and_no_leftover_tmp_files(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = stress_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"
        if cache_file.exists():
            cache_file.unlink()

        orig_scan = scan_active_registrations

        def wrapped_scan(*args: Any, **kwargs: Any) -> ActiveRegistrations:
            kwargs["manifest_path"] = _MANIFEST_PATH
            return orig_scan(*args, **kwargs)

        monkeypatch.setattr(
            "cisternal.usage.hooks.scan_active_registrations", wrapped_scan
        )

        payload = {
            "session_id": "sess_cold_atomic",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        res = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
        assert res is not None
        assert cache_file.is_file()

        # Verify no .tmp files were left behind in sessions_dir
        tmp_files = list(sessions_dir.glob("*.tmp.*"))
        assert len(tmp_files) == 0

        # Verify cache content is valid JSON and contains required keys
        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "servers" in cache_data
        assert "tools" in cache_data
        assert "bathos/run_sql" in cache_data["tools"]

    def test_stale_cache_rebuilt_when_settings_mtime_advances(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = stress_env["sessions"]
        claude_dir = stress_env["claude"]
        settings_file = claude_dir / "settings.json"
        cache_file = sessions_dir / "active_servers.json"

        orig_scan = scan_active_registrations

        def wrapped_scan(*args: Any, **kwargs: Any) -> ActiveRegistrations:
            kwargs["manifest_path"] = _MANIFEST_PATH
            return orig_scan(*args, **kwargs)

        monkeypatch.setattr(
            "cisternal.usage.hooks.scan_active_registrations", wrapped_scan
        )

        # 1. Populate initial cache
        payload = {
            "session_id": "sess_mtime_rebuild",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        handle_pre_tool_use(payload, sessions_dir=sessions_dir)
        assert cache_file.is_file()
        initial_mtime = cache_file.stat().st_mtime

        # Sleep briefly to ensure mtime timestamp differences
        time.sleep(0.05)

        # 2. Modify settings.json to advance its mtime
        new_settings = json.loads(settings_file.read_text(encoding="utf-8"))
        new_settings["enabledPlugins"]["extra_plugin"] = True
        settings_file.write_text(json.dumps(new_settings), encoding="utf-8")
        # Ensure settings mtime is strictly greater than initial cache mtime
        now = time.time() + 2.0
        os.utime(settings_file, (now, now))

        # 3. Next invocation must detect stale cache and rebuild
        handle_pre_tool_use(payload, sessions_dir=sessions_dir)
        new_cache_mtime = cache_file.stat().st_mtime
        assert new_cache_mtime > initial_mtime

    def test_corrupted_cache_file_auto_recovers(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When active_servers.json is corrupt (truncated/garbage), it is gracefully re-generated."""
        sessions_dir = stress_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"
        cache_file.write_text("{TRUNCATED CORRUPT JSON", encoding="utf-8")

        orig_scan = scan_active_registrations

        def wrapped_scan(*args: Any, **kwargs: Any) -> ActiveRegistrations:
            kwargs["manifest_path"] = _MANIFEST_PATH
            return orig_scan(*args, **kwargs)

        monkeypatch.setattr(
            "cisternal.usage.hooks.scan_active_registrations", wrapped_scan
        )

        payload = {
            "session_id": "sess_corrupt_cache",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        res = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
        assert res is not None
        # Cache file should be repaired
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "servers" in data


class TestAdversarialFailOpenSemantics:
    """Stress test fail-open semantics: corrupt config files, unreadable dirs, fuzzing, exit 0, no stdout."""

    def test_corrupt_settings_json_exits_0_with_no_stdout(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When settings.json contains corrupt syntax, CLI exits 0 with empty stdout (no nudge)."""
        settings_file = stress_env["claude"] / "settings.json"
        settings_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

        # Invalidate cache so scan_active_registrations runs against the corrupt settings.json
        cache_file = stress_env["sessions"] / "active_servers.json"
        if cache_file.exists():
            cache_file.unlink()

        stdin_payload = json.dumps(
            {
                "session_id": "sess_corrupt_settings",
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            }
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
        code, stdout = _invoke_cli(["hook", "pre-tool-use"])
        assert code == 0
        assert stdout.strip() == ""

    def test_unreadable_settings_json_exits_0_with_no_stdout(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When settings.json has chmod 000 permissions, CLI exits 0 with empty stdout."""
        settings_file = stress_env["claude"] / "settings.json"
        cache_file = stress_env["sessions"] / "active_servers.json"
        if cache_file.exists():
            cache_file.unlink()

        settings_file.chmod(0o000)
        try:
            stdin_payload = json.dumps(
                {
                    "session_id": "sess_unreadable_settings",
                    "tool_name": "Bash",
                    "tool_input": {"command": "bth sql 'SELECT 1'"},
                }
            )
            monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
            code, stdout = _invoke_cli(["hook", "pre-tool-use"])
            assert code == 0
            assert stdout.strip() == ""
        finally:
            settings_file.chmod(0o644)

    def test_unreadable_session_dir_fails_open_with_no_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_regs: ActiveRegistrations,
    ) -> None:
        """If sessions_dir has unreadable permissions, PreToolUse and PostToolUse fail open gracefully."""
        unreadable_dir = tmp_path / "locked_sessions"
        unreadable_dir.mkdir()
        unreadable_dir.chmod(0o000)

        try:
            payload_pre = {
                "session_id": "sess_locked",
                "tool_name": "Bash",
                "tool_input": {"command": "bth sql 'SELECT 1'"},
            }
            # PreToolUse with locked dir fails open (returns None)
            res_pre = handle_pre_tool_use(
                payload_pre,
                sessions_dir=unreadable_dir,
                registrations=sample_regs,
            )
            assert res_pre is None

            # CLI pre-tool-use exits 0 with no stdout
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload_pre)))
            monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", str(unreadable_dir))
            code, stdout = _invoke_cli(["hook", "pre-tool-use"])
            assert code == 0
            assert stdout.strip() == ""

            # PostToolUse with locked dir fails open (returns False)
            payload_post = {
                "session_id": "sess_locked",
                "tool_name": "mcp__bathos__run_sql",
                "tool_response": {"ok": False, "error": "crash"},
            }
            res_post = handle_post_tool_use(payload_post, sessions_dir=unreadable_dir)
            assert res_post is False

            # CLI post-tool-use exits 0 with no stdout
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload_post)))
            code_post, stdout_post = _invoke_cli(["hook", "post-tool-use"])
            assert code_post == 0
            assert stdout_post == ""
        finally:
            unreadable_dir.chmod(0o755)

    def test_disabled_sessions_dir_fails_open_with_no_stdout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When CISTERNAL_SESSIONS_DIR=off, both hooks exit 0 with empty stdout."""
        monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", "off")

        payload_pre = {
            "session_id": "sess_disabled",
            "tool_name": "Bash",
            "tool_input": {"command": "bth sql 'SELECT 1'"},
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload_pre)))
        code_pre, stdout_pre = _invoke_cli(["hook", "pre-tool-use"])
        assert code_pre == 0
        assert stdout_pre.strip() == ""

        payload_post = {
            "session_id": "sess_disabled",
            "tool_name": "mcp__bathos__run_sql",
            "tool_response": {"ok": False, "error": "crash"},
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload_post)))
        code_post, stdout_post = _invoke_cli(["hook", "post-tool-use"])
        assert code_post == 0
        assert stdout_post.strip() == ""

    def test_cli_stdin_fuzzing_and_exit_code_zero(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI hook commands must ALWAYS exit 0 on invalid/corrupted/empty inputs."""
        fuzz_inputs = [
            "",
            "   \n\t",
            "not a json",
            "[]",
            "12345",
            '"just a string"',
            "null",
            "{}",
            '{"tool_name": "Bash"}',
            '{"tool_name": "Bash", "tool_input": null}',
            '{"tool_name": "Bash", "tool_input": {"command": ""}}',
            '{"tool_name": "NotBash", "tool_input": {"command": "bth sql"}}',
            '{"tool_name": "Bash", "toolCall": {"args": {"command": "ls"}}}',
            "{\x00\x01\x02 binary garbage",
        ]

        for subcmd in ("pre-tool-use", "post-tool-use", "post-tool-failure"):
            for fuzz in fuzz_inputs:
                monkeypatch.setattr(sys, "stdin", io.StringIO(fuzz))
                code, stdout = _invoke_cli(["hook", subcmd])
                assert code == 0, (
                    f"Command 'hook {subcmd}' crashed with exit code {code} on input: {fuzz!r}"
                )
                if subcmd in ("post-tool-use", "post-tool-failure") or fuzz.strip() in (
                    "",
                    "not a json",
                ):
                    assert stdout == ""


class TestAdversarialBenchmarkLatency:
    """Rigorous 100 warm + 100 cold latency verification against the 150 ms ceiling."""

    def test_benchmark_100_warm_iterations_under_150ms(
        self, stress_env: dict[str, Path], sample_regs: ActiveRegistrations
    ) -> None:
        sessions_dir = stress_env["sessions"]
        payload = {
            "session_id": "sess_bench_warm_adv",
            "tool_name": "Bash",
            "tool_input": {"command": "bth run exp1 && bth sql 'SELECT 1'"},
        }

        # Warm up
        res = handle_pre_tool_use(
            payload, sessions_dir=sessions_dir, registrations=sample_regs
        )
        assert res is not None

        warm_times_ms: list[float] = []
        for _ in range(100):
            t0 = time.perf_counter()
            out = handle_pre_tool_use(
                payload, sessions_dir=sessions_dir, registrations=sample_regs
            )
            t1 = time.perf_counter()
            assert out is not None
            warm_times_ms.append((t1 - t0) * 1000.0)

        warm_times_ms.sort()
        p95 = warm_times_ms[95]
        p99 = warm_times_ms[99]
        min_t = warm_times_ms[0]
        mean_t = sum(warm_times_ms) / len(warm_times_ms)
        max_t = warm_times_ms[-1]

        print(
            f"\n[Adversarial Warm Benchmark] N=100 min={min_t:.3f}ms mean={mean_t:.3f}ms p95={p95:.3f}ms p99={p99:.3f}ms max={max_t:.3f}ms"
        )
        assert p95 <= 150.0, f"Warm cache p95 ({p95:.2f} ms) exceeded 150 ms ceiling!"

    def test_benchmark_100_cold_iterations_under_150ms(
        self, stress_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = stress_env["sessions"]
        cache_file = sessions_dir / "active_servers.json"

        orig_scan = scan_active_registrations

        def wrapped_scan(*args: Any, **kwargs: Any) -> ActiveRegistrations:
            kwargs["manifest_path"] = _MANIFEST_PATH
            return orig_scan(*args, **kwargs)

        monkeypatch.setattr(
            "cisternal.usage.hooks.scan_active_registrations", wrapped_scan
        )

        payload = {
            "session_id": "sess_bench_cold_adv",
            "tool_name": "Bash",
            "tool_input": {"command": "bth run exp1 && bth sql 'SELECT 1'"},
        }

        cold_times_ms: list[float] = []
        for _ in range(100):
            if cache_file.exists():
                cache_file.unlink()

            t0 = time.perf_counter()
            out = handle_pre_tool_use(payload, sessions_dir=sessions_dir)
            t1 = time.perf_counter()
            assert out is not None
            cold_times_ms.append((t1 - t0) * 1000.0)

        cold_times_ms.sort()
        p95 = cold_times_ms[95]
        p99 = cold_times_ms[99]
        min_t = cold_times_ms[0]
        mean_t = sum(cold_times_ms) / len(cold_times_ms)
        max_t = cold_times_ms[-1]

        print(
            f"\n[Adversarial Cold Benchmark] N=100 min={min_t:.3f}ms mean={mean_t:.3f}ms p95={p95:.3f}ms p99={p99:.3f}ms max={max_t:.3f}ms"
        )
        assert p95 <= 150.0, (
            f"Cold cache rebuild p95 ({p95:.2f} ms) exceeded 150 ms ceiling!"
        )
