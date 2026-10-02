"""Cisternal: Shared telemetry substrate for praxia tool family.

Public API (spec §3.2 — M1 telemetry + M2 registration surface):

  M1 — Telemetry:
    init(log_dir, max_bytes, backup_count, exporters): Initialize pipeline
    emit_event(name, **fields): Emit a telemetry event
    span(name, **fields): Sync timing context manager
    aspan(name, **fields): Async timing context manager
    status(): Get pipeline health status

  M2 — Registration surface (B+G2 hybrid design, challenger-hardened):
    tool: Pure-metadata decorator for registering MCP tools (A1, A2).
          @cisternal.tool returns the original fn unchanged (decorated_fn is fn).
    wire(server, app, *, adapter, registry, expected, validate, recovery):
          Snapshot a registry at call time and register each tool on a FastMCP
          server (and optionally a Cyclopts App). Returns a WiredRegistry.
          `recovery=(is_recoverable, recover)` (optional; spec
          260805_nlm-adapter-transparent-auto-reauth) applies a transparent
          retry-once-after-recovery policy uniformly to every entry's MCP
          callable and CLI closure; `None` (default) is unaffected.
    WiredRegistry: Introspection object returned by wire().
    CliContract, CliOption, CliContext, json_option, default_report,
    exit_code_attr, cli_command, cli_group: the rich CLI contract for wire()
          (cisternal #30). Defined in the fastmcp-free
          cisternal.registration.cli_contract and imported eagerly.
    CisternalWireError: Raised by wire() when expected tools are missing.
    clear_registry(name): Test teardown helper; clears a named registry (A7).

Design assumptions (spec §assumptions):
  A1 — FastMCP v3 uses asyncio.iscoroutinefunction() to decide whether to await
        the tool callable. The generated MCP callable is always async def.
  A2 — FastMCP v3 reads inspect.signature(fn) for JSON schema generation.
        Explicit __signature__ injection (H1) controls what FastMCP sees.
  A3 — M1 CisternalMiddleware is installed on the FastMCP server before wire()
        is called. Telemetry and shape adaptation are M1's exclusive responsibility.
  A4 — Cyclopts 4.18.0+ calls asyncio.run() for async def command functions when
        no event loop is running; inside a running loop, use app.run_async().
  A5 — Global registry state is process-scoped; no cross-process sharing.
  A6 — Python >= 3.11 (asyncio.get_running_loop() is the stable API).
  A7 — Test environments call cisternal.clear_registry() in teardown to prevent
        cross-test registry contamination.

HARD INVARIANT (C5/AC-M2-6):
  The M2 wire-time MCP callable is a PURE PASSTHROUGH — it MUST NOT call any
  adapter.emit_* or adapter.shape_* methods, or emit ANY telemetry. All
  telemetry and shaping is exclusively owned by M1 CisternalMiddleware.
"""

from pathlib import Path
from typing import Any

from cisternal.telemetry import (
    init_pipeline,
    get_pipeline,
    span,
    aspan,
    job_span,
    status,
    ExporterBase,
    _build_record,
)
from cisternal.registration.cli_contract import (
    CliContext,
    CliContract,
    CliOption,
    cli_command,
    cli_group,
    default_report,
    exit_code_attr,
    json_option,
)
from cisternal.registration.decorator import tool
from cisternal.registration.errors import CisternalWireError
from cisternal.registration.registry import clear_registry

# M3 (assets export)
from cisternal.assets.spec import AssetSpec
from cisternal.assets.bundle import AssetBundle
from cisternal.assets.source import registry_assets
from cisternal.export.base import Emitter
from cisternal.export.claude import ClaudeEmitter
from cisternal.export.write import write_bundle


def init(
    log_dir: str | Path | None = None,
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
    exporters: list[ExporterBase] | None = None,
    heartbeat_interval: float = 30.0,
    level: int | str | None = None,
) -> None:
    """Initialize the telemetry pipeline (idempotent).

    Args:
        log_dir: Directory for JSONL logs. If None, resolves via env vars or defaults to ~/.cisternal/logs.
        max_bytes: Max file size before rotation (default 10 MB).
        backup_count: Number of backup files to keep.
        exporters: Custom exporters. If None, uses JsonlExporter with log_dir.
        heartbeat_interval: Seconds between liveness heartbeat probes (default 30s).
        level: Minimum severity for events sent through ``emit_event`` (int,
            level name like ``"WARNING"``, or digit string). Resolution:
            explicit arg > ``CISTERNAL_LOG_LEVEL`` > None (no filtering). An
            unrecognized value warns on stderr and disables filtering. Unlike
            the other arguments, an explicit ``level`` also applies when the
            pipeline already exists; ``init()`` without one never changes it.
            Spans (``span``/``aspan``/``job_span``) and heartbeats are never
            filtered.
    """
    init_pipeline(
        log_dir=Path(log_dir) if log_dir is not None else None,
        max_bytes=max_bytes,
        backup_count=backup_count,
        exporters=exporters,
        heartbeat_interval=heartbeat_interval,
        level=level,
    )


def emit_event(name: str, *, level: int | str | None = None, **fields: Any) -> None:
    """Emit a telemetry event with optional level filtering.

    Snapshots contextvars on this thread, builds a Record, and enqueues
    it for non-blocking export. Never raises.

    Args:
        name: Event name (e.g. 'mcp.call_start').
        level: Severity of this event (int or level name; keyword-only, so
            ``level`` is a reserved name, not a field). Stored as
            ``Record.severity``; dropped if below the ``init(level=)``
            threshold. Unrecognized values count as INFO. Defaults to INFO.
        **fields: Event fields (e.g. tool='foo', request_id='xyz').
    """
    import logging
    import dataclasses
    import sys
    import time

    try:
        pipeline = get_pipeline()
        if pipeline is None:
            return

        from cisternal.telemetry.pipeline import _normalize_level

        # Invalid/unknown levels are treated as INFO (never raise).
        severity = _normalize_level(level)
        if severity is None:
            severity = logging.INFO

        # Check if event passes the configured minimum level threshold
        min_level = getattr(pipeline, "min_level", None)
        if min_level is not None and severity < min_level:
            # Event below threshold; drop it
            return

        # Severity is attached after the build, never passed through **fields,
        # so a caller field named "severity" stays an ordinary field.
        record = _build_record(name, ts=time.time(), **fields)
        if record is None:
            return
        if severity != record.severity:
            record = dataclasses.replace(record, severity=severity)
        pipeline.emit(record)
    except Exception as e:
        # Never-raise contract: telemetry must not break the caller.
        print(f"[cisternal] emit_event({name!r}) failed: {e}", file=sys.stderr)


def _lazy_import(name: str) -> object:
    """Lazy re-export for wire and WiredRegistry to defer fastmcp import."""
    if name == "wire":
        from cisternal.registration.wired import wire as _wire
        return _wire
    if name == "WiredRegistry":
        from cisternal.registration.wired import WiredRegistry as _WiredRegistry
        return _WiredRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str) -> object:
    return _lazy_import(name)


def __dir__() -> list[str]:
    # wire/WiredRegistry resolve via __getattr__ (deferred fastmcp import,
    # above) rather than being bound in the module's own __dict__, so the
    # default dir(module) -- which only reflects real __dict__ entries, not
    # __all__ -- silently omits them (issue #18). Explicit __dir__ so
    # "wire" in dir(cisternal) is True, matching __all__.
    return sorted(set(globals()) | set(__all__))


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
    "CisternalWireError",
    "clear_registry",
    # M2 — wire() CLI contract (fastmcp-free; imported eagerly, spec 4 / R10)
    "CliContract",
    "CliOption",
    "CliContext",
    "json_option",
    "default_report",
    "exit_code_attr",
    "cli_command",
    "cli_group",
    # M3 (assets export)
    "AssetSpec",
    "AssetBundle",
    "registry_assets",
    "Emitter",
    "ClaudeEmitter",
    "write_bundle",
]
