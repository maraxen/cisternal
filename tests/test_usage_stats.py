"""Tests for C0 usage statistics, Wilson intervals, and paired controls."""

from __future__ import annotations

from pathlib import Path

from cisternal.usage.usage import (
    check_paired_controls,
    compute_usage_summary,
    wilson_confidence_interval,
)


class TestWilsonConfidenceInterval:
    """Test Wilson 95% score interval mathematical contracts."""

    def test_spec_e4_empirical_verification(self) -> None:
        """Verify exact intervals from spec line 24."""
        # 13/57 = 22.8% [13.8%, 35.2%]
        ci_err = wilson_confidence_interval(13, 57)
        assert round(ci_err.lower, 3) == 0.138
        assert round(ci_err.upper, 3) == 0.352

        # 15/664 = 2.3% [1.4%, 3.7%]
        ci_succ = wilson_confidence_interval(15, 664)
        assert round(ci_succ.lower, 3) == 0.014
        assert round(ci_succ.upper, 3) == 0.037

    def test_wilson_edge_case_n_zero(self) -> None:
        """n=0 returns [0.0, 0.0]."""
        ci = wilson_confidence_interval(0, 0)
        assert ci.lower == 0.0
        assert ci.upper == 0.0

    def test_wilson_edge_case_x_zero(self) -> None:
        """x=0 clamps lower bound to 0.0."""
        ci = wilson_confidence_interval(0, 20)
        assert ci.lower == 0.0
        assert 0.0 < ci.upper < 1.0

    def test_wilson_edge_case_x_equals_n(self) -> None:
        """x=n clamps upper bound to 1.0."""
        ci = wilson_confidence_interval(20, 20)
        assert 0.0 < ci.lower < 1.0
        assert ci.upper == 1.0


class TestPairedSyntheticControls:
    """Test paired positive and negative controls on synthetic fixture."""

    def test_paired_controls_fixture(self) -> None:
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "transcripts"
            / "synthetic_paired_controls.jsonl"
        )
        assert fixture_path.is_file()

        summary = compute_usage_summary(session_files=[fixture_path])

        # Paired positive: planted bathos/run_sql == 5 (3 from plugin prefix, 2 from short mcp__)
        assert "bathos/run_sql" in summary.tools
        assert summary.tools["bathos/run_sql"].total_calls == 5

        # Bare tool run_sql was rejected and not counted under bathos/run_sql
        # Paired negative: uncalled tool == 0
        assert (
            "bathos/planted_uncalled" not in summary.tools
            or summary.tools["bathos/planted_uncalled"].total_calls == 0
        )

        # Distinct parsed tool keys >= 2 (bathos/run_sql and praxia/status)
        assert len(summary.tools) >= 2
        assert "praxia/status" in summary.tools
        assert summary.tools["praxia/status"].total_calls == 1

        assert check_paired_controls(summary) is True


class TestGoldenRedactedFixture:
    """Test parsing over realistic golden_redacted.jsonl transcript."""

    def test_golden_redacted_transcript(self) -> None:
        fixture_path = (
            Path(__file__).parent / "fixtures" / "transcripts" / "golden_redacted.jsonl"
        )
        assert fixture_path.is_file()

        summary = compute_usage_summary(session_files=[fixture_path])

        assert summary.total_sessions == 1
        assert summary.main_sessions_count == 1
        assert summary.subagent_sessions_count == 0

        # bathos/run_sql tool call
        assert "bathos/run_sql" in summary.tools
        t_stat = summary.tools["bathos/run_sql"]
        assert t_stat.total_calls == 1
        assert t_stat.total_errors == 1

        # bth sql CLI call
        assert "bth sql" in summary.cli_verbs
        assert summary.cli_verbs["bth sql"].total == 1

        # run-cisternal skill invocation
        assert "run-cisternal" in summary.skills
        assert summary.skills["run-cisternal"].total >= 1

        # ToolSearch select: provenance
        assert summary.toolsearch.select_exact.total == 1
        # E4 fallback: error on bathos/run_sql followed at step +1 by bth sql
        e4_err = summary.e4_transitions["error_to_cli"]
        assert e4_err.trials == 1
        assert e4_err.successes == 1
        assert e4_err.rate == 1.0


class TestSessionStratification:
    """Test that main_interactive and subagent_headless metrics are cleanly partitioned."""

    def test_stratification_separation(self, tmp_path: Path) -> None:
        p_root = tmp_path / "projects"
        main_file = p_root / "repo-a" / "main_session.jsonl"
        sub_file = p_root / "repo-a" / "main_session" / "subagents" / "agent-1.jsonl"
        main_file.parent.mkdir(parents=True)
        sub_file.parent.mkdir(parents=True)

        main_file.write_text(
            """{"type": "init", "session_id": "m1", "cwd": "/repo", "isSidechain": false}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "c1", "name": "mcp__bathos__run_sql", "input": {}}]}}
""",
            encoding="utf-8",
        )

        sub_file.write_text(
            """{"type": "init", "session_id": "s1", "cwd": "/repo"}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "c2", "name": "mcp__bathos__run_sql", "input": {}}]}}
""",
            encoding="utf-8",
        )

        summary = compute_usage_summary(projects_root=p_root)
        assert summary.total_sessions == 2
        assert summary.main_sessions_count == 1
        assert summary.subagent_sessions_count == 1

        t_stat = summary.tools["bathos/run_sql"]
        assert t_stat.main_interactive.total_calls == 1
        assert t_stat.subagent_headless.total_calls == 1
        assert t_stat.total_calls == 2


class TestDurationEnrichment:
    """Test optional server JSONL log join within ±5s window."""

    def test_duration_join_within_window(self, tmp_path: Path) -> None:
        sess_file = tmp_path / "sess.jsonl"
        sess_file.write_text(
            """{"type": "init", "session_id": "s1", "cwd": "/repo"}
{"type": "assistant", "timestamp": "2026-11-01T12:00:00Z", "message": {"content": [{"type": "tool_use", "id": "c1", "name": "mcp__bathos__run_sql", "input": {}}]}}
""",
            encoding="utf-8",
        )

        log_dir = tmp_path / "server_logs"
        log_dir.mkdir()
        server_log = log_dir / "mcp.jsonl"
        # Recorded 2 seconds after tool call
        server_log.write_text(
            """{"name": "mcp.call_end", "tool": "bathos/run_sql", "duration_ms": 142.5, "timestamp": "2026-11-01T12:00:02Z"}
""",
            encoding="utf-8",
        )

        summary = compute_usage_summary(session_files=[sess_file], log_dir=log_dir)
        t_stat = summary.tools["bathos/run_sql"]
        assert t_stat.total_calls == 1
        assert len(t_stat.main_interactive.durations_ms) == 1
        assert t_stat.main_interactive.durations_ms[0] == 142.5
        assert t_stat.main_interactive.p50 == 142.5
