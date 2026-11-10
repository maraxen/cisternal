"""Tests for prune list recommendation engine (Spec §C1)."""

from __future__ import annotations

from cisternal.usage.prune import (
    compute_prune_recommendations,
)
from cisternal.usage.registrations import ActiveRegistrations, PluginAssetInfo
from cisternal.usage.usage import (
    StratifiedCount,
    StratifiedToolUsage,
    ToolCallStats,
    ToolSearchUsage,
    UsageSummary,
)


def _make_usage(
    total_sessions: int = 25,
    calendar_days: float = 15.0,
    tools: dict[str, StratifiedToolUsage] | None = None,
    skills: dict[str, StratifiedCount] | None = None,
    sessions_by_repo: dict[str, int] | None = None,
    server_sessions_by_repo: dict[str, dict[str, int]] | None = None,
) -> UsageSummary:
    return UsageSummary(
        total_sessions=total_sessions,
        calendar_days=calendar_days,
        main_sessions_count=total_sessions,
        subagent_sessions_count=0,
        tools=tools or {},
        cli_verbs={},
        skills=skills or {},
        toolsearch=ToolSearchUsage(),
        e4_transitions={},
        sessions_by_repo=sessions_by_repo or {"repo-main": total_sessions},
        server_sessions_by_repo=server_sessions_by_repo or {},
    )


class TestPruneLookbackFloor:
    """Test dual-condition floor (N >= 20 AND >= 14 calendar days)."""

    def test_insufficient_sessions_suppressed(self) -> None:
        """N=15 sessions over 20 days fails floor."""
        usage = _make_usage(total_sessions=15, calendar_days=20.0)
        reg = ActiveRegistrations(servers=("bathos", "praxia"))
        report = compute_prune_recommendations(usage, reg)
        assert report.floor_cleared is False
        assert report.suppression_reason is not None
        assert "floor is N>=20 AND >=14 days" in report.suppression_reason
        assert report.drop == ()
        assert report.enable_per_project == ()
        assert set(report.keep) == {"bathos", "praxia"}

    def test_insufficient_days_suppressed(self) -> None:
        """N=30 sessions over 10 days fails floor."""
        usage = _make_usage(total_sessions=30, calendar_days=10.0)
        reg = ActiveRegistrations(servers=("bathos", "praxia"))
        report = compute_prune_recommendations(usage, reg)
        assert report.floor_cleared is False
        assert report.drop == ()

    def test_floor_cleared(self) -> None:
        """N=20 sessions over 14 days passes floor."""
        usage = _make_usage(total_sessions=20, calendar_days=14.0)
        reg = ActiveRegistrations(servers=())
        report = compute_prune_recommendations(usage, reg)
        assert report.floor_cleared is True
        assert report.suppression_reason is None


class TestPruneBucketing:
    """Test keep, drop, whitelisting, and concentration logic."""

    def test_unregistered_historical_servers_ignored(self) -> None:
        """Servers in usage telemetry but not in active registrations are never reported."""
        tool_stat = StratifiedToolUsage(main_interactive=ToolCallStats(total_calls=50))
        usage = _make_usage(
            total_sessions=25,
            calendar_days=15.0,
            tools={"old_unregistered/query": tool_stat},
        )
        reg = ActiveRegistrations(servers=("registered_server",))
        report = compute_prune_recommendations(usage, reg)
        # old_unregistered is omitted from all buckets
        assert "old_unregistered" not in report.keep
        assert not any(d.server == "old_unregistered" for d in report.drop)
        assert "registered_server" in [d.server for d in report.drop]

    def test_active_server_with_calls_kept(self) -> None:
        """Active server with >= 1 call is kept."""
        tool_stat = StratifiedToolUsage(main_interactive=ToolCallStats(total_calls=5))
        usage = _make_usage(
            total_sessions=25,
            calendar_days=15.0,
            tools={"bathos/run_sql": tool_stat},
        )
        reg = ActiveRegistrations(servers=("bathos",))
        report = compute_prune_recommendations(usage, reg)
        assert "bathos" in report.keep
        assert report.drop == ()

    def test_standalone_zero_call_server_dropped_with_rule_of_three(self) -> None:
        """Server with 0 calls is dropped with Rule of Three bound 3/N."""
        usage = _make_usage(total_sessions=30, calendar_days=20.0)
        reg = ActiveRegistrations(servers=("unused_server",))
        report = compute_prune_recommendations(usage, reg)
        assert len(report.drop) == 1
        drop_rec = report.drop[0]
        assert drop_rec.server == "unused_server"
        assert round(drop_rec.rule_of_three_bound, 2) == 0.10  # 3 / 30 = 0.10

    def test_plugin_with_hooks_or_commands_whitelisted(self) -> None:
        """Plugin with 0 MCP calls but active hooks or commands is whitelisted in keep."""
        usage = _make_usage(total_sessions=25, calendar_days=15.0)
        plugin_hook = PluginAssetInfo(
            servers=("server_with_hook",), hooks=("PreToolUse",)
        )
        plugin_cmd = PluginAssetInfo(servers=("server_with_cmd",), commands=("mycmd",))
        reg = ActiveRegistrations(
            servers=("server_with_hook", "server_with_cmd"),
            plugins={"p_hook": plugin_hook, "p_cmd": plugin_cmd},
        )
        report = compute_prune_recommendations(usage, reg)
        assert "server_with_hook" in report.keep
        assert "server_with_cmd" in report.keep
        assert report.drop == ()

    def test_plugin_skill_accounting_drop_vs_keep(self) -> None:
        """Plugin with 0 MCP calls is dropped if all skills 0 calls, kept if any skill called."""
        usage = _make_usage(
            total_sessions=25,
            calendar_days=15.0,
            skills={
                "active_skill": StratifiedCount(main_interactive=3),
                "dead_skill": StratifiedCount(main_interactive=0),
            },
        )
        plugin_active = PluginAssetInfo(
            servers=("server_active_skill",), skills=("active_skill",)
        )
        plugin_dead = PluginAssetInfo(
            servers=("server_dead_skill",), skills=("dead_skill",)
        )
        reg = ActiveRegistrations(
            servers=("server_active_skill", "server_dead_skill"),
            plugins={"p_active": plugin_active, "p_dead": plugin_dead},
        )
        report = compute_prune_recommendations(usage, reg)
        assert "server_active_skill" in report.keep
        assert any(d.server == "server_dead_skill" for d in report.drop)

    def test_enable_per_project_concentration(self) -> None:
        """Server with >= 80% usage in a repo clearing the floor is placed in enable-per-project."""
        tool_stat = StratifiedToolUsage(main_interactive=ToolCallStats(total_calls=10))
        usage = _make_usage(
            total_sessions=50,
            calendar_days=20.0,
            tools={"specialized_tool/query": tool_stat},
            sessions_by_repo={"repo-heavy": 25, "repo-light": 25},
            server_sessions_by_repo={
                "specialized_tool": {
                    "repo-heavy": 9,  # 9 / 10 = 90% concentration
                    "repo-light": 1,
                }
            },
        )
        reg = ActiveRegistrations(servers=("specialized_tool",))
        report = compute_prune_recommendations(usage, reg)
        assert len(report.enable_per_project) == 1
        proj_rec = report.enable_per_project[0]
        assert proj_rec.server == "specialized_tool"
        assert proj_rec.top_repo == "repo-heavy"
        assert proj_rec.concentration_share == 0.90

    def test_enable_per_project_requires_repo_days_floor(self) -> None:
        """Top repo with N_repo >= 20 but < 14 calendar days does not qualify for enable-per-project."""
        tool_stat = StratifiedToolUsage(main_interactive=ToolCallStats(total_calls=10))
        usage = UsageSummary(
            total_sessions=50,
            calendar_days=20.0,
            main_sessions_count=50,
            subagent_sessions_count=0,
            tools={"specialized_tool/query": tool_stat},
            cli_verbs={},
            skills={},
            toolsearch=ToolSearchUsage(),
            e4_transitions={},
            sessions_by_repo={"repo-short-span": 25, "repo-long-span": 25},
            server_sessions_by_repo={
                "specialized_tool": {
                    "repo-short-span": 9,
                    "repo-long-span": 1,
                }
            },
            calendar_days_by_repo={
                "repo-short-span": 5.0,
                "repo-long-span": 20.0,
            },
        )
        reg = ActiveRegistrations(servers=("specialized_tool",))
        report = compute_prune_recommendations(usage, reg)
        assert report.enable_per_project == ()
        assert "specialized_tool" in report.keep

    def test_plugin_namespaced_skill_accounting(self) -> None:
        """Plugin skill invoked as '<plugin>:<skill>' counts as active under R4."""
        usage = _make_usage(
            total_sessions=25,
            calendar_days=15.0,
            skills={
                "p_namespaced:my_skill": StratifiedCount(main_interactive=2),
            },
        )
        plugin_ns = PluginAssetInfo(
            servers=("server_ns_skill",), skills=("my_skill",)
        )
        reg = ActiveRegistrations(
            servers=("server_ns_skill",),
            plugins={"p_namespaced": plugin_ns},
        )
        report = compute_prune_recommendations(usage, reg)
        assert "server_ns_skill" in report.keep
        assert report.drop == ()

