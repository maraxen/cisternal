"""Usage telemetry, derived data paths, and transcript parsing infrastructure."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cisternal.usage.paths import (
        MAX_FILE_SIZE_BYTES,
        MAX_RECORD_LINE_BYTES,
        TRUNCATION_MARKER,
        atomic_append_jsonl,
        resolve_sessions_dir,
    )
    from cisternal.usage.prune import (
        DropRecommendation,
        ProjectRecommendation,
        PruneAction,
        PruneReport,
        compute_prune_recommendations,
    )
    from cisternal.usage.registrations import (
        ActiveRegistrations,
        PluginAssetInfo,
        scan_active_registrations,
    )
    from cisternal.usage.transcript import (
        SessionType,
        ToolKey,
        TranscriptEvent,
        VerbSpec,
        VerbTable,
        canonical_tool_key,
        discover_transcript_files,
        parse_cli_command,
        parse_cli_commands,
        resolve_repo_key,
        stratify_session_type,
        stream_transcript_events,
    )
    from cisternal.usage.usage import (
        DEFAULT_VERBS,
        E4TransitionRate,
        StratifiedCount,
        StratifiedToolUsage,
        ToolCallStats,
        ToolSearchProvenance,
        ToolSearchUsage,
        UsageSummary,
        WilsonInterval,
        check_paired_controls,
        compute_usage_summary,
        wilson_confidence_interval,
    )

_SUBMODULE_MAP: dict[str, str] = {
    "MAX_FILE_SIZE_BYTES": ".paths",
    "MAX_RECORD_LINE_BYTES": ".paths",
    "TRUNCATION_MARKER": ".paths",
    "atomic_append_jsonl": ".paths",
    "resolve_sessions_dir": ".paths",
    "DropRecommendation": ".prune",
    "ProjectRecommendation": ".prune",
    "PruneAction": ".prune",
    "PruneReport": ".prune",
    "compute_prune_recommendations": ".prune",
    "ActiveRegistrations": ".registrations",
    "PluginAssetInfo": ".registrations",
    "scan_active_registrations": ".registrations",
    "SessionType": ".transcript",
    "ToolKey": ".transcript",
    "TranscriptEvent": ".transcript",
    "VerbSpec": ".transcript",
    "VerbTable": ".transcript",
    "canonical_tool_key": ".transcript",
    "discover_transcript_files": ".transcript",
    "parse_cli_command": ".transcript",
    "parse_cli_commands": ".transcript",
    "resolve_repo_key": ".transcript",
    "stratify_session_type": ".transcript",
    "stream_transcript_events": ".transcript",
    "DEFAULT_VERBS": ".usage",
    "E4TransitionRate": ".usage",
    "StratifiedCount": ".usage",
    "StratifiedToolUsage": ".usage",
    "ToolCallStats": ".usage",
    "ToolSearchProvenance": ".usage",
    "ToolSearchUsage": ".usage",
    "UsageSummary": ".usage",
    "WilsonInterval": ".usage",
    "check_paired_controls": ".usage",
    "compute_usage_summary": ".usage",
    "wilson_confidence_interval": ".usage",
}

__all__ = [
    "ActiveRegistrations",
    "DEFAULT_VERBS",
    "DropRecommendation",
    "E4TransitionRate",
    "MAX_FILE_SIZE_BYTES",
    "MAX_RECORD_LINE_BYTES",
    "PluginAssetInfo",
    "ProjectRecommendation",
    "PruneAction",
    "PruneReport",
    "SessionType",
    "StratifiedCount",
    "StratifiedToolUsage",
    "TRUNCATION_MARKER",
    "ToolCallStats",
    "ToolKey",
    "ToolSearchProvenance",
    "ToolSearchUsage",
    "TranscriptEvent",
    "UsageSummary",
    "VerbSpec",
    "VerbTable",
    "WilsonInterval",
    "atomic_append_jsonl",
    "canonical_tool_key",
    "check_paired_controls",
    "compute_prune_recommendations",
    "compute_usage_summary",
    "discover_transcript_files",
    "parse_cli_command",
    "parse_cli_commands",
    "resolve_repo_key",
    "resolve_sessions_dir",
    "scan_active_registrations",
    "stratify_session_type",
    "stream_transcript_events",
    "wilson_confidence_interval",
]


def __getattr__(name: str) -> Any:
    mod_name = _SUBMODULE_MAP.get(name)
    if mod_name is not None:
        mod = importlib.import_module(mod_name, __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
