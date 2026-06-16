"""Tests for cisterna core: AC-CORE acceptance criteria."""
import asyncio
import json
import tempfile
import time
from pathlib import Path

import pytest

from cisterna import emit_event, init, span, aspan, status
from cisterna.telemetry.context import run_uuid_var
from cisterna.telemetry.exporter import ShadowExporter


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for JSONL logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def cleanup_pipeline():
    """Clean up pipeline between tests."""
    yield
    # Shutdown any existing pipeline
    from cisterna.telemetry import pipeline as pipeline_module
    from cisterna.telemetry import self_obs as self_obs_module

    if pipeline_module._global_pipeline is not None:
        pipeline_module._global_pipeline.shutdown()
        pipeline_module._global_pipeline = None

    # Reset heartbeat state
    with self_obs_module._heartbeat_lock:
        self_obs_module._heartbeat_thread = None
        self_obs_module._last_stat = {"mtime": None, "size": None, "ts": None, "last_growth_ts": None}
        self_obs_module._jsonl_path = None


class TestACCore1:
    """AC-CORE-1: emit_event writes JSONL within 100ms."""

    def test_emit_event_writes_jsonl(self, temp_log_dir):
        """Given init() with temp log dir; When emit_event("mcp.call_start"); Then JSONL appears within 100ms."""
        init(log_dir=temp_log_dir)

        t0 = time.time()
        emit_event("mcp.call_start", tool="test_tool", request_id="req-1")

        # Allow time for async queue processing
        time.sleep(0.05)

        elapsed = time.time() - t0
        assert elapsed < 0.1, f"emit_event took {elapsed}s, should be <0.1s"

        # Find the JSONL file
        jsonl_files = list(temp_log_dir.glob("events.*.*.jsonl"))
        assert len(jsonl_files) > 0, f"No JSONL files found in {temp_log_dir}"

        # Read and verify the record (skip heartbeat events)
        with open(jsonl_files[0]) as f:
            lines = f.readlines()

        assert len(lines) > 0, "JSONL file is empty"
        # Find the mcp.call_start record (skip heartbeats which may also be written)
        mcp_record = None
        for line in lines:
            record = json.loads(line)
            if record["name"] == "mcp.call_start":
                mcp_record = record
                break

        assert mcp_record is not None, f"mcp.call_start record not found in {[json.loads(line)['name'] for line in lines]}"
        assert mcp_record["fields"]["tool"] == "test_tool"
        assert mcp_record["fields"]["request_id"] == "req-1"


class TestACCore2:
    """AC-CORE-2: Two exporters both receive the same record."""

    def test_multiple_exporters(self, temp_log_dir):
        """Given JsonlExporter + ShadowExporter; When emit_event; Then both receive the record."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        emit_event("mcp.call_start", tool="multi_tool", request_id="req-2")
        time.sleep(0.05)

        # Check ShadowExporter (filter out heartbeats)
        mcp_records = [r for r in shadow.records if r.name == "mcp.call_start"]
        assert len(mcp_records) >= 1, f"Expected mcp.call_start in {[r.name for r in shadow.records]}"
        record = mcp_records[0]
        assert record.name == "mcp.call_start"
        assert record.fields["tool"] == "multi_tool"

        # Check JSONL file
        jsonl_files = list(temp_log_dir.glob("events.*.*.jsonl"))
        assert len(jsonl_files) > 0
        with open(jsonl_files[0]) as f:
            lines = f.readlines()
        assert len(lines) >= 1

        # Find the mcp.call_start record
        jsonl_record = None
        for line in lines:
            record = json.loads(line)
            if record["name"] == "mcp.call_start":
                jsonl_record = record
                break
        assert jsonl_record is not None


class TestACCore3:
    """AC-CORE-3: ContextVars snapshot round-trip."""

    def test_contextvar_snapshot(self, temp_log_dir):
        """Given run_uuid_var.set("uuid-x"); When emit_event; Then record contains uuid-x."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        token = run_uuid_var.set("uuid-x")
        try:
            emit_event("test.event")
            time.sleep(0.05)

            # Find the test.event record (filter out heartbeats)
            test_records = [r for r in shadow.records if r.name == "test.event"]
            assert len(test_records) >= 1, f"Expected test.event in {[r.name for r in shadow.records]}"
            record = test_records[0]
            assert record.run_uuid == "uuid-x"
        finally:
            run_uuid_var.reset(token)


class TestACCore4:
    """AC-CORE-4: Async task isolation of contextvars."""

    @pytest.mark.asyncio
    async def test_async_context_isolation(self, temp_log_dir):
        """Given async tasks with different run_uuid; Then each emits its own value."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        async def task_x():
            token = run_uuid_var.set("uuid-x")
            try:
                emit_event("task.x")
                await asyncio.sleep(0.01)
            finally:
                run_uuid_var.reset(token)

        async def task_y():
            token = run_uuid_var.set("uuid-y")
            try:
                await asyncio.sleep(0.005)
                emit_event("task.y")
            finally:
                run_uuid_var.reset(token)

        await asyncio.gather(task_x(), task_y())
        time.sleep(0.05)

        # Filter out heartbeat events
        task_records = [r for r in shadow.records if r.name.startswith("task.")]
        assert len(task_records) == 2, f"Expected 2 task records, got {[r.name for r in shadow.records]}"
        by_name = {r.name: r for r in task_records}
        assert by_name["task.x"].run_uuid == "uuid-x"
        assert by_name["task.y"].run_uuid == "uuid-y"


class TestACCore5:
    """AC-CORE-5: Idempotent init."""

    def test_idempotent_init(self, temp_log_dir):
        """Given init() called twice; When status(); Then exactly one QueueListener thread."""
        from cisterna.telemetry import pipeline as pipeline_module

        init(log_dir=temp_log_dir)
        first_pipeline = pipeline_module._global_pipeline

        # Call init again
        init(log_dir=temp_log_dir)
        second_pipeline = pipeline_module._global_pipeline

        # Should be same pipeline instance
        assert first_pipeline is second_pipeline

        # Check pipeline is alive
        st = status()
        assert st.pipeline_alive


class TestSpanContextManager:
    """Test span() context manager behavior."""

    def test_span_emits_start_and_end(self, temp_log_dir):
        """Given span("test.span"); When it completes; Then start and end events emitted."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        with span("test.span", param1="value1"):
            time.sleep(0.01)

        time.sleep(0.05)

        assert len(shadow.records) >= 2
        names = [r.name for r in shadow.records]
        assert "test.span.start" in names
        assert "test.span.end" in names

        # Check start has span_id
        start_record = [r for r in shadow.records if r.name == "test.span.start"][0]
        assert "span_id" in start_record.fields

        # Check end has duration_ms
        end_record = [r for r in shadow.records if r.name == "test.span.end"][0]
        assert "duration_ms" in end_record.fields
        assert end_record.fields["ok"] is True

    def test_span_reraises_exception(self, temp_log_dir):
        """Given span() with exception; When exception raised; Then span re-raises it."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        with pytest.raises(ValueError, match="test error"):
            with span("test.error"):
                raise ValueError("test error")

        time.sleep(0.05)

        # Check error event was emitted
        records = shadow.records
        end_records = [r for r in records if r.name == "test.error.end"]
        assert len(end_records) >= 1
        assert end_records[0].fields["ok"] is False
        assert end_records[0].fields["exc_type"] == "ValueError"


class TestAsyncSpan:
    """Test aspan() async context manager behavior."""

    @pytest.mark.asyncio
    async def test_aspan_emits_start_and_end(self, temp_log_dir):
        """Given aspan("async.span"); When it completes; Then start and end events emitted."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        async with aspan("async.span", param="value"):
            await asyncio.sleep(0.01)

        await asyncio.sleep(0.05)

        assert len(shadow.records) >= 2
        names = [r.name for r in shadow.records]
        assert "async.span.start" in names
        assert "async.span.end" in names

    @pytest.mark.asyncio
    async def test_aspan_reraises_exception(self, temp_log_dir):
        """Given aspan() with exception; When exception raised; Then aspan re-raises it."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        with pytest.raises(RuntimeError, match="async error"):
            async with aspan("async.error"):
                raise RuntimeError("async error")

        await asyncio.sleep(0.05)

        # Check error event was emitted
        records = shadow.records
        end_records = [r for r in records if r.name == "async.error.end"]
        assert len(end_records) >= 1
        assert end_records[0].fields["ok"] is False


class TestNeverRaise:
    """Test never-raise contract: exporters that raise don't crash the caller."""

    def test_raising_exporter_swallowed(self, temp_log_dir):
        """Given a raising exporter; When emit_event; Then no exception propagates to caller."""

        class RaisingExporter:
            def export(self, record):
                raise RuntimeError("exporter failed")

            def flush(self):
                pass

            def close(self):
                pass

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[RaisingExporter(), shadow])

        # Should not raise despite RaisingExporter raising
        emit_event("test.event", field="value")
        time.sleep(0.05)

        # Shadow exporter should still have received it
        assert len(shadow.records) >= 1
        assert shadow.records[0].name == "test.event"


class TestNonSerializable:
    """Test handling of non-serializable fields."""

    def test_non_serializable_field_dropped_gracefully(self, temp_log_dir):
        """Given non-serializable field; When emit_event; Then no crash, field omitted or record omitted."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        class Unserializable:
            def __repr__(self):
                raise RuntimeError("cannot repr")

        # This should not crash
        emit_event("test.event", serializable="ok", unserializable=Unserializable())
        time.sleep(0.05)

        # Either the record made it to shadow (gracefully handled)
        # or it was silently dropped (never-raise)
        # The contract is: never crash the caller
        # So this test just verifies no exception propagates
