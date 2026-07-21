"""Exporter: ABC and concrete implementations (JsonlExporter, ShadowExporter)."""

from abc import ABC, abstractmethod
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading

from .record import Record


class ExporterBase(ABC):
    """Abstract base class for all exporters (never-raise contract).

    Exporters are called by EventPipeline in isolation per exporter;
    if one raises, it's caught and doesn't affect the caller or other exporters.
    """

    @abstractmethod
    def export(self, record: Record) -> None:
        """Export a single record.

        Must not raise (or raising is caught by caller and logged).
        Thread-safe; called from QueueListener thread.

        Args:
            record: Normalized Record to export.
        """
        pass

    def flush(self) -> None:
        """Flush any buffered data. Subclasses may override.

        Default is no-op. Called by EventPipeline.shutdown().
        """
        pass

    def close(self) -> None:
        """Close/cleanup resources. Subclasses may override.

        Default is no-op. Called by EventPipeline.shutdown().
        """
        pass


class JsonlExporter(ExporterBase):
    """Writes Record objects as JSONL (newline-delimited JSON) with file rotation.

    Thread-safe; serializes to the same RotatingFileHandler.
    Never reads contextvars (CH-4) — all context has already been snapshotted
    into the Record by _build_record() on the producer thread.

    Matches bathos telemetry: queue->RotatingFileHandler->JSONL files.
    Non-blocking design (put_nowait/drop-on-full at the EventPipeline level).
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int = 10_485_760,  # 10 MB
        backup_count: int = 5,
    ) -> None:
        """Initialize JsonlExporter.

        Args:
            path: Path to write JSONL to (e.g. Path('/tmp/events.hostname.pid.jsonl')).
                  RotatingFileHandler will add .1, .2, etc. on rotation.
            max_bytes: Max size before rotation.
            backup_count: Number of backup files to keep.
        """
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._drop_count = 0
        self._lock = threading.Lock()

        # Set up RotatingFileHandler
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handler = RotatingFileHandler(
            str(self._path),
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        # Use a simple JSON format (no timestamp prefix, just the JSON record)
        self._handler.setFormatter(logging.Formatter("%(message)s"))

        # Create a logger just for this exporter
        self._logger = logging.getLogger(f"cisternal.exporter.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.addHandler(self._handler)
        self._logger.propagate = False

    def export(self, record: Record) -> None:
        """Serialize and write a Record as a JSON line.

        Thread-safe. Never raises (or raises are caught by caller).
        """
        try:
            with self._lock:
                # Serialize Record to dict
                data = {
                    "name": record.name,
                    "ts": record.ts,
                    "run_uuid": record.run_uuid,
                    "mcp_request_id": record.mcp_request_id,
                    "task_id": record.task_id,
                    "request_id": record.request_id,
                    "session_id": record.session_id,
                    "phase": record.phase,
                    "fields": record.fields,
                }
                # Log as JSON (RotatingFileHandler will append newline)
                json_str = json.dumps(data, default=str)
                self._logger.info(json_str)
        except Exception as e:
            # Never raise; log to stderr and increment drop count
            print(f"[cisternal] JsonlExporter.export() failed: {e}", file=sys.stderr)
            with self._lock:
                self._drop_count += 1

    def flush(self) -> None:
        """Flush the RotatingFileHandler."""
        try:
            with self._lock:
                self._handler.flush()
        except Exception as e:
            print(f"[cisternal] JsonlExporter.flush() failed: {e}", file=sys.stderr)

    def close(self) -> None:
        """Close the RotatingFileHandler."""
        try:
            with self._lock:
                self._handler.close()
                self._logger.removeHandler(self._handler)
        except Exception as e:
            print(f"[cisternal] JsonlExporter.close() failed: {e}", file=sys.stderr)


class ShadowExporter(ExporterBase):
    """Spy exporter that collects Record objects for testing (AC-SHADOW, AC-CORE-2).

    Collects all exported records into a list for inspection in tests.
    """

    def __init__(self) -> None:
        """Initialize ShadowExporter."""
        self.records: list[Record] = []
        self._lock = threading.Lock()

    def export(self, record: Record) -> None:
        """Append the record to self.records."""
        with self._lock:
            self.records.append(record)
