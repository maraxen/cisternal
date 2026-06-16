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
    """Snapshot of cisterna.telemetry.context.run_uuid_var at build time."""

    mcp_request_id: str | None
    """Snapshot of cisterna.telemetry.context.mcp_request_id_var at build time."""

    task_id: str | None
    """Snapshot of cisterna.telemetry.context.task_id_var at build time."""

    request_id: str | None
    """Snapshot of cisterna.telemetry.context.request_id_var at build time."""

    session_id: str | None
    """Snapshot of cisterna.telemetry.context.session_id_var at build time."""

    phase: str | None
    """Snapshot of cisterna.telemetry.context.phase_var at build time."""

    fields: dict[str, Any]
    """Caller-supplied fields (tool name, duration_ms, arg_keys, etc.)."""
