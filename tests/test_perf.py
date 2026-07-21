"""Performance benchmarks: AC-PERF-1a, AC-PERF-1b, AC-PERF-1c (spec §8).

AC-PERF-1a: emit_event x1000 with 2 exporters; median per-call < 1ms (enqueue only).
AC-PERF-1b: CisternalMiddleware x500; median overhead < 1ms.
AC-PERF-1c: queue capacity 10, 100 events before drain; drop_count >= 90.
"""

import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from cisternal import emit_event, init
from cisternal.adapters.v3_middleware import CisternalMiddleware
from cisternal.telemetry.context import _build_record
from cisternal.telemetry.exporter import ShadowExporter
from cisternal.telemetry.pipeline import EventPipeline


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for JSONL logs."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up pipeline between tests."""
    yield
    from cisternal.telemetry import pipeline as pm
    import cisternal.telemetry.self_obs as so_mod

    if pm._global_pipeline:
        pm._global_pipeline.shutdown()
        pm._global_pipeline = None

    with so_mod._heartbeat_lock:
        so_mod._heartbeat_thread = None
        so_mod._last_stat = {
            "mtime": None,
            "size": None,
            "ts": None,
            "last_growth_ts": None,
        }
        so_mod._jsonl_path = None
    so_mod._last_ec3_warn = 0.0


class TestAcPerf1a:
    """AC-PERF-1a: emit_event x1000 with 2 exporters; median per-call < 1ms."""

    def test_emit_event_median_under_1ms(self, temp_log_dir):
        """Given 2 ShadowExporters (no disk I/O);
        When emit_event called 1000 times;
        Then median per-call latency < 1ms (pure enqueue path)."""

        shadow1, shadow2 = ShadowExporter(), ShadowExporter()
        # Use ShadowExporters only — pure enqueue path, no disk I/O
        init(log_dir=temp_log_dir, exporters=[shadow1, shadow2], heartbeat_interval=30.0)

        durations_ns: list[int] = []
        for _ in range(1000):
            t0 = time.perf_counter_ns()
            emit_event("mcp.call_start", tool="bench", request_id="r")
            durations_ns.append(time.perf_counter_ns() - t0)

        median_ms = statistics.median(durations_ns) / 1_000_000
        assert median_ms < 1.0, (
            f"Median emit_event {median_ms:.4f}ms >= 1ms threshold (AC-PERF-1a)"
        )


class TestAcPerf1b:
    """AC-PERF-1b: CisternalMiddleware on_call_tool x500; median overhead < 1ms."""

    @pytest.mark.asyncio
    async def test_middleware_overhead_median_under_1ms(self, temp_log_dir):
        """Given CisternalMiddleware with ShadowExporter;
        When on_call_tool awaited 500 times (mock call_next returns immediately);
        Then median overhead < 1ms."""

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        middleware = CisternalMiddleware()
        ctx = Mock()
        ctx.message = Mock()
        ctx.message.name = "bench_tool"
        ctx.message.arguments = {}

        async def call_next(_):
            return {}

        durations_ns: list[int] = []
        for _ in range(500):
            t0 = time.perf_counter_ns()
            await middleware.on_call_tool(ctx, call_next)
            durations_ns.append(time.perf_counter_ns() - t0)

        median_ms = statistics.median(durations_ns) / 1_000_000
        assert median_ms < 1.0, (
            f"Median middleware overhead {median_ms:.4f}ms >= 1ms threshold (AC-PERF-1b)"
        )


class TestAcPerf1c:
    """AC-PERF-1c: queue capacity 10, 100 events before drain; drop_count >= 90."""

    def test_drop_on_full_no_exception(self):
        """Given EventPipeline with queue_size=10, one ShadowExporter;
        When 100 events emitted rapidly before consumer drains;
        Then drop_count >= 90 and no exception raised."""

        shadow = ShadowExporter()
        pipeline = EventPipeline(queue_size=10, exporters=[shadow])

        # Build a minimal record for raw pipeline emit
        record = _build_record("mcp.call_start", ts=time.time(), tool="t", request_id="r")

        # Rapid-fire 100 emits into the tiny queue before consumer can drain
        for _ in range(100):
            pipeline.emit(record)

        # Wait briefly for consumer to process what it can
        time.sleep(0.1)

        assert pipeline.drop_count >= 90, (
            f"drop_count={pipeline.drop_count} < 90; queue may have drained too fast "
            "(AC-PERF-1c: expected >= 90 drops with queue_size=10 and 100 rapid emits)"
        )

        pipeline.shutdown()
