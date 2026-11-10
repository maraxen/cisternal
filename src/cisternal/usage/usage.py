"""C0 Tracked Usage Telemetry: tool, CLI, skill, and ToolSearch metrics (Spec §C0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import math
from pathlib import Path
import re
from typing import Any, Literal, Sequence

from cisternal.usage.transcript import (
    VerbSpec,
    VerbTable,
    canonical_tool_key,
    discover_transcript_files,
    parse_cli_commands,
    resolve_repo_key,
    stratify_session_type,
    stream_transcript_events,
)

_log = logging.getLogger(__name__)

SessionStratum = Literal["main_interactive", "subagent_headless"]

# Default verbs table for CLI fallback detection (E4)
DEFAULT_VERBS: dict[str, VerbSpec] = {
    "bth": VerbSpec(
        binary="bth",
        subcommands={
            "sql": "bathos/run_sql",
            "show": "bathos/get_run",
            "validate-sidecar": "bathos/validate_sidecar",
        },
        exclude=("run",),
    ),
    "bathos": VerbSpec(
        binary="bathos",
        subcommands={
            "sql": "bathos/run_sql",
            "show": "bathos/get_run",
        },
        exclude=("run",),
    ),
    "praxia": VerbSpec(
        binary="praxia",
        subcommands={
            "status": "praxia/status",
        },
    ),
}


@dataclass(frozen=True, slots=True)
class WilsonInterval:
    lower: float
    upper: float

    def format_pct(self, decimals: int = 1) -> str:
        return f"[{self.lower * 100:.{decimals}f}%, {self.upper * 100:.{decimals}f}%]"


def wilson_confidence_interval(
    successes: int,
    trials: int,
    z: float = 1.95996,
) -> WilsonInterval:
    """Compute two-sided 95% Wilson score confidence interval.

    Formula:
        p_hat = x / n
        denom = 1 + z^2 / n
        center = (p_hat + z^2 / (2n)) / denom
        margin = (z / denom) * sqrt(p_hat * (1 - p_hat) / n + z^2 / (4n^2))
        CI = [max(0.0, center - margin), min(1.0, center + margin)]
    """
    if trials <= 0:
        return WilsonInterval(lower=0.0, upper=0.0)

    p_hat = successes / trials
    denom = 1.0 + (z * z) / trials
    center = (p_hat + (z * z) / (2.0 * trials)) / denom
    radicand = (p_hat * (1.0 - p_hat) / trials) + ((z * z) / (4.0 * trials * trials))
    margin = (z / denom) * math.sqrt(max(0.0, radicand))

    return WilsonInterval(
        lower=max(0.0, center - margin),
        upper=min(1.0, center + margin),
    )


@dataclass(frozen=True, slots=True)
class ToolCallStats:
    total_calls: int = 0
    success_calls: int = 0
    error_calls: int = 0
    durations_ms: tuple[float, ...] = ()

    @property
    def p50(self) -> float | None:
        if not self.durations_ms:
            return None
        sorted_d = sorted(self.durations_ms)
        n = len(sorted_d)
        mid = n // 2
        return (
            sorted_d[mid] if n % 2 != 0 else (sorted_d[mid - 1] + sorted_d[mid]) / 2.0
        )

    @property
    def p95(self) -> float | None:
        if not self.durations_ms:
            return None
        sorted_d = sorted(self.durations_ms)
        idx = int(0.95 * len(sorted_d))
        return sorted_d[min(idx, len(sorted_d) - 1)]

    @property
    def mean_duration(self) -> float | None:
        if not self.durations_ms:
            return None
        return sum(self.durations_ms) / len(self.durations_ms)


@dataclass(frozen=True, slots=True)
class StratifiedToolUsage:
    main_interactive: ToolCallStats = field(default_factory=ToolCallStats)
    subagent_headless: ToolCallStats = field(default_factory=ToolCallStats)

    @property
    def total_calls(self) -> int:
        return self.main_interactive.total_calls + self.subagent_headless.total_calls

    @property
    def total_errors(self) -> int:
        return self.main_interactive.error_calls + self.subagent_headless.error_calls

    @property
    def total_success(self) -> int:
        return (
            self.main_interactive.success_calls + self.subagent_headless.success_calls
        )


@dataclass(frozen=True, slots=True)
class StratifiedCount:
    main_interactive: int = 0
    subagent_headless: int = 0

    @property
    def total(self) -> int:
        return self.main_interactive + self.subagent_headless


@dataclass(frozen=True, slots=True)
class ToolSearchProvenance:
    deferred_listing_only: StratifiedCount = field(default_factory=StratifiedCount)
    prior_mention: StratifiedCount = field(default_factory=StratifiedCount)


@dataclass(frozen=True, slots=True)
class ToolSearchUsage:
    select_exact: StratifiedCount = field(default_factory=StratifiedCount)
    keyword_queries: StratifiedCount = field(default_factory=StratifiedCount)
    provenance: ToolSearchProvenance = field(default_factory=ToolSearchProvenance)


@dataclass(frozen=True, slots=True)
class E4TransitionRate:
    successes: int
    trials: int
    rate: float
    ci_95: WilsonInterval


@dataclass(frozen=True, slots=True)
class UsageSummary:
    total_sessions: int
    calendar_days: float
    main_sessions_count: int
    subagent_sessions_count: int
    tools: dict[str, StratifiedToolUsage]
    cli_verbs: dict[str, StratifiedCount]
    skills: dict[str, StratifiedCount]
    toolsearch: ToolSearchUsage
    e4_transitions: dict[str, E4TransitionRate]
    sessions_by_repo: dict[str, int]
    server_sessions_by_repo: dict[str, dict[str, int]] = field(default_factory=dict)
    calendar_days_by_repo: dict[str, float] = field(default_factory=dict)


def check_paired_controls(
    usage: UsageSummary,
    planted_tool: str = "bathos/run_sql",
    uncalled_tool: str = "bathos/planted_uncalled",
    expected_planted: int = 5,
) -> bool:
    """Validate paired synthetic controls for C0 usage counter."""
    planted_stat = usage.tools.get(planted_tool)
    planted_count = planted_stat.total_calls if planted_stat else 0
    if planted_count != expected_planted:
        _log.warning(
            "Paired control failed: %s count is %d, expected %d",
            planted_tool,
            planted_count,
            expected_planted,
        )
        return False

    uncalled_stat = usage.tools.get(uncalled_tool)
    uncalled_count = uncalled_stat.total_calls if uncalled_stat else 0
    if uncalled_count != 0:
        _log.warning(
            "Paired control failed: %s count is %d, expected 0",
            uncalled_tool,
            uncalled_count,
        )
        return False

    if len(usage.tools) < 2:
        _log.warning(
            "Paired control failed: total distinct parsed tools is %d, expected >= 2",
            len(usage.tools),
        )
        return False

    return True


def _parse_timestamp(ts: Any) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            # Handle ISO string with or without Z
            cleaned = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt.timestamp()
        except Exception:
            return None
    return None


def _is_error_result(result_content: Any, is_error_flag: bool | None) -> bool:
    if is_error_flag is True:
        return True
    if isinstance(result_content, str):
        try:
            parsed = json.loads(result_content)
            if isinstance(parsed, dict):
                if parsed.get("ok") is False or "error_code" in parsed:
                    return True
        except Exception:
            pass
        if "error" in result_content.lower() and "failed" in result_content.lower():
            return True
    elif isinstance(result_content, dict):
        if result_content.get("ok") is False or "error_code" in result_content:
            return True
    return False


def _load_server_log_durations(log_dir: Path | None) -> list[tuple[str, float, float]]:
    """Load (canonical_tool, timestamp_sec, duration_ms) from server JSONL logs."""
    if not log_dir or not log_dir.is_dir():
        return []

    records: list[tuple[str, float, float]] = []
    for path in log_dir.glob("**/*.jsonl"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(doc, dict):
                        continue

                    # Extract tool, duration_ms, timestamp
                    tool = doc.get("tool") or doc.get("fields", {}).get("tool")
                    duration = doc.get("duration_ms") or doc.get("fields", {}).get(
                        "duration_ms"
                    )
                    ts = (
                        doc.get("timestamp")
                        or doc.get("ts")
                        or doc.get("fields", {}).get("timestamp")
                    )

                    if tool and duration is not None:
                        t_sec = _parse_timestamp(ts)
                        if t_sec is not None:
                            try:
                                d_val = float(duration)
                                # Normalize tool if needed
                                c_tool = str(tool)
                                if c_tool.startswith("mcp__"):
                                    c_tool = canonical_tool_key(c_tool)
                                records.append((c_tool, t_sec, d_val))
                            except (ValueError, TypeError):
                                continue
        except OSError:
            continue
    return records


@dataclass
class _ActionRecord:
    action_type: str  # "mcp", "cli", "other"
    canonical_tool: str | None = None
    cli_pair: tuple[str, str] | None = None
    is_error: bool = False
    timestamp: float | None = None


def compute_usage_summary(
    projects_root: Path | None = None,
    *,
    session_files: Sequence[Path] | None = None,
    log_dir: Path | None = None,
    verbs: VerbTable | None = None,
    declared_servers: Sequence[str] = (),
) -> UsageSummary:
    """Compute usage telemetry across Claude Code session transcripts."""
    vtable: VerbTable = verbs or DEFAULT_VERBS

    # 1. Discover transcript files
    file_items: list[tuple[str, Path]] = []
    if session_files is not None:
        for p in session_files:
            file_items.append((p.parent.name, p))
    elif projects_root is not None:
        file_items = list(discover_transcript_files(projects_root))
    else:
        from cisternal.plugin.shared import claude_home

        p_root = claude_home() / "projects"
        file_items = list(discover_transcript_files(p_root)) if p_root.is_dir() else []

    # 2. Load optional server logs for duration enrichment
    server_records = _load_server_log_durations(log_dir)

    # Accumulators
    total_sessions = 0
    main_sessions_count = 0
    subagent_sessions_count = 0
    timestamps: list[float] = []

    # Repo counts
    sessions_by_repo: dict[str, int] = {}
    server_sessions_by_repo: dict[str, dict[str, int]] = {}
    timestamps_by_repo: dict[str, list[float]] = {}

    # Tool stats: canonical_key -> { "main": [calls, successes, errors, [durations]], "subagent": ... }
    tool_counts: dict[str, dict[str, Any]] = {}
    cli_counts: dict[str, dict[str, int]] = {}
    skill_counts: dict[str, dict[str, int]] = {}

    # ToolSearch stats
    ts_select_exact = {"main_interactive": 0, "subagent_headless": 0}
    ts_keyword = {"main_interactive": 0, "subagent_headless": 0}
    ts_deferred_only = {"main_interactive": 0, "subagent_headless": 0}
    ts_prior_mention = {"main_interactive": 0, "subagent_headless": 0}

    # E4 transitions: error/success trials and fallbacks
    e4_error_trials = 0
    e4_error_fallbacks = 0
    e4_success_trials = 0
    e4_success_fallbacks = 0

    # Map from canonical_tool to matching CLI verb (binary, subcommand)
    tool_to_cli_verb: dict[str, set[tuple[str, str]]] = {}
    for b_name, b_spec in vtable.items():
        subcmds = getattr(b_spec, "subcommands", None)
        if subcmds is None and isinstance(b_spec, dict):
            subcmds = b_spec.get("subcommands", {})
        if isinstance(subcmds, dict):
            for scmd, target_tool in subcmds.items():
                if isinstance(target_tool, str):
                    tool_to_cli_verb.setdefault(target_tool, set()).add((b_name, scmd))

    # Process each session file
    for slug, s_path in file_items:
        events = list(stream_transcript_events(s_path))
        if not events:
            continue

        stratum: SessionStratum = stratify_session_type(events, s_path)

        total_sessions += 1
        if stratum == "main_interactive":
            main_sessions_count += 1
        else:
            subagent_sessions_count += 1

        # Determine cwd and slug for repo folding
        session_cwd = ""
        resolved_slug = slug
        if s_path.parent.name == "subagents":
            resolved_slug = s_path.parent.parent.parent.name

        for ev in events:
            raw = ev.raw_record
            if raw.get("cwd"):
                session_cwd = str(raw["cwd"])
                break
            if raw.get("payload", {}).get("cwd"):
                session_cwd = str(raw["payload"]["cwd"])
                break

        repo_key = resolve_repo_key(session_cwd or str(s_path.parent), resolved_slug)
        sessions_by_repo[repo_key] = sessions_by_repo.get(repo_key, 0) + 1

        # Track prior mentions for E3 ToolSearch provenance
        prior_mentions: set[str] = set()

        # Track distinct servers called in this session
        session_servers: set[str] = set()

        # Build ordered list of actions in this session for E4 transition tracking
        session_actions: list[_ActionRecord] = []

        # Tool result index: tool_use_id -> (is_error, content)
        tool_results: dict[str, tuple[bool, Any]] = {}
        for ev in events:
            raw = ev.raw_record
            msg = raw.get("message") or raw
            content_blocks = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content_blocks, list):
                for b in content_blocks:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tid = str(b.get("tool_use_id") or "")
                        tool_results[tid] = (
                            bool(b.get("is_error")),
                            b.get("content"),
                        )
            elif raw.get("type") == "tool_result":
                tid = str(raw.get("tool_use_id") or "")
                tool_results[tid] = (
                    bool(raw.get("is_error")),
                    raw.get("content"),
                )

        # Iterate through events to extract tool uses, CLI commands, skills, toolsearch
        for ev in events:
            t_sec = _parse_timestamp(ev.timestamp)
            if t_sec is not None:
                timestamps.append(t_sec)
                timestamps_by_repo.setdefault(repo_key, []).append(t_sec)

            raw = ev.raw_record
            ev_type = ev.event_type

            # Check user/assistant text for mentions
            msg = raw.get("message") or raw
            if isinstance(msg, dict):
                text_content = msg.get("content")
                if isinstance(text_content, str):
                    for word in re.findall(r"[a-zA-Z0-9_/-]{3,}", text_content):
                        prior_mentions.add(word)

            # Check invoked_skills
            if ev_type == "invoked_skills" or "invoked_skills" in raw:
                sk_list = raw.get("skills") or raw.get("invoked_skills") or []
                if isinstance(sk_list, list):
                    for sk in sk_list:
                        sk_name = str(sk)
                        if sk_name not in skill_counts:
                            skill_counts[sk_name] = {
                                "main_interactive": 0,
                                "subagent_headless": 0,
                            }
                        skill_counts[sk_name][stratum] += 1

            # Extract tool_use blocks
            content_blocks: list[dict[str, Any]] = []
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                for b in msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        content_blocks.append(b)
            elif raw.get("type") == "tool_use":
                content_blocks.append(raw)

            for b in content_blocks:
                call_id = str(b.get("id") or "")
                t_name = str(b.get("name") or "")
                t_input = b.get("input") or {}
                if not isinstance(t_input, dict):
                    t_input = {}

                # 1. ToolSearch
                if t_name == "ToolSearch":
                    query = str(t_input.get("query") or "")
                    if query.startswith("select:"):
                        ts_select_exact[stratum] += 1
                        target_tool = query.removeprefix("select:").strip()
                        # Provenance check (E3)
                        if any(
                            target_tool in m or m in target_tool for m in prior_mentions
                        ):
                            ts_prior_mention[stratum] += 1
                        else:
                            ts_deferred_only[stratum] += 1
                    else:
                        ts_keyword[stratum] += 1
                    session_actions.append(
                        _ActionRecord(action_type="other", timestamp=t_sec)
                    )
                    continue

                # 2. Skill tool
                if t_name == "Skill":
                    sk_name = str(t_input.get("skill") or "")
                    if sk_name:
                        if sk_name not in skill_counts:
                            skill_counts[sk_name] = {
                                "main_interactive": 0,
                                "subagent_headless": 0,
                            }
                        skill_counts[sk_name][stratum] += 1
                    session_actions.append(
                        _ActionRecord(action_type="other", timestamp=t_sec)
                    )
                    continue

                # 3. Bash CLI tool
                if t_name == "Bash":
                    cmd = str(t_input.get("command") or "")
                    cli_pairs = parse_cli_commands(cmd, vtable)
                    for b_bin, b_sub in cli_pairs:
                        key = f"{b_bin} {b_sub}"
                        if key not in cli_counts:
                            cli_counts[key] = {
                                "main_interactive": 0,
                                "subagent_headless": 0,
                            }
                        cli_counts[key][stratum] += 1
                        session_actions.append(
                            _ActionRecord(
                                action_type="cli",
                                cli_pair=(b_bin, b_sub),
                                timestamp=t_sec,
                            )
                        )
                    if not cli_pairs:
                        session_actions.append(
                            _ActionRecord(action_type="other", timestamp=t_sec)
                        )
                    continue

                # 4. MCP tool
                canonical: str | None = None
                if t_name.startswith("mcp__"):
                    try:
                        canonical = canonical_tool_key(
                            t_name, declared_servers=declared_servers
                        )
                    except ValueError:
                        canonical = None
                elif "/" in t_name:
                    canonical = t_name
                # Bare tool name without server context is rejected per GAP-04 / NC
                elif declared_servers and len(declared_servers) == 1:
                    canonical = f"{declared_servers[0]}/{t_name}"

                if canonical:
                    # Determine result status
                    res_error_flag, res_content = tool_results.get(
                        call_id, (None, None)
                    )
                    is_err = _is_error_result(res_content, res_error_flag)

                    # Duration enrichment
                    matched_duration: float | None = None
                    if t_sec is not None and server_records:
                        for s_tool, s_ts, s_dur in server_records:
                            if s_tool == canonical and abs(s_ts - t_sec) <= 5.0:
                                matched_duration = s_dur
                                break

                    # Record stats
                    if canonical not in tool_counts:
                        tool_counts[canonical] = {
                            "main_interactive": {
                                "total": 0,
                                "success": 0,
                                "error": 0,
                                "durations": [],
                            },
                            "subagent_headless": {
                                "total": 0,
                                "success": 0,
                                "error": 0,
                                "durations": [],
                            },
                        }
                    st_entry = tool_counts[canonical][stratum]
                    st_entry["total"] += 1
                    if is_err:
                        st_entry["error"] += 1
                    else:
                        st_entry["success"] += 1
                    if matched_duration is not None:
                        st_entry["durations"].append(matched_duration)

                    session_servers.add(canonical.split("/", 1)[0])
                    session_actions.append(
                        _ActionRecord(
                            action_type="mcp",
                            canonical_tool=canonical,
                            is_error=is_err,
                            timestamp=t_sec,
                        )
                    )
                else:
                    session_actions.append(
                        _ActionRecord(action_type="other", timestamp=t_sec)
                    )

        for srv in session_servers:
            repo_map = server_sessions_by_repo.setdefault(srv, {})
            repo_map[repo_key] = repo_map.get(repo_key, 0) + 1

        # E4 Transition analysis for this session
        for i, act in enumerate(session_actions):
            if act.action_type != "mcp" or not act.canonical_tool:
                continue

            target_verbs = tool_to_cli_verb.get(act.canonical_tool, set())
            if not target_verbs:
                continue

            # Look ahead up to 3 actions in the session
            has_same_verb_fallback = False
            for next_act in session_actions[i + 1 : i + 4]:
                if next_act.action_type == "cli" and next_act.cli_pair:
                    if next_act.cli_pair in target_verbs:
                        has_same_verb_fallback = True
                        break

            if act.is_error:
                e4_error_trials += 1
                if has_same_verb_fallback:
                    e4_error_fallbacks += 1
            else:
                e4_success_trials += 1
                if has_same_verb_fallback:
                    e4_success_fallbacks += 1

    # Calendar days span
    calendar_days = 0.0
    if len(timestamps) >= 2:
        calendar_days = max(0.0, (max(timestamps) - min(timestamps)) / 86400.0)

    calendar_days_by_repo: dict[str, float] = {}
    for r_key, r_ts in timestamps_by_repo.items():
        if len(r_ts) >= 2:
            calendar_days_by_repo[r_key] = max(0.0, (max(r_ts) - min(r_ts)) / 86400.0)
        else:
            calendar_days_by_repo[r_key] = 0.0

    # Compile final structured dataclasses
    final_tools: dict[str, StratifiedToolUsage] = {}
    for c_key, data in sorted(tool_counts.items()):
        main_d = data["main_interactive"]
        sub_d = data["subagent_headless"]
        final_tools[c_key] = StratifiedToolUsage(
            main_interactive=ToolCallStats(
                total_calls=main_d["total"],
                success_calls=main_d["success"],
                error_calls=main_d["error"],
                durations_ms=tuple(main_d["durations"]),
            ),
            subagent_headless=ToolCallStats(
                total_calls=sub_d["total"],
                success_calls=sub_d["success"],
                error_calls=sub_d["error"],
                durations_ms=tuple(sub_d["durations"]),
            ),
        )

    final_cli: dict[str, StratifiedCount] = {
        k: StratifiedCount(
            main_interactive=v["main_interactive"],
            subagent_headless=v["subagent_headless"],
        )
        for k, v in sorted(cli_counts.items())
    }

    final_skills: dict[str, StratifiedCount] = {
        k: StratifiedCount(
            main_interactive=v["main_interactive"],
            subagent_headless=v["subagent_headless"],
        )
        for k, v in sorted(skill_counts.items())
    }

    final_toolsearch = ToolSearchUsage(
        select_exact=StratifiedCount(**ts_select_exact),
        keyword_queries=StratifiedCount(**ts_keyword),
        provenance=ToolSearchProvenance(
            deferred_listing_only=StratifiedCount(**ts_deferred_only),
            prior_mention=StratifiedCount(**ts_prior_mention),
        ),
    )

    # E4 transition rates with Wilson 95% CIs
    e4_transitions: dict[str, E4TransitionRate] = {
        "error_to_cli": E4TransitionRate(
            successes=e4_error_fallbacks,
            trials=e4_error_trials,
            rate=(e4_error_fallbacks / e4_error_trials) if e4_error_trials > 0 else 0.0,
            ci_95=wilson_confidence_interval(e4_error_fallbacks, e4_error_trials),
        ),
        "success_to_cli": E4TransitionRate(
            successes=e4_success_fallbacks,
            trials=e4_success_trials,
            rate=(e4_success_fallbacks / e4_success_trials)
            if e4_success_trials > 0
            else 0.0,
            ci_95=wilson_confidence_interval(e4_success_fallbacks, e4_success_trials),
        ),
    }

    return UsageSummary(
        total_sessions=total_sessions,
        calendar_days=calendar_days,
        main_sessions_count=main_sessions_count,
        subagent_sessions_count=subagent_sessions_count,
        tools=final_tools,
        cli_verbs=final_cli,
        skills=final_skills,
        toolsearch=final_toolsearch,
        e4_transitions=e4_transitions,
        sessions_by_repo=sessions_by_repo,
        server_sessions_by_repo=server_sessions_by_repo,
        calendar_days_by_repo=calendar_days_by_repo,
    )
