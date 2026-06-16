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
