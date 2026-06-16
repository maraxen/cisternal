"""Self-observability: StatusReport and liveness probe (CH-12, CH-11).

Provides consumer-side evidence of pipeline health via heartbeat/write-probe.
CH-12: heartbeat_alive/write_probe_ok determined by consumer-side evidence:
  - Record JsonlExporter output file mtime+size at each heartbeat enqueue.
  - On next heartbeat, re-stat. If both advanced, both flags True.
  - If neither advances within 2x interval, dead QueueListener detected (EC-3).
"""
from dataclasses import dataclass
import os
import threading
import time
from pathlib import Path

from .pipeline import get_pipeline


# Global state for heartbeat thread and liveness tracking
_heartbeat_thread = None
_heartbeat_lock = threading.Lock()
_heartbeat_interval = 0.05  # 50ms default, same as tests
_last_stat = {"mtime": None, "size": None, "ts": None, "last_growth_ts": None}
_jsonl_path = None


@dataclass
class StatusReport:
    """Health status of the telemetry pipeline.

    Fields document both producer-side (events_emitted) and consumer-side
    (pipeline_alive, heartbeat_alive via write-probe) evidence.
    """

    pipeline_alive: bool
    """QueueListener thread is_alive()."""

    queue_depth: int
    """Current number of records waiting in the queue."""

    events_emitted: int
    """Total records put_nowait (producer counter)."""

    events_exported: int
    """Total records exported by exporters (consumer counter)."""

    drop_count: int
    """Records dropped due to queue full (put_nowait exceeded capacity)."""

    heartbeat_alive: bool
    """(CH-12) Consumer-side liveness: last heartbeat caused output file to grow."""

    write_probe_ok: bool
    """(CH-12) Last heartbeat write probe succeeded (file mtime/size advanced)."""


def _heartbeat_daemon(interval: float) -> None:
    """Emit periodic heartbeat events and track file liveness (CH-12).

    Runs as a daemon thread started by init_pipeline().
    Every interval, emits a "heartbeat" event and probes the JSONL output file.

    Args:
        interval: Seconds between heartbeats.
    """
    from .context import _build_record

    while True:
        try:
            time.sleep(interval)
            pipeline = get_pipeline()
            if pipeline is None:
                continue

            # Emit heartbeat event
            record = _build_record("heartbeat")
            if record is not None:
                pipeline.emit(record)

            # Probe the JSONL file for growth (consumer-side evidence)
            _probe_jsonl_file()

        except Exception:
            # Never crash the heartbeat thread
            pass


def _probe_jsonl_file() -> None:
    """Probe the JSONL output file mtime+size to detect consumer-side liveness.

    CH-12: On each heartbeat, stat the file. If both mtime and size advanced
    since last probe, set heartbeat_alive=True and write_probe_ok=True.
    If neither advances for 2x interval, consumer (QueueListener) is dead.
    """
    global _last_stat, _jsonl_path

    if _jsonl_path is None or not _jsonl_path.exists():
        return

    try:
        stat = os.stat(_jsonl_path)
        mtime = stat.st_mtime
        size = stat.st_size
        now = time.time()

        with _heartbeat_lock:
            # First stat case: initialize baseline
            if _last_stat["mtime"] is None:
                _last_stat["mtime"] = mtime
                _last_stat["size"] = size
                _last_stat["ts"] = now
                _last_stat["last_growth_ts"] = now
                return

            # Check if both mtime and size advanced since last stat
            if mtime > _last_stat["mtime"] and size > _last_stat["size"]:
                # File has grown; consumer is alive
                _last_stat["mtime"] = mtime
                _last_stat["size"] = size
                _last_stat["ts"] = now
                _last_stat["last_growth_ts"] = now
            else:
                # No growth in this probe; just update the probe timestamp
                _last_stat["ts"] = now

    except Exception:
        pass


def _start_heartbeat(interval: float, jsonl_path: Path | None) -> None:
    """Start the heartbeat daemon thread (called by init_pipeline).

    Args:
        interval: Seconds between heartbeats.
        jsonl_path: Path to the JSONL output file for liveness probing.
    """
    global _heartbeat_thread, _jsonl_path, _heartbeat_interval

    with _heartbeat_lock:
        if _heartbeat_thread is None:
            _jsonl_path = jsonl_path
            _heartbeat_interval = interval
            _heartbeat_thread = threading.Thread(
                target=_heartbeat_daemon, args=(interval,), daemon=True
            )
            _heartbeat_thread.start()


def status() -> StatusReport:
    """Return current pipeline status with consumer-side liveness evidence.

    CH-12: heartbeat_alive and write_probe_ok are set based on whether the
    JSONL output file has grown since the last heartbeat. This provides
    consumer-side evidence of a live QueueListener.

    The flags are True if file growth occurred within 2x the heartbeat interval.
    If no growth occurs within that window, the QueueListener is presumed dead (EC-3).

    Returns:
        StatusReport with current pipeline health.
    """
    pipeline = get_pipeline()

    if pipeline is None:
        return StatusReport(
            pipeline_alive=False,
            queue_depth=0,
            events_emitted=0,
            events_exported=0,
            drop_count=0,
            heartbeat_alive=False,
            write_probe_ok=False,
        )

    # Check consumer-side liveness: has the file grown recently?
    heartbeat_alive = False
    write_probe_ok = False

    with _heartbeat_lock:
        if _last_stat["last_growth_ts"] is not None:
            # File has grown at least once
            now = time.time()
            time_since_last_growth = now - _last_stat["last_growth_ts"]

            # If file has grown recently (within 2x interval), it's alive
            if time_since_last_growth < (2 * _heartbeat_interval):
                heartbeat_alive = True
                write_probe_ok = True

    return StatusReport(
        pipeline_alive=pipeline.is_alive(),
        queue_depth=pipeline.queue_depth,
        events_emitted=pipeline.events_emitted,
        events_exported=pipeline.events_exported,
        drop_count=pipeline.drop_count,
        heartbeat_alive=heartbeat_alive,
        write_probe_ok=write_probe_ok,
    )
