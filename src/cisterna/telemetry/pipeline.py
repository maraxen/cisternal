"""EventPipeline: Fan-out core with bounded queue and per-exporter isolation.

The dual-emit fan-out design (G from the decision record):
1. Build ONE normalized Record once (via _build_record on producer thread).
2. Fan out to N exporters, each isolated by try/except.
3. One exporter raising never crashes the caller or starves others.

Fork prohibition (C9):
    Consumer threads do not survive os.fork().
    Use spawn or forkserver; fork is unsupported.
    Per-pid JSONL naming (events.<host>.<pid>.jsonl) requires spawn.
"""
import queue
import sys
import threading
from pathlib import Path

from .exporter import ExporterBase, JsonlExporter
from .record import Record


# Global pipeline instance for init()/emit_event()
_global_pipeline = None
_pipeline_lock = threading.Lock()


class _QueueListenerThread(threading.Thread):
    """Custom consumer thread for the bounded queue.

    Dequeues Records and fan-outs to each exporter in isolation.
    One exporter raising never affects the caller or other exporters.
    """

    def __init__(self, q: queue.Queue, exporters: list[ExporterBase]) -> None:
        """Initialize the consumer thread.

        Args:
            q: The bounded queue.
            exporters: List of exporters to fan-out to.
        """
        super().__init__(daemon=True)
        self._queue = q
        self._exporters = exporters
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Main loop: dequeue Records and fan-out to exporters."""
        while not self._stop_event.is_set():
            try:
                # Wait for a record with timeout
                record = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if record is None:
                # Sentinel for shutdown
                break

            # Fan-out to each exporter in isolation
            for exporter in self._exporters:
                try:
                    exporter.export(record)
                except Exception as e:
                    # Never raise; log and continue to next exporter
                    print(
                        f"[cisterna] Exporter {type(exporter).__name__} raised: {e}",
                        file=sys.stderr,
                    )

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()


class EventPipeline:
    """Non-blocking event pipeline with bounded queue and per-exporter isolation.

    Fan-out core (design G):
    - Enqueue a Record (put_nowait; drop if full).
    - Consumer thread dequeues and calls each exporter in isolation.
    - One exporter raising is caught; others still run.
    """

    def __init__(
        self,
        queue_size: int = 10000,
        exporters: list[ExporterBase] | None = None,
    ) -> None:
        """Initialize the event pipeline.

        Args:
            queue_size: Size of the bounded queue. Exceeded → drop.
            exporters: List of ExporterBase instances. If None, uses JsonlExporter
                       with default args (should be overridden; included for tests).
        """
        self._queue: queue.Queue[Record | None] = queue.Queue(maxsize=queue_size)
        self._queue_size = queue_size
        self._exporters = exporters or []
        self._drop_count = 0
        self._events_emitted = 0
        self._events_exported = 0

        # Start custom consumer thread
        self._listener = _QueueListenerThread(self._queue, self._exporters)
        self._listener.start()

        self._shutdown = False

    def emit(self, record: Record) -> None:
        """Enqueue a Record for export (non-blocking, put_nowait).

        If queue is full, drop silently and increment drop counter.
        Never blocks the caller (off hot path).

        Args:
            record: Record to emit.
        """
        if self._shutdown:
            return

        try:
            self._queue.put_nowait(record)
            self._events_emitted += 1
        except queue.Full:
            # Queue full → drop on full (never block caller)
            self._drop_count += 1

    def shutdown(self, timeout: float = 2.0) -> None:
        """Flush and shutdown the pipeline gracefully.

        Args:
            timeout: Max time to wait for listener thread to drain.
        """
        if self._shutdown:
            return

        self._shutdown = True

        # Signal listener to stop after draining
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            pass

        # Flush exporters
        for exporter in self._exporters:
            try:
                exporter.flush()
            except Exception as e:
                print(
                    f"[cisterna] Exporter.flush() failed: {e}",
                    file=sys.stderr,
                )

        # Stop listener thread
        try:
            self._listener.stop()
            self._listener.join(timeout=timeout)
        except Exception as e:
            print(
                f"[cisterna] Listener thread shutdown failed: {e}",
                file=sys.stderr,
            )

        # Close exporters
        for exporter in self._exporters:
            try:
                exporter.close()
            except Exception as e:
                print(
                    f"[cisterna] Exporter.close() failed: {e}",
                    file=sys.stderr,
                )

    def is_alive(self) -> bool:
        """Check if consumer thread is alive."""
        return self._listener.is_alive() if self._listener else False

    @property
    def drop_count(self) -> int:
        """Number of events dropped due to queue full."""
        return self._drop_count

    @property
    def queue_depth(self) -> int:
        """Current depth of the queue."""
        return self._queue.qsize()

    @property
    def events_emitted(self) -> int:
        """Total events emitted (enqueued)."""
        return self._events_emitted

    @property
    def events_exported(self) -> int:
        """Total events exported by exporters."""
        return self._events_exported


def init_pipeline(
    log_dir: Path | None = None,
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
    exporters: list[ExporterBase] | None = None,
) -> EventPipeline:
    """Initialize or return the global EventPipeline (idempotent init, AC-CORE-5).

    If the pipeline is already initialized, return the existing instance.
    Otherwise, create a new one with the given parameters.

    Args:
        log_dir: Directory for JSONL logs. If None and no exporters, uses /tmp.
        max_bytes: Max file size before rotation.
        backup_count: Backup files to keep.
        exporters: Custom exporters. If None, uses JsonlExporter with log_dir.

    Returns:
        The global EventPipeline instance.
    """
    global _global_pipeline

    with _pipeline_lock:
        if _global_pipeline is not None:
            # Already initialized; return existing
            return _global_pipeline

        # Initialize exporter list (copy to avoid mutating caller's list)
        exporters = list(exporters) if exporters is not None else []

        # If log_dir is provided (or default), add JsonlExporter
        if log_dir is None:
            log_dir = Path("/tmp")
        else:
            log_dir = Path(log_dir)

        # Always add JSONL exporter with per-pid naming (requires spawn, per C9)
        import os
        import socket
        hostname = socket.gethostname()
        pid = os.getpid()
        jsonl_path = log_dir / f"events.{hostname}.{pid}.jsonl"
        exporters.append(
            JsonlExporter(jsonl_path, max_bytes=max_bytes, backup_count=backup_count)
        )

        _global_pipeline = EventPipeline(exporters=exporters)
        return _global_pipeline


def get_pipeline() -> EventPipeline | None:
    """Get the global pipeline (may be None if not initialized)."""
    global _global_pipeline
    return _global_pipeline


def shutdown_pipeline() -> None:
    """Shutdown the global pipeline."""
    global _global_pipeline
    with _pipeline_lock:
        if _global_pipeline is not None:
            _global_pipeline.shutdown()
            _global_pipeline = None
