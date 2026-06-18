"""Cisterna: Shared telemetry substrate for praxia tool family.

Public API (spec §3.2):
  - init(log_dir, max_bytes, backup_count, exporters): Initialize pipeline
  - emit_event(name, **fields): Emit a telemetry event
  - span(name, **fields): Sync timing context manager
  - aspan(name, **fields): Async timing context manager
  - status(): Get pipeline health status
  - tool: Pure-metadata decorator for registering MCP tools
  - clear_registry: Test teardown helper; clears a named registry
"""

from pathlib import Path
from typing import Any

from cisterna.telemetry import (
    init_pipeline,
    get_pipeline,
    span,
    aspan,
    status,
    ExporterBase,
    _build_record,
)
from cisterna.registration.decorator import tool
from cisterna.registration.registry import clear_registry


def init(
    log_dir: str | Path | None = None,
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
    exporters: list[ExporterBase] | None = None,
    heartbeat_interval: float = 30.0,
) -> None:
    """Initialize the telemetry pipeline (idempotent).

    Args:
        log_dir: Directory for JSONL logs. If None, resolves via env vars or defaults to ~/.cisterna/logs.
        max_bytes: Max file size before rotation (default 10 MB).
        backup_count: Number of backup files to keep.
        exporters: Custom exporters. If None, uses JsonlExporter with log_dir.
        heartbeat_interval: Seconds between liveness heartbeat probes (default 30s).
    """
    init_pipeline(
        log_dir=log_dir,
        max_bytes=max_bytes,
        backup_count=backup_count,
        exporters=exporters,
        heartbeat_interval=heartbeat_interval,
    )


def emit_event(name: str, **fields: Any) -> None:
    """Emit a telemetry event.

    Snapshots contextvars on this thread, builds a Record, and enqueues
    it for non-blocking export. Never raises.

    Args:
        name: Event name (e.g. 'mcp.call_start').
        **fields: Event fields (e.g. tool='foo', request_id='xyz').
    """
    import time

    pipeline = get_pipeline()
    if pipeline is None:
        return

    record = _build_record(name, ts=time.time(), **fields)
    if record is not None:
        pipeline.emit(record)


__all__ = [
    "init",
    "emit_event",
    "span",
    "aspan",
    "status",
    "tool",
    "clear_registry",
]
