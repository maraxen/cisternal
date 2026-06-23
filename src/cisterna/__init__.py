"""Cisterna: Shared telemetry substrate for praxia tool family.

Public API (spec §3.2 — M1 telemetry + M2 registration surface):

  M1 — Telemetry:
    init(log_dir, max_bytes, backup_count, exporters): Initialize pipeline
    emit_event(name, **fields): Emit a telemetry event
    span(name, **fields): Sync timing context manager
    aspan(name, **fields): Async timing context manager
    status(): Get pipeline health status

  M2 — Registration surface (B+G2 hybrid design, challenger-hardened):
    tool: Pure-metadata decorator for registering MCP tools (A1, A2).
          @cisterna.tool returns the original fn unchanged (decorated_fn is fn).
    wire(server, app, *, adapter, registry, expected, validate):
          Snapshot a registry at call time and register each tool on a FastMCP
          server (and optionally a Cyclopts App). Returns a WiredRegistry.
    WiredRegistry: Introspection object returned by wire().
    CisternaWireError: Raised by wire() when expected tools are missing.
    clear_registry(name): Test teardown helper; clears a named registry (A7).

Design assumptions (spec §assumptions):
  A1 — FastMCP v3 uses asyncio.iscoroutinefunction() to decide whether to await
        the tool callable. The generated MCP callable is always async def.
  A2 — FastMCP v3 reads inspect.signature(fn) for JSON schema generation.
        Explicit __signature__ injection (H1) controls what FastMCP sees.
  A3 — M1 CisternaMiddleware is installed on the FastMCP server before wire()
        is called. Telemetry and shape adaptation are M1's exclusive responsibility.
  A4 — Cyclopts 4.18.0+ calls asyncio.run() for async def command functions when
        no event loop is running; inside a running loop, use app.run_async().
  A5 — Global registry state is process-scoped; no cross-process sharing.
  A6 — Python >= 3.11 (asyncio.get_running_loop() is the stable API).
  A7 — Test environments call cisterna.clear_registry() in teardown to prevent
        cross-test registry contamination.

HARD INVARIANT (C5/AC-M2-6):
  The M2 wire-time MCP callable is a PURE PASSTHROUGH — it MUST NOT call any
  adapter.emit_* or adapter.shape_* methods, or emit ANY telemetry. All
  telemetry and shaping is exclusively owned by M1 CisternaMiddleware.
"""

from pathlib import Path
from typing import Any

from cisterna.telemetry import (
    init_pipeline,
    get_pipeline,
    span,
    aspan,
    job_span,
    status,
    ExporterBase,
    _build_record,
)
from cisterna.registration.decorator import tool
from cisterna.registration.errors import CisternaWireError
from cisterna.registration.registry import clear_registry

# M3 (assets export)
from cisterna.assets.spec import AssetSpec
from cisterna.assets.bundle import AssetBundle
from cisterna.assets.source import registry_assets
from cisterna.export.base import Emitter
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.write import write_bundle


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


def _lazy_import(name: str) -> object:
    """Lazy re-export for wire and WiredRegistry to defer fastmcp import."""
    if name == "wire":
        from cisterna.registration.wired import wire as _wire
        return _wire
    if name == "WiredRegistry":
        from cisterna.registration.wired import WiredRegistry as _WiredRegistry
        return _WiredRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str) -> object:
    return _lazy_import(name)


__all__ = [
    # M1 — Telemetry
    "init",
    "emit_event",
    "span",
    "aspan",
    "job_span",
    "status",
    # M2 — Registration surface
    "tool",
    "wire",
    "WiredRegistry",
    "CisternaWireError",
    "clear_registry",
    # M3 (assets export)
    "AssetSpec",
    "AssetBundle",
    "registry_assets",
    "Emitter",
    "ClaudeEmitter",
    "write_bundle",
]
