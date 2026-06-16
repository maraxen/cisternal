"""Tests for JsonlExporter: AC-PKG and file rotation."""
import json
import tempfile
import time
from pathlib import Path

from cisterna.telemetry.exporter import JsonlExporter
from cisterna.telemetry.record import Record


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

            threads = [threading.Thread(target=write_record, args=(i,)) for i in range(10)]
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
            from cisterna.telemetry.pipeline import EventPipeline

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
