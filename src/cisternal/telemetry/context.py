"""Context: ContextVar definitions and record-building (CH-4).

Owns all ContextVar objects. _build_record() snapshots context values
on the PRODUCER thread (the thread calling emit_event), not on the
consumer (QueueListener) thread.

This ensures contextvars are captured at the source, before enqueue,
eliminating races where the consumer thread's context might be different.
"""

from contextvars import ContextVar
import time
import sys

from .record import Record


# ContextVar definitions per spec §3.1
run_uuid_var: ContextVar[str | None] = ContextVar("cisternal.run_uuid", default=None)
mcp_request_id_var: ContextVar[str | None] = ContextVar(
    "cisternal.mcp_request_id", default=None
)
task_id_var: ContextVar[str | None] = ContextVar("cisternal.task_id", default=None)
request_id_var: ContextVar[str | None] = ContextVar("cisternal.request_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("cisternal.session_id", default=None)
phase_var: ContextVar[str | None] = ContextVar("cisternal.phase", default=None)


def _build_record(name: str, ts: float | None = None, **fields) -> Record | None:
    """Build a Record by snapshotting contextvars on the PRODUCER thread.

    Args:
        name: Event name (e.g. 'mcp.call_start').
        ts: Unix timestamp. If None, uses time.time(). If provided, should be set
            by the caller (e.g. when calling this from emit_event, ts is already captured).
        **fields: Caller-supplied event fields.

    Returns:
        Record with all contextvars snapshotted, or None if build failed.
        Never raises (C4, C5): wrapped in try/except to handle non-serializable
        nested fields gracefully.

    Contract (CH-4):
        - Runs on the producer thread (the thread calling emit_event).
        - Snapshots all ContextVar values once.
        - Exporter thread never reads contextvars; it only serializes the Record.
    """
    try:
        if ts is None:
            ts = time.time()

        # Snapshot all contextvars on this thread
        return Record(
            name=name,
            ts=ts,
            run_uuid=run_uuid_var.get(),
            mcp_request_id=mcp_request_id_var.get(),
            task_id=task_id_var.get(),
            request_id=request_id_var.get(),
            session_id=session_id_var.get(),
            phase=phase_var.get(),
            fields=fields,
        )
    except Exception as e:
        # EC-2: Never-raise; if anything fails during record construction,
        # (e.g. if fields contains non-serializable nested **kwargs),
        # log and return a degraded record or None.
        print(f"[cisternal] Error building record: {e}", file=sys.stderr)
        return None
