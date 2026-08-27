"""Context: ContextVar definitions and record-building (CH-4).

Owns all ContextVar objects. _build_record() snapshots context values
on the PRODUCER thread (the thread calling emit_event), not on the
consumer (QueueListener) thread.

This ensures contextvars are captured at the source, before enqueue,
eliminating races where the consumer thread's context might be different.
"""

from contextvars import ContextVar
import threading
import time
import sys

from .git_state import GitState
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

# Git provenance (spec 260827): deliberately NOT a ContextVar. ContextVars are
# thread/task-local by design (that's exactly right for task_id_var/
# request_id_var above, which must stay isolated per concurrent request) --
# but git state is a process-global constant captured once at init() time in
# a background thread, and needs to be visible from EVERY thread/task that
# later calls emit_event(), not just the one that happened to call init().
# A ContextVar.set() in init()'s thread would silently not propagate to any
# other thread's context, making git fields None everywhere except whichever
# thread happened to call init() -- a real bug caught by the multi-threaded
# heartbeat tests during development. Mirrors pipeline.py's _global_pipeline
# pattern (plain global + lock) instead.
_git_state: GitState | None = None
_git_state_lock = threading.Lock()


def get_git_state() -> GitState | None:
    """Return the process-global git state, or None if init() hasn't run yet
    (or the background capture it started hasn't completed yet)."""
    return _git_state


def _set_git_state(state: GitState | None) -> None:
    """Set the process-global git state. Internal -- callers go through
    init_pipeline(), which does the actual capture in a background thread."""
    global _git_state
    with _git_state_lock:
        _git_state = state

# Recovery-telemetry bridge (companion spec 260805_nlm-adapter-recovery-
# telemetry-bridge.md, Spec B AC1). Set by the composed MCP callable's
# recovery branch (cisternal.registration.compose, only when `recovery=` is
# supplied to wire()/compose_mcp_callable) as a cross-boundary signal for
# CisternalMiddleware.on_call_tool to read/emit/clear (Spec B AC2/AC3). A
# plain ContextVar is a signal, not a telemetry *call*, so setting it does
# not violate wire()'s HARD INVARIANT (C5) -- see compose.py's module
# docstring. Payload shape: {tool, outcome, duration_ms, exc, started_at} |
# None -- see compose.py's _set_recovery_context for the producer and
# v3_middleware.py's on_call_tool for the consumer.
_last_recovery_var: ContextVar[dict | None] = ContextVar(
    "cisternal.last_recovery", default=None
)


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
        git_state = get_git_state()
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
            git_hash=git_state.hash if git_state is not None else None,
            git_branch=git_state.branch if git_state is not None else None,
            git_dirty=git_state.dirty if git_state is not None else None,
            git_dirty_content_id=(
                git_state.dirty_content_id if git_state is not None else None
            ),
            git_provenance_source=(
                git_state.provenance_source if git_state is not None else None
            ),
        )
    except Exception as e:
        # EC-2: Never-raise; if anything fails during record construction,
        # (e.g. if fields contains non-serializable nested **kwargs),
        # log and return a degraded record or None.
        print(f"[cisternal] Error building record: {e}", file=sys.stderr)
        return None
