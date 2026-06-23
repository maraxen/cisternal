"""span() and aspan(): Context managers for timing and tracing (re-raise on error).

Generic timing primitives that emit <name>.start and <name>.end events.
On caller exception: record status=ERROR, exc_type, exc_msg, then RE-RAISE.
Mirrors bathos.telemetry.span behavior (CH-5).
"""

from contextlib import asynccontextmanager, contextmanager
import time
import uuid
from typing import Any, AsyncIterator, Iterator

from .pipeline import get_pipeline
from .context import _build_record


@contextmanager
def span(name: str, **fields: Any) -> Iterator[None]:
    """Sync context manager for timing with span emission and error recording.

    Emits <name>.start on entry, <name>.end on exit.
    On exception: records status=ERROR and re-raises (intentional).

    Args:
        name: Span name (e.g. 'process.file').
        **fields: Additional fields to include in both start and end events.

    Yields:
        None.

    Raises:
        Any exception raised in the block (re-raised after recording).

    Example:
        >>> with span("process.item", item_id="123"):
        ...     do_work()
        # Emits: process.item.start (span_id, item_id)
        #        process.item.end (span_id, item_id, duration_ms, ok=True)
    """
    pipeline = get_pipeline()
    if pipeline is None:
        # Pipeline not initialized; just yield without telemetry
        yield
        return

    span_id = uuid.uuid4().hex
    t0 = time.monotonic_ns()

    # Emit start event
    record = _build_record(
        f"{name}.start",
        span_id=span_id,
        **fields,
    )
    if record is not None:
        pipeline.emit(record)

    try:
        yield
        # Normal completion
        duration_ms = (time.monotonic_ns() - t0) / 1e6
        record = _build_record(
            f"{name}.end",
            span_id=span_id,
            duration_ms=duration_ms,
            ok=True,
            **fields,
        )
        if record is not None:
            pipeline.emit(record)
    except Exception as exc:
        # Record error and re-raise
        duration_ms = (time.monotonic_ns() - t0) / 1e6
        record = _build_record(
            f"{name}.end",
            span_id=span_id,
            duration_ms=duration_ms,
            ok=False,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
            **fields,
        )
        if record is not None:
            pipeline.emit(record)
        # Intentional re-raise (C5): span is a timing primitive, not a shield
        raise


@contextmanager
def job_span(name: str, **fields: Any) -> Iterator[None]:
    """HPC/SLURM job span — sets task_id/run_uuid from env then delegates to span().

    Reads ``MYX_JOB_ID`` or ``BTH_TASK_ID`` for task_id, and ``MYX_RUN_UUID`` or
    ``BTH_RUN_UUID`` for run_uuid when not passed explicitly in *fields*.

    Args:
        name: Span name (e.g. ``slurm.submit``).
        **fields: Extra fields forwarded to start/end events.

    Yields:
        None.
    """
    import os

    from .context import run_uuid_var, task_id_var

    span_fields = dict(fields)
    tokens: list[tuple[Any, Any]] = []

    task_id = span_fields.get("task_id") or os.environ.get("MYX_JOB_ID") or os.environ.get(
        "BTH_TASK_ID"
    )
    if task_id:
        span_fields.setdefault("task_id", task_id)
        tokens.append((task_id_var, task_id_var.set(str(task_id))))

    run_uuid = span_fields.get("run_uuid") or os.environ.get("MYX_RUN_UUID") or os.environ.get(
        "BTH_RUN_UUID"
    )
    if run_uuid:
        span_fields.setdefault("run_uuid", run_uuid)
        tokens.append((run_uuid_var, run_uuid_var.set(str(run_uuid))))

    try:
        with span(name, **span_fields):
            yield
    finally:
        for var, token in reversed(tokens):
            try:
                var.reset(token)
            except ValueError:
                pass


@asynccontextmanager
async def aspan(name: str, **fields: Any) -> AsyncIterator[None]:
    """Async context manager for timing with span emission and error recording.

    Emits <name>.start on entry, <name>.end on exit.
    On exception: records status=ERROR and re-raises (intentional).

    Args:
        name: Span name (e.g. 'async.fetch').
        **fields: Additional fields to include in both start and end events.

    Yields:
        None.

    Raises:
        Any exception raised in the block (re-raised after recording).

    Example:
        >>> async with aspan("fetch.data", url="https://..."):
        ...     data = await client.get(url)
        # Emits: fetch.data.start (span_id, url)
        #        fetch.data.end (span_id, url, duration_ms, ok=True)
    """
    pipeline = get_pipeline()
    if pipeline is None:
        # Pipeline not initialized; just yield without telemetry
        yield
        return

    span_id = uuid.uuid4().hex
    t0 = time.monotonic_ns()

    # Emit start event
    record = _build_record(
        f"{name}.start",
        span_id=span_id,
        **fields,
    )
    if record is not None:
        pipeline.emit(record)

    try:
        yield
        # Normal completion
        duration_ms = (time.monotonic_ns() - t0) / 1e6
        record = _build_record(
            f"{name}.end",
            span_id=span_id,
            duration_ms=duration_ms,
            ok=True,
            **fields,
        )
        if record is not None:
            pipeline.emit(record)
    except Exception as exc:
        # Record error and re-raise
        duration_ms = (time.monotonic_ns() - t0) / 1e6
        record = _build_record(
            f"{name}.end",
            span_id=span_id,
            duration_ms=duration_ms,
            ok=False,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
            **fields,
        )
        if record is not None:
            pipeline.emit(record)
        # Intentional re-raise (C5): span is a timing primitive, not a shield
        raise
