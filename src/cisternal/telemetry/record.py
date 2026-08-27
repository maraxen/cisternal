"""Record: frozen dataclass for normalized telemetry events."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Record:
    """Normalized telemetry record.

    Frozen dataclass (immutable, hashable) with slots for memory efficiency.
    Produced by _build_record() on the producer thread;
    consumed by exporters on the consumer (QueueListener) thread.
    """

    name: str
    """Event name (e.g. 'mcp.call_start', 'cli.cmd_end')."""

    ts: float
    """Unix timestamp (time.time()) on the producer thread at emission."""

    run_uuid: str | None
    """Snapshot of cisternal.telemetry.context.run_uuid_var at build time."""

    mcp_request_id: str | None
    """Snapshot of cisternal.telemetry.context.mcp_request_id_var at build time."""

    task_id: str | None
    """Snapshot of cisternal.telemetry.context.task_id_var at build time."""

    request_id: str | None
    """Snapshot of cisternal.telemetry.context.request_id_var at build time."""

    session_id: str | None
    """Snapshot of cisternal.telemetry.context.session_id_var at build time."""

    phase: str | None
    """Snapshot of cisternal.telemetry.context.phase_var at build time."""

    fields: dict[str, Any]
    """Caller-supplied fields (tool name, duration_ms, arg_keys, etc.)."""

    git_hash: str | None = None
    """Snapshot of cisternal.telemetry.context.git_state_var.hash at build
    time (spec 260827). None until init() has run; "nogit"/"unknown" are the
    captured-but-degraded sentinels -- see telemetry.git_state.GitState."""

    git_branch: str | None = None
    """Snapshot of git_state_var.branch. Same None-vs-sentinel distinction as
    git_hash."""

    git_dirty: bool | None = None
    """Snapshot of git_state_var.dirty. None until init() has run."""

    git_dirty_content_id: str | None = None
    """Snapshot of git_state_var.dirty_content_id. None when the tree wasn't
    dirty, computation was skipped, or init() hasn't run."""

    git_provenance_source: str | None = None
    """Snapshot of git_state_var.provenance_source ("git" | "nogit" |
    "unavailable"). None until init() has run."""
