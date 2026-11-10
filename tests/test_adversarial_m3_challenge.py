"""Adversarial stress-testing suite for Milestone M3 (Track C Part 1: C0, C1).

Executed by challenger_m3_1 to adversarially test:
1. Mathematical invariants of Wilson score intervals (boundaries, extreme N, monotonicity, Spec E4).
2. C0 event aggregator & paired controls (planted counts across wire forms, uncalled tool, sliding window E4 fallback detection, duration join).
3. C1 host safety & registrations scanning (read-only config, no claude subprocess, atomic cache write).
4. C1 prune floor, worktree repo folding, whitelisting (hooks/commands), and R4 skill accounting.
5. Cyclopts CLI commands (usage, prune-list, argument validation, flags).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import random
import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from cisternal.cli import app
from cisternal.usage.prune import (
    compute_prune_recommendations,
)
from cisternal.usage.registrations import (
    ActiveRegistrations,
    PluginAssetInfo,
    _atomic_write_cache,
    scan_active_registrations,
)
from cisternal.usage.usage import (
    StratifiedCount,
    StratifiedToolUsage,
    ToolCallStats,
    ToolSearchUsage,
    UsageSummary,
    check_paired_controls,
    compute_usage_summary,
    wilson_confidence_interval,
)


# ==============================================================================
# Suite 1: Mathematical Invariants (wilson_confidence_interval)
# ==============================================================================


class TestAdversarialWilsonInvariants:
    """Stress-test mathematical invariants, boundaries, and extreme scales."""

    def test_trials_zero_or_negative(self) -> None:
        """Trials <= 0 must always yield [0.0, 0.0] without division by zero."""
        for trials in [0, -1, -100, -1_000_000]:
            for successes in [0, 1, -5, 100]:
                ci = wilson_confidence_interval(successes, trials)
                assert ci.lower == 0.0, f"Failed for {successes}/{trials}"
                assert ci.upper == 0.0, f"Failed for {successes}/{trials}"
                assert ci.format_pct(1) == "[0.0%, 0.0%]"

    def test_zero_successes_positive_trials(self) -> None:
        """x = 0, n > 0: lower bound is in [0.0, 1e-15], upper bound matches Wilson formula."""
        z = 1.95996
        for n in [1, 2, 3, 5, 7, 10, 20, 50, 100, 1000, 100_000]:
            ci = wilson_confidence_interval(0, n, z=z)
            assert 0.0 <= ci.lower <= 1e-15, (
                f"Lower bound {ci.lower} out of [0, 1e-15] for 0/{n}"
            )
            expected_upper = (z * z) / (n + z * z)
            assert math.isclose(ci.upper, expected_upper, rel_tol=1e-6), (
                f"Upper bound mismatch for 0/{n}: got {ci.upper}, expected {expected_upper}"
            )
            assert 0.0 < ci.upper <= 1.0
            assert ci.format_pct(1).startswith("[0.0%,")

    def test_all_successes_positive_trials(self) -> None:
        """x = n, n > 0: upper bound is in [1.0 - 1e-15, 1.0], lower bound matches Wilson formula."""
        z = 1.95996
        for n in [1, 2, 3, 5, 7, 10, 20, 50, 100, 1000, 100_000]:
            ci = wilson_confidence_interval(n, n, z=z)
            assert 1.0 - 1e-15 <= ci.upper <= 1.0, (
                f"Upper bound {ci.upper} out of bounds for {n}/{n}"
            )
            expected_lower = n / (n + z * z)
            assert math.isclose(ci.lower, expected_lower, rel_tol=1e-6), (
                f"Lower bound mismatch for {n}/{n}: got {ci.lower}, expected {expected_lower}"
            )
            assert 0.0 <= ci.lower < 1.0
            assert ci.format_pct(1).endswith("100.0%]")

    def test_extreme_scale_numerical_stability(self) -> None:
        """Test astronomical trial counts (n = 1,000,000 and 10,000,000) for overflow / underflow."""
        for n in [1_000_000, 10_000_000]:
            # Midpoint
            ci_half = wilson_confidence_interval(n // 2, n)
            assert 0.0 <= ci_half.lower <= 0.5 <= ci_half.upper <= 1.0
            assert math.isclose(ci_half.lower, 0.5, abs_tol=0.002)
            assert math.isclose(ci_half.upper, 0.5, abs_tol=0.002)

            # Rare event: 1 in a million
            ci_rare = wilson_confidence_interval(1, n)
            assert 0.0 <= ci_rare.lower <= ci_rare.upper <= 1.0
            assert ci_rare.upper > 0.0

            # Almost certain: n - 1
            ci_high = wilson_confidence_interval(n - 1, n)
            assert 0.0 <= ci_high.lower <= ci_high.upper <= 1.0
            assert ci_high.lower < 1.0

    def test_spec_e4_exact_numbers(self) -> None:
        """Spec §E4 line 24 empirical numbers reproduction."""
        # 13/57: error fallback rate ~23% -> [13.8%, 35.2%]
        ci_err = wilson_confidence_interval(13, 57)
        assert round(ci_err.lower, 3) == 0.138
        assert round(ci_err.upper, 3) == 0.352
        assert ci_err.format_pct(1) == "[13.8%, 35.2%]"

        # 15/664: success fallback rate ~2% -> [1.4%, 3.7%]
        ci_succ = wilson_confidence_interval(15, 664)
        assert round(ci_succ.lower, 3) == 0.014
        assert round(ci_succ.upper, 3) == 0.037
        assert ci_succ.format_pct(1) == "[1.4%, 3.7%]"

    def test_randomized_invariants_property_test(self) -> None:
        """Randomized property testing: bounds strictly in [0, 1], lower <= upper, sample mean contained."""
        rng = random.Random(42)
        for _ in range(500):
            n = rng.randint(1, 10_000)
            x = rng.randint(0, n)
            ci = wilson_confidence_interval(x, n)

            # 1. Strict boundaries
            assert 0.0 <= ci.lower <= 1.0, f"Lower bound out of [0, 1]: {ci}"
            assert 0.0 <= ci.upper <= 1.0, f"Upper bound out of [0, 1]: {ci}"
            assert ci.lower <= ci.upper + 1e-15, f"Lower > Upper: {ci}"

            # 2. Sample mean must lie within confidence interval
            p_hat = x / n
            assert ci.lower - 1e-9 <= p_hat <= ci.upper + 1e-9, (
                f"p_hat {p_hat} outside [{ci.lower}, {ci.upper}]"
            )

    def test_monotonicity_fixed_n(self) -> None:
        """For fixed n, increasing x must monotonically increase lower and upper bounds."""
        n = 100
        prev_lower = -1.0
        prev_upper = -1.0
        for x in range(n + 1):
            ci = wilson_confidence_interval(x, n)
            assert ci.lower >= prev_lower - 1e-12, (
                f"Monotonicity violated at lower for x={x}"
            )
            assert ci.upper >= prev_upper - 1e-12, (
                f"Monotonicity violated at upper for x={x}"
            )
            prev_lower = ci.lower
            prev_upper = ci.upper


# ==============================================================================
# Suite 2: C0 Event Aggregator & Controls
# ==============================================================================


class TestAdversarialC0AggregatorAndControls:
    """Stress-test paired controls, sliding window fallback, duration join."""

    def test_paired_controls_perturbations(self) -> None:
        """check_paired_controls must return False if planted count != 5, uncalled != 0, or tools < 2."""

        def make_usage(
            planted: int, uncalled: int, tool_keys: list[str]
        ) -> UsageSummary:
            tools_map: dict[str, StratifiedToolUsage] = {}
            for k in tool_keys:
                c = (
                    planted
                    if k == "bathos/run_sql"
                    else (uncalled if k == "bathos/planted_uncalled" else 1)
                )
                tools_map[k] = StratifiedToolUsage(
                    main_interactive=ToolCallStats(total_calls=c, success_calls=c)
                )
            return UsageSummary(
                total_sessions=1,
                calendar_days=1.0,
                main_sessions_count=1,
                subagent_sessions_count=0,
                tools=tools_map,
                cli_verbs={},
                skills={},
                toolsearch=ToolSearchUsage(),
                e4_transitions={},
                sessions_by_repo={},
            )

        # Baseline: Valid paired controls (planted=5, uncalled=0, tools >= 2)
        valid = make_usage(5, 0, ["bathos/run_sql", "praxia/status"])
        assert check_paired_controls(valid) is True

        # Perturbation 1: planted != 5 (e.g. 4 or 6)
        assert (
            check_paired_controls(make_usage(4, 0, ["bathos/run_sql", "praxia/status"]))
            is False
        )
        assert (
            check_paired_controls(make_usage(6, 0, ["bathos/run_sql", "praxia/status"]))
            is False
        )

        # Perturbation 2: uncalled != 0 (e.g. 1)
        assert (
            check_paired_controls(
                make_usage(
                    5, 1, ["bathos/run_sql", "bathos/planted_uncalled", "praxia/status"]
                )
            )
            is False
        )

        # Perturbation 3: distinct tools < 2 (only bathos/run_sql)
        assert check_paired_controls(make_usage(5, 0, ["bathos/run_sql"])) is False

    def test_e4_sliding_window_fallbacks_adversarial(self, tmp_path: Path) -> None:
        """Test E4 sliding window lookahead: step +1, +2, +3 caught; step +4 ignored; no double count."""

        def write_session(filename: str, actions: list[dict[str, Any]]) -> Path:
            s_file = tmp_path / filename
            lines = [
                json.dumps(
                    {
                        "type": "session_meta",
                        "session_id": "test_s",
                        "timestamp": "2026-11-01T10:00:00Z",
                        "cwd": "/repo",
                    }
                ),
            ]
            for i, act in enumerate(actions):
                call_id = f"call_{i}"
                if act["type"] == "mcp":
                    lines.append(
                        json.dumps(
                            {
                                "type": "message",
                                "timestamp": "2026-11-01T10:01:00Z",
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": call_id,
                                            "name": act["wire_name"],
                                            "input": {},
                                        }
                                    ],
                                },
                            }
                        )
                    )
                    lines.append(
                        json.dumps(
                            {
                                "type": "tool_result",
                                "tool_use_id": call_id,
                                "is_error": act.get("is_error", False),
                                "content": "error failure"
                                if act.get("is_error")
                                else "ok result",
                            }
                        )
                    )
                elif act["type"] == "bash":
                    lines.append(
                        json.dumps(
                            {
                                "type": "message",
                                "timestamp": "2026-11-01T10:01:00Z",
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": call_id,
                                            "name": "Bash",
                                            "input": {"command": act["cmd"]},
                                        }
                                    ],
                                },
                            }
                        )
                    )
                elif act["type"] == "other":
                    lines.append(
                        json.dumps(
                            {
                                "type": "message",
                                "timestamp": "2026-11-01T10:01:00Z",
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": call_id,
                                            "name": "ToolSearch",
                                            "input": {"query": "test"},
                                        }
                                    ],
                                },
                            }
                        )
                    )
            s_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return s_file

        # Scenario A: Fallback at step +1 (immediate)
        s_a = write_session(
            "sa.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": True},
                {"type": "bash", "cmd": "bth sql 'SELECT 1'"},
            ],
        )
        usage_a = compute_usage_summary(session_files=[s_a])
        e4_err_a = usage_a.e4_transitions["error_to_cli"]
        assert e4_err_a.trials == 1 and e4_err_a.successes == 1, (
            f"Step +1 failed: {e4_err_a}"
        )

        # Scenario B: Fallback at step +2 (one intervening other action)
        s_b = write_session(
            "sb.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": True},
                {"type": "other"},
                {"type": "bash", "cmd": "bth sql 'SELECT 1'"},
            ],
        )
        usage_b = compute_usage_summary(session_files=[s_b])
        e4_err_b = usage_b.e4_transitions["error_to_cli"]
        assert e4_err_b.trials == 1 and e4_err_b.successes == 1, (
            f"Step +2 failed: {e4_err_b}"
        )

        # Scenario C: Fallback at step +3 (two intervening actions)
        s_c = write_session(
            "sc.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": True},
                {"type": "other"},
                {"type": "other"},
                {"type": "bash", "cmd": "bth sql 'SELECT 1'"},
            ],
        )
        usage_c = compute_usage_summary(session_files=[s_c])
        e4_err_c = usage_c.e4_transitions["error_to_cli"]
        assert e4_err_c.trials == 1 and e4_err_c.successes == 1, (
            f"Step +3 failed: {e4_err_c}"
        )

        # Scenario D: Step +4 (three intervening actions) -> OUTSIDE WINDOW
        s_d = write_session(
            "sd.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": True},
                {"type": "other"},
                {"type": "other"},
                {"type": "other"},
                {"type": "bash", "cmd": "bth sql 'SELECT 1'"},
            ],
        )
        usage_d = compute_usage_summary(session_files=[s_d])
        e4_err_d = usage_d.e4_transitions["error_to_cli"]
        assert e4_err_d.trials == 1 and e4_err_d.successes == 0, (
            f"Step +4 was incorrectly caught: {e4_err_d}"
        )

        # Scenario E: Multiple fallbacks within window -> NO DOUBLE COUNTING
        s_e = write_session(
            "se.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": True},
                {"type": "bash", "cmd": "bth sql 'SELECT 1'"},
                {"type": "bash", "cmd": "bth sql 'SELECT 2'"},
            ],
        )
        usage_e = compute_usage_summary(session_files=[s_e])
        e4_err_e = usage_e.e4_transitions["error_to_cli"]
        assert e4_err_e.trials == 1 and e4_err_e.successes == 1, (
            f"Double-counted fallback: {e4_err_e}"
        )

        # Scenario F: Excluded verb -> NOT a fallback
        s_f = write_session(
            "sf.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": True},
                {"type": "bash", "cmd": "bth run exp1"},
            ],
        )
        usage_f = compute_usage_summary(session_files=[s_f])
        e4_err_f = usage_f.e4_transitions["error_to_cli"]
        assert e4_err_f.trials == 1 and e4_err_f.successes == 0, (
            f"Excluded verb 'run' treated as fallback: {e4_err_f}"
        )

        # Scenario G: Success fallback
        s_g = write_session(
            "sg.jsonl",
            [
                {"type": "mcp", "wire_name": "mcp__bathos__run_sql", "is_error": False},
                {"type": "bash", "cmd": "bth sql 'SELECT 1'"},
            ],
        )
        usage_g = compute_usage_summary(session_files=[s_g])
        e4_succ_g = usage_g.e4_transitions["success_to_cli"]
        assert e4_succ_g.trials == 1 and e4_succ_g.successes == 1
        assert usage_g.e4_transitions["error_to_cli"].trials == 0

    def test_server_duration_join_boundary(self, tmp_path: Path) -> None:
        """Test timestamp correlation window [ -5.0s, +5.0s ] and resilience to log errors."""
        log_dir = tmp_path / "server_logs"
        log_dir.mkdir()

        # Client timestamps:
        # t1: 2026-11-01T10:00:00Z -> epoch 1793527200.0
        # t2: 2026-11-01T10:01:00Z -> epoch 1793527260.0
        # t3: 2026-11-01T10:02:00Z -> epoch 1793527320.0
        # t4: 2026-11-01T10:03:00Z -> epoch 1793527380.0
        srv_file = log_dir / "server.jsonl"
        srv_file.write_text(
            "\n".join(
                [
                    # 1. Match at +4.9s
                    json.dumps(
                        {
                            "tool": "mcp__bathos__run_sql",
                            "timestamp": 1793527204.9,
                            "duration_ms": 120.0,
                        }
                    ),
                    # 2. Outside at +5.1s
                    json.dumps(
                        {
                            "tool": "mcp__bathos__run_sql",
                            "timestamp": 1793527265.1,
                            "duration_ms": 999.0,
                        }
                    ),
                    # 3. Match at -4.9s
                    json.dumps(
                        {
                            "tool": "praxia/status",
                            "timestamp": 1793527315.1,
                            "duration_ms": 45.0,
                        }
                    ),
                    # 4. Outside at -5.1s
                    json.dumps(
                        {
                            "tool": "praxia/status",
                            "timestamp": 1793527374.9,
                            "duration_ms": 888.0,
                        }
                    ),
                    # Corrupted / edge-case lines in server log
                    "not json at all",
                    json.dumps({"other_key": 123}),
                    json.dumps(
                        {
                            "tool": "praxia/status",
                            "timestamp": "invalid_ts",
                            "duration_ms": 50.0,
                        }
                    ),
                    json.dumps(
                        {
                            "tool": "praxia/status",
                            "timestamp": 1793527380.0,
                            "duration_ms": "not_a_float",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        client_file = tmp_path / "client.jsonl"
        client_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "session_meta",
                            "session_id": "c1",
                            "timestamp": "2026-11-01T10:00:00Z",
                            "cwd": "/repo",
                        }
                    ),
                    # 1. Match at +4.9s
                    json.dumps(
                        {
                            "type": "message",
                            "timestamp": "2026-11-01T10:00:00Z",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "t1",
                                        "name": "mcp__bathos__run_sql",
                                        "input": {},
                                    }
                                ]
                            },
                        }
                    ),
                    # 2. Outside at +5.1s
                    json.dumps(
                        {
                            "type": "message",
                            "timestamp": "2026-11-01T10:01:00Z",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "t2",
                                        "name": "mcp__bathos__run_sql",
                                        "input": {},
                                    }
                                ]
                            },
                        }
                    ),
                    # 3. Match at -4.9s
                    json.dumps(
                        {
                            "type": "message",
                            "timestamp": "2026-11-01T10:02:00Z",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "t3",
                                        "name": "mcp__praxia__status",
                                        "input": {},
                                    }
                                ]
                            },
                        }
                    ),
                    # 4. Outside at -5.1s
                    json.dumps(
                        {
                            "type": "message",
                            "timestamp": "2026-11-01T10:03:00Z",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "t4",
                                        "name": "mcp__praxia__status",
                                        "input": {},
                                    }
                                ]
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        usage = compute_usage_summary(session_files=[client_file], log_dir=log_dir)

        # bathos/run_sql should have exactly 1 duration: 120.0
        bathos_durations = usage.tools["bathos/run_sql"].main_interactive.durations_ms
        assert bathos_durations == (120.0,), (
            f"Expected (120.0,), got {bathos_durations}"
        )

        # praxia/status should have exactly 1 duration: 45.0
        praxia_durations = usage.tools["praxia/status"].main_interactive.durations_ms
        assert praxia_durations == (45.0,), f"Expected (45.0,), got {praxia_durations}"

        # Missing log dir does not crash
        usage_no_log = compute_usage_summary(
            session_files=[client_file], log_dir=tmp_path / "nonexistent"
        )
        assert usage_no_log.tools["bathos/run_sql"].main_interactive.durations_ms == ()


# ==============================================================================
# Suite 3: C1 Host Safety & Registration Scanning
# ==============================================================================


class TestAdversarialC1HostSafetyAndRegistrations:
    """Stress-test host safety (no config mutation, no claude process) and atomic cache."""

    def test_host_safety_no_config_mutation(self, tmp_path: Path) -> None:
        """scan_active_registrations must NEVER create or mutate ~/.config/cisternal/config.toml."""
        fake_home = tmp_path / "home"
        fake_config_dir = fake_home / ".config" / "cisternal"
        fake_config_file = fake_config_dir / "config.toml"

        with patch.dict(os.environ, {"HOME": str(fake_home)}):
            assert not fake_config_file.exists()

            scan_active_registrations(
                sessions_dir=tmp_path / "sessions",
                claude_dir=tmp_path / "claude",
                force=True,
            )

            assert not fake_config_file.exists(), (
                "Host safety violation: config.toml was created!"
            )

    def test_host_safety_never_spawns_claude(self, tmp_path: Path) -> None:
        """scan_active_registrations must NEVER invoke subprocess with 'claude' CLI."""
        real_run = subprocess.run
        real_popen = subprocess.Popen

        def guard_run(cmd, *args, **kwargs):
            cmd_str = str(cmd)
            if "claude" in cmd_str and "git" not in cmd_str:
                raise AssertionError(
                    f"Host safety violation: attempted to spawn claude: {cmd}"
                )
            return real_run(cmd, *args, **kwargs)

        def guard_popen(cmd, *args, **kwargs):
            cmd_str = str(cmd)
            if "claude" in cmd_str and "git" not in cmd_str:
                raise AssertionError(
                    f"Host safety violation: attempted to spawn claude via Popen: {cmd}"
                )
            return real_popen(cmd, *args, **kwargs)

        with (
            patch("subprocess.run", side_effect=guard_run),
            patch("subprocess.Popen", side_effect=guard_popen),
        ):
            scan_active_registrations(
                sessions_dir=tmp_path / "sessions",
                claude_dir=tmp_path / "claude",
                force=True,
            )

    def test_atomic_write_cache_and_cleanup(self, tmp_path: Path) -> None:
        """Atomic write to active_servers.json: valid JSON, directory auto-creation, no lingering temp files."""
        cache_file = tmp_path / "nested" / "deep" / "sessions" / "active_servers.json"
        data = {
            "version": "1.0",
            "servers": ["server_a", "server_b"],
            "tools": {"server_a/tool1": "mcp__server_a__tool1"},
            "verbs": {},
            "families": {"fam1": ["server_a/tool1"]},
            "plugins": {},
        }

        _atomic_write_cache(cache_file, data)

        assert cache_file.is_file()
        read_back = json.loads(cache_file.read_text(encoding="utf-8"))
        assert read_back == data

        temp_files = list(cache_file.parent.glob("*.tmp.*"))
        assert len(temp_files) == 0, f"Lingering temporary files found: {temp_files}"


# ==============================================================================
# Suite 4: C1 Prune Floor & Whitelisting
# ==============================================================================


class TestAdversarialC1PruneFloorAndWhitelisting:
    """Stress-test lookback floor boundary, repo worktree folding, whitelisting, and skill accounting."""

    def _make_dummy_usage(
        self,
        sessions: int,
        days: float,
        tools: dict[str, int] | None = None,
        skills: dict[str, int] | None = None,
        repo_sessions: dict[str, int] | None = None,
        server_repo_sessions: dict[str, dict[str, int]] | None = None,
    ) -> UsageSummary:
        tools_dict = {
            k: StratifiedToolUsage(
                main_interactive=ToolCallStats(total_calls=v, success_calls=v)
            )
            for k, v in (tools or {}).items()
        }
        skills_dict = {
            k: StratifiedCount(main_interactive=v) for k, v in (skills or {}).items()
        }
        return UsageSummary(
            total_sessions=sessions,
            calendar_days=days,
            main_sessions_count=sessions,
            subagent_sessions_count=0,
            tools=tools_dict,
            cli_verbs={},
            skills=skills_dict,
            toolsearch=ToolSearchUsage(),
            e4_transitions={},
            sessions_by_repo=repo_sessions or {},
            server_sessions_by_repo=server_repo_sessions or {},
        )

    def test_lookback_floor_boundary_conditions(self) -> None:
        """Floor check: N >= 20 AND days >= 14.0. Both must be satisfied."""
        regs = ActiveRegistrations(servers=("server_a", "server_b"))

        # Case 1: N=19, days=14.0 -> SUPPRESSED
        rep1 = compute_prune_recommendations(self._make_dummy_usage(19, 14.0), regs)
        assert not rep1.floor_cleared
        assert rep1.suppression_reason is not None
        assert rep1.drop == ()
        assert rep1.enable_per_project == ()
        assert set(rep1.keep) == {"server_a", "server_b"}

        # Case 2: N=20, days=13.9 -> SUPPRESSED
        rep2 = compute_prune_recommendations(self._make_dummy_usage(20, 13.9), regs)
        assert not rep2.floor_cleared
        assert rep2.suppression_reason is not None
        assert rep2.drop == ()
        assert rep2.enable_per_project == ()

        # Case 3: N=20, days=14.0 -> PERMITTED
        rep3 = compute_prune_recommendations(self._make_dummy_usage(20, 14.0), regs)
        assert rep3.floor_cleared
        assert rep3.suppression_reason is None
        assert len(rep3.drop) == 2

    def test_whitelisting_hooks_and_commands(self) -> None:
        """Active plugins declaring hooks or commands are NEVER placed in drop, even with 0 MCP calls."""
        regs = ActiveRegistrations(
            servers=("hook_srv", "cmd_srv", "plain_srv"),
            plugins={
                "hook_plugin": PluginAssetInfo(
                    servers=("hook_srv",), hooks=("my_hook",)
                ),
                "cmd_plugin": PluginAssetInfo(
                    servers=("cmd_srv",), commands=("my_cmd",)
                ),
                "plain_plugin": PluginAssetInfo(servers=("plain_srv",)),
            },
        )
        usage = self._make_dummy_usage(sessions=25, days=15.0, tools={})
        report = compute_prune_recommendations(usage, regs)

        assert report.floor_cleared
        assert "hook_srv" in report.keep
        assert "cmd_srv" in report.keep
        drop_servers = [d.server for d in report.drop]
        assert "plain_srv" in drop_servers
        assert "hook_srv" not in drop_servers
        assert "cmd_srv" not in drop_servers

    def test_r4_skill_accounting(self) -> None:
        """Plugin with 0 calls: kept if any skill invoked, dropped if all skills had 0 invocations."""
        regs = ActiveRegistrations(
            servers=("active_skill_srv", "idle_skill_srv"),
            plugins={
                "active_p": PluginAssetInfo(
                    servers=("active_skill_srv",), skills=("used_skill",)
                ),
                "idle_p": PluginAssetInfo(
                    servers=("idle_skill_srv",), skills=("unused_skill",)
                ),
            },
        )
        usage = self._make_dummy_usage(
            sessions=25,
            days=15.0,
            tools={},
            skills={"used_skill": 1, "unused_skill": 0},
        )
        report = compute_prune_recommendations(usage, regs)

        assert "active_skill_srv" in report.keep
        drop_map = {d.server: d for d in report.drop}
        assert "idle_skill_srv" in drop_map
        assert "0 invocations" in drop_map["idle_skill_srv"].reason

    def test_rule_of_three_bound(self) -> None:
        """Dropped recommendations must accurately report Rule of Three 3.0 / N upper bound."""
        regs = ActiveRegistrations(servers=("dead_srv",))
        for n in [20, 50, 100]:
            usage = self._make_dummy_usage(sessions=n, days=20.0, tools={})
            report = compute_prune_recommendations(usage, regs)
            assert len(report.drop) == 1
            expected_bound = min(1.0, 3.0 / n)
            assert math.isclose(
                report.drop[0].rule_of_three_bound, expected_bound, rel_tol=1e-6
            )

    def test_worktree_repo_folding_in_usage(self, tmp_path: Path) -> None:
        """Sessions inside .claude/worktrees/ fold into parent repo on disk."""
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        wt_dir = repo_dir / ".claude" / "worktrees" / "feat1"
        wt_dir.mkdir(parents=True)

        files: list[Path] = []
        for i in range(20):
            sf = tmp_path / f"sess_{i}.jsonl"
            cwd = str(repo_dir) if i < 15 else str(wt_dir)
            sf.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "session_id": f"s_{i}",
                                "timestamp": f"2026-11-0{i % 9 + 1}T10:00:00Z",
                                "cwd": cwd,
                            }
                        ),
                        json.dumps(
                            {
                                "type": "message",
                                "timestamp": "2026-11-01T10:01:00Z",
                                "message": {
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": "t1",
                                            "name": "mcp__repo_srv__tool",
                                            "input": {},
                                        }
                                    ]
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            files.append(sf)

        usage = compute_usage_summary(session_files=files)

        resolved_repo_str = str(repo_dir.resolve())
        assert resolved_repo_str in usage.sessions_by_repo
        assert usage.sessions_by_repo[resolved_repo_str] == 20
        assert str(wt_dir) not in usage.sessions_by_repo

        srv_repo_map = usage.server_sessions_by_repo.get("repo_srv", {})
        assert srv_repo_map.get(resolved_repo_str) == 20


# ==============================================================================
# Suite 5: CLI Integration (cisternal usage & cisternal prune-list)
# ==============================================================================


class TestAdversarialCLIIntegration:
    """Stress-test CLI invocations across flags, json schemas, error codes."""

    def test_cli_usage_flag_permutations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test cisternal usage with --show-paths, --summary, --json."""
        # 1. --show-paths
        with pytest.raises(SystemExit) as exc1:
            app(
                [
                    "usage",
                    "--show-paths",
                    "--sessions-dir",
                    str(tmp_path),
                    "--no-summary",
                ]
            )
        assert exc1.value.code == 0
        cap1 = capsys.readouterr()
        assert "Sessions directory:" in cap1.out
        assert str(tmp_path) in cap1.out

        # 2. --json
        with pytest.raises(SystemExit) as exc2:
            app(
                [
                    "usage",
                    "--json",
                    "--projects-dir",
                    str(tmp_path),
                    "--sessions-dir",
                    str(tmp_path),
                ]
            )
        assert exc2.value.code == 0
        cap2 = capsys.readouterr()
        doc = json.loads(cap2.out)
        assert doc.get("version") == "1.0"
        assert "metadata" in doc
        assert "sessions_total" in doc["metadata"]
        assert "stratified" in doc
        assert "combined" in doc["stratified"]
        assert "e4_transitions" in doc["stratified"]["combined"]

        # 3. Invalid option -> exit 2
        with pytest.raises(SystemExit) as exc3:
            app(["usage", "--bogus-option"])
        assert exc3.value.code == 2

    def test_cli_prune_list_flag_permutations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test cisternal prune-list with --json, --days, --min-sessions, --repo."""
        # 1. Default run with empty dir -> floor not met
        with pytest.raises(SystemExit) as exc1:
            app(
                [
                    "prune-list",
                    "--json",
                    "--projects-dir",
                    str(tmp_path),
                    "--sessions-dir",
                    str(tmp_path),
                ]
            )
        assert exc1.value.code == 0
        cap1 = capsys.readouterr()
        doc1 = json.loads(cap1.out)
        assert doc1["floor_cleared"] is False
        assert "Recommendations suppressed" in doc1["suppression_reason"]

        # 2. Lower floor (--days 1 --min-sessions 1)
        with pytest.raises(SystemExit) as exc2:
            app(
                [
                    "prune-list",
                    "--json",
                    "--days",
                    "1",
                    "--min-sessions",
                    "1",
                    "--projects-dir",
                    str(tmp_path),
                    "--sessions-dir",
                    str(tmp_path),
                ]
            )
        assert exc2.value.code == 0
        cap2 = capsys.readouterr()
        doc2 = json.loads(cap2.out)
        assert "floor_cleared" in doc2

        # 3. Invalid --days 0 -> exit 2
        with pytest.raises(SystemExit) as exc3:
            app(["prune-list", "--days", "0"])
        assert exc3.value.code == 2

        # 4. Invalid --min-sessions 0 -> exit 2
        with pytest.raises(SystemExit) as exc4:
            app(["prune-list", "--min-sessions", "0"])
        assert exc4.value.code == 2
