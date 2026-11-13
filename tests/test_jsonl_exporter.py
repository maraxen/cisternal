"""Tests for JsonlExporter: AC-PKG and file rotation."""

import json
import tempfile
import threading
import time
from pathlib import Path

from cisternal.telemetry.exporter import ExporterBase, JsonlExporter
from cisternal.telemetry.pipeline import EventPipeline
from cisternal.telemetry.record import Record


class TestJsonlExporter:
    """Test JsonlExporter file writing and rotation."""

    def test_jsonl_exporter_writes_file(self):
        """Given JsonlExporter; When export(record); Then JSONL line written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            exporter = JsonlExporter(path, max_bytes=10_485_760, backup_count=5)

            record = Record(
                name="test.event",
                ts=time.time(),
                run_uuid=None,
                mcp_request_id=None,
                task_id=None,
                request_id=None,
                session_id=None,
                phase=None,
                fields={"key": "value"},
            )

            exporter.export(record)
            exporter.flush()

            # File should exist
            assert path.exists()

            # Should contain JSON line
            with open(path) as f:
                line = f.readline()
                data = json.loads(line)
                assert data["name"] == "test.event"
                assert data["fields"]["key"] == "value"

    def test_jsonl_exporter_thread_safe(self):
        """Given JsonlExporter; When multiple threads export; Then all records written."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            exporter = JsonlExporter(path, max_bytes=10_485_760, backup_count=5)

            def write_record(i):
                record = Record(
                    name=f"event.{i}",
                    ts=time.time(),
                    run_uuid=None,
                    mcp_request_id=None,
                    task_id=None,
                    request_id=None,
                    session_id=None,
                    phase=None,
                    fields={"index": i},
                )
                exporter.export(record)

            threads = [
                threading.Thread(target=write_record, args=(i,)) for i in range(10)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            exporter.flush()

            # Should have 10 records
            with open(path) as f:
                lines = f.readlines()
                assert len(lines) == 10


class TestJsonlExporterDrops:
    """Test JsonlExporter drop behavior on queue full."""

    def test_drop_on_full_queue(self):
        """Given bounded queue; When capacity exceeded; Then drop_count incremented."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from cisternal.telemetry.pipeline import EventPipeline

            path = Path(tmpdir) / "test.jsonl"
            exporter = JsonlExporter(path, max_bytes=10_485_760, backup_count=5)

            # Create pipeline with very small queue
            pipeline = EventPipeline(queue_size=5, exporters=[exporter])

            # Fill queue beyond capacity
            for i in range(20):
                record = Record(
                    name=f"event.{i}",
                    ts=time.time(),
                    run_uuid=None,
                    mcp_request_id=None,
                    task_id=None,
                    request_id=None,
                    session_id=None,
                    phase=None,
                    fields={},
                )
                pipeline.emit(record)

            pipeline.shutdown()

            # Should have recorded drops on the pipeline
            assert pipeline.drop_count > 0


def _record(name: str, index: int) -> Record:
    return Record(
        name=name,
        ts=time.time(),
        run_uuid=None,
        mcp_request_id=None,
        task_id=None,
        request_id=None,
        session_id=None,
        phase=None,
        fields={"index": index},
    )


class TestShutdownDrainsQueue:
    """shutdown() must export records still queued, and must stay bounded."""

    def test_shutdown_writes_every_record_still_queued(self):
        """Records waiting behind one in-flight export are on disk after shutdown.

        The listener is held inside the first export until the sentinel is
        queued, so the other records are still in the queue when shutdown
        starts. Releasing before the sentinel is queued lets the listener
        drain on its own and would pass even if shutdown dropped the queue.
        """
        n = 50
        entered = threading.Event()
        release = threading.Event()

        class _HoldFirstExport(JsonlExporter):
            def export(self, record: Record) -> None:
                if not entered.is_set():
                    entered.set()
                    assert release.wait(timeout=5)
                super().export(record)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            exporter = _HoldFirstExport(path, max_bytes=10_485_760, backup_count=5)
            pipeline = EventPipeline(queue_size=10_000, exporters=[exporter])
            pipeline.emit(_record("event.0", 0))
            assert entered.wait(timeout=2), "listener never entered export()"
            for i in range(1, n):
                pipeline.emit(_record(f"event.{i}", i))

            def _release_once_shutdown_has_the_sentinel() -> None:
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    # First record is in export(); the rest plus the sentinel
                    # make n items. stop() on the unfixed path runs immediately
                    # after the sentinel is queued, so wait briefly and prefer
                    # releasing only after that fallback has fired.
                    if pipeline._listener._stop_event.is_set():
                        release.set()
                        return
                    if pipeline.queue_depth >= n:
                        time.sleep(0.05)
                        release.set()
                        return
                    time.sleep(0.001)
                release.set()

            releaser = threading.Thread(target=_release_once_shutdown_has_the_sentinel)
            releaser.start()
            try:
                pipeline.shutdown()
            finally:
                release.set()
                releaser.join(timeout=2)

            lines = [line for line in path.read_text().splitlines() if line.strip()]
            names = [json.loads(line)["name"] for line in lines]
            assert names == [f"event.{i}" for i in range(n)]

    def test_shutdown_returns_when_exporter_blocks(self):
        """A blocked export() cannot make shutdown() wait past its timeout."""

        class _StuckExporter(ExporterBase):
            def export(self, record: Record) -> None:
                threading.Event().wait()

        pipeline = EventPipeline(queue_size=10, exporters=[_StuckExporter()])
        pipeline.emit(_record("event.stuck", 0))
        timeout = 0.3
        started = time.monotonic()
        pipeline.shutdown(timeout=timeout)
        elapsed = time.monotonic() - started
        assert elapsed < timeout + 0.5, (
            f"shutdown() took {elapsed:.3f}s, timeout was {timeout}s"
        )
