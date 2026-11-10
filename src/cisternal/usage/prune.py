"""Prune list recommendation engine: keep, drop, and enable-per-project bucketing (Spec §C1).

Invariants:
1. Floor check: $N >= 20$ sessions AND calendar days $>= 14$. Below floor, recommendations are suppressed.
2. Historical un-registered servers in transcripts are ignored.
3. Whitelisting: active plugins with hooks or commands are NEVER placed in drop.
4. R4 Skill accounting: plugins with skills are dropped only if all skills have 0 invocations.
5. Concentration: servers with >= 80% sessions in top repo (which clears floor) become enable-per-project.
6. Rule of Three: drop candidates report 3.0 / N upper bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging

from cisternal.usage.registrations import ActiveRegistrations, PluginAssetInfo
from cisternal.usage.usage import UsageSummary

_log = logging.getLogger(__name__)


class PruneAction(str, Enum):
    KEEP = "keep"
    DROP = "drop"
    ENABLE_PER_PROJECT = "enable-per-project"


@dataclass(frozen=True, slots=True)
class DropRecommendation:
    server: str
    plugin: str | None
    rule_of_three_bound: float
    reason: str


@dataclass(frozen=True, slots=True)
class ProjectRecommendation:
    server: str
    top_repo: str
    concentration_share: float
    repo_sessions: int
    reason: str


@dataclass(frozen=True, slots=True)
class PruneReport:
    floor_cleared: bool
    total_sessions: int
    calendar_days: float
    suppression_reason: str | None
    keep: tuple[str, ...]
    drop: tuple[DropRecommendation, ...]
    enable_per_project: tuple[ProjectRecommendation, ...]


def compute_prune_recommendations(
    usage: UsageSummary,
    registrations: ActiveRegistrations,
    *,
    min_sessions: int = 20,
    min_days: int = 14,
    concentration_threshold: float = 0.80,
) -> PruneReport:
    """Compute keep, drop, and enable-per-project server recommendations."""
    # 1. Lookback floor validation: N >= 20 AND >= 14 calendar days
    floor_cleared = (usage.total_sessions >= min_sessions) and (
        usage.calendar_days >= min_days
    )
    if not floor_cleared:
        suppression_reason = (
            f"N={usage.total_sessions} sessions over {usage.calendar_days:.1f} days; "
            f"floor is N>={min_sessions} AND >={min_days} days. Recommendations suppressed."
        )
        return PruneReport(
            floor_cleared=False,
            total_sessions=usage.total_sessions,
            calendar_days=usage.calendar_days,
            suppression_reason=suppression_reason,
            keep=tuple(sorted(registrations.servers)),
            drop=(),
            enable_per_project=(),
        )

    # Rule of Three upper bound: 3.0 / N
    bound_p95 = (
        min(1.0, 3.0 / usage.total_sessions) if usage.total_sessions > 0 else 1.0
    )

    keep_servers: list[str] = []
    drop_recommendations: list[DropRecommendation] = []
    project_recommendations: list[ProjectRecommendation] = []

    # Map server to owning plugin
    server_to_plugin: dict[str, str] = {}
    for p_name, p_info in registrations.plugins.items():
        for s in p_info.servers:
            server_to_plugin[s] = p_name
        if p_name in registrations.servers:
            server_to_plugin[p_name] = p_name

    # Evaluate each registered server
    for server in sorted(registrations.servers):
        # Calculate total MCP calls for this server
        server_calls = sum(
            stat.total_calls
            for tool_key, stat in usage.tools.items()
            if tool_key == server or tool_key.startswith(f"{server}/")
        )

        owning_plugin_name = server_to_plugin.get(server)
        owning_plugin: PluginAssetInfo | None = None
        if owning_plugin_name and owning_plugin_name in registrations.plugins:
            owning_plugin = registrations.plugins[owning_plugin_name]

        if server_calls > 0:
            # Check for concentration in a single repository
            repo_sessions_map = usage.server_sessions_by_repo.get(server, {})
            total_calling_sessions = sum(repo_sessions_map.values())

            if total_calling_sessions > 0 and len(repo_sessions_map) > 0:
                top_repo, top_calling_sessions = max(
                    repo_sessions_map.items(), key=lambda item: item[1]
                )
                share = top_calling_sessions / total_calling_sessions
                top_repo_total_sessions = usage.sessions_by_repo.get(top_repo, 0)

                # Top repo must have >= concentration_threshold AND independently clear the floor
                top_repo_days = usage.calendar_days_by_repo.get(
                    top_repo, usage.calendar_days
                )
                if (
                    share >= concentration_threshold
                    and top_repo_total_sessions >= min_sessions
                    and top_repo_days >= min_days
                ):
                    project_recommendations.append(
                        ProjectRecommendation(
                            server=server,
                            top_repo=top_repo,
                            concentration_share=share,
                            repo_sessions=top_repo_total_sessions,
                            reason=(
                                f"{share * 100:.1f}% of calling sessions concentrated in repository {top_repo!r} "
                                f"({top_repo_total_sessions} sessions)"
                            ),
                        )
                    )
                    continue

            keep_servers.append(server)
            continue

        # server_calls == 0: check non-MCP asset whitelisting
        if owning_plugin is not None:
            # Whitelist: plugin ships hooks
            if owning_plugin.hooks:
                keep_servers.append(server)
                continue

            # Whitelist: plugin ships commands
            if owning_plugin.commands:
                keep_servers.append(server)
                continue

            # R4 Skill accounting: plugin ships skills
            if owning_plugin.skills:
                # Check if any skill of this plugin was invoked (bare <skill> or <plugin>:<skill>)
                skill_invocations = 0
                for sk in owning_plugin.skills:
                    if sk in usage.skills:
                        skill_invocations += usage.skills[sk].total
                    if (
                        owning_plugin_name
                        and f"{owning_plugin_name}:{sk}" in usage.skills
                    ):
                        skill_invocations += usage.skills[
                            f"{owning_plugin_name}:{sk}"
                        ].total
                if skill_invocations > 0:
                    keep_servers.append(server)
                    continue
                else:
                    drop_recommendations.append(
                        DropRecommendation(
                            server=server,
                            plugin=owning_plugin_name,
                            rule_of_three_bound=bound_p95,
                            reason=f"0 MCP calls across {usage.total_sessions} sessions, and all plugin skills had 0 invocations",
                        )
                    )
                    continue

        # Standalone server with 0 calls or plugin with no hooks/commands/skills
        drop_recommendations.append(
            DropRecommendation(
                server=server,
                plugin=owning_plugin_name,
                rule_of_three_bound=bound_p95,
                reason=f"0 MCP calls across {usage.total_sessions} sessions (p95 usage bound <= {bound_p95 * 100:.1f}%)",
            )
        )

    return PruneReport(
        floor_cleared=True,
        total_sessions=usage.total_sessions,
        calendar_days=usage.calendar_days,
        suppression_reason=None,
        keep=tuple(keep_servers),
        drop=tuple(drop_recommendations),
        enable_per_project=tuple(project_recommendations),
    )
