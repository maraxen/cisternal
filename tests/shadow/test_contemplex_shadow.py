"""AC-SHADOW-2: Contemplex shadow test for parity verification.

Tests that contemplex legacy telemetry and cisternal shadow capture the same
tool invocations with start->end ordering in both streams.

Schema notes:
- logging.info(msg, extra={...}) puts extra dict keys as ATTRIBUTES on LogRecord
- LogRecord attributes are accessed via getattr(lr, "key"), not getMessage()
"""

import logging
import tempfile
import time
from pathlib import Path

import pytest

from cisternal import init
from cisternal.adapters.base import ContemplexAdapter
from cisternal.adapters.v2_decorator import traced_tool
from cisternal.telemetry.exporter import ShadowExporter
from .harness import assert_parity, capture_legacy

_contemplex_logger = logging.getLogger("contemplex")


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for JSONL logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up pipeline and self-observability state between tests."""
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


class TestAcShadow2:
    """AC-SHADOW-2: Contemplex stub pattern with start->end ordering in both streams."""

    def test_start_end_ordering_in_cisternal(self, temp_log_dir):
        """Given contemplex legacy telemetry;
        When brainstorm_start called and emits both start and end logs;
        Then cisternal records preserve start->end ordering (call_start < call_end).
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(ContemplexAdapter())
        def brainstorm_start(session_id: str = "test"):
            # Emit legacy start and end logs
            _contemplex_logger.info("start", extra={"tool": "brainstorm_start"})
            _contemplex_logger.info("end", extra={"tool": "brainstorm_start"})
            return {"session_id": session_id, "ok": True}

        with capture_legacy("contemplex") as legacy:
            brainstorm_start()
            time.sleep(0.05)  # Allow events to export

        # Get cisternal records for this tool
        mcp_records = [
            r for r in shadow.records if r.fields.get("tool") == "brainstorm_start"
        ]

        assert len(legacy) >= 2, f"Legacy stream must have >= 2 records, got {len(legacy)}"
        assert (
            len(mcp_records) >= 2
        ), f"Cisternal stream must have >= 2 records, got {len(mcp_records)}"

        # Verify start->end ordering in cisternal
        names = [r.name for r in mcp_records]
        assert "mcp.call_start" in names, f"Missing call_start in {names}"
        assert "mcp.call_end" in names, f"Missing call_end in {names}"

        start_idx = names.index("mcp.call_start")
        end_idx = names.index("mcp.call_end")
        assert (
            start_idx < end_idx
        ), f"call_start at {start_idx} should come before call_end at {end_idx}"

    def test_contemplex_parity(self, temp_log_dir):
        """Given contemplex legacy telemetry + cisternal shadow active;
        When brainstorm_reply called;
        Then capture_legacy("contemplex") and capture_cisternal each captured >= 1
        matching record; parity passes.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(ContemplexAdapter())
        def brainstorm_reply(reply: str = "idea"):
            # Emit legacy telemetry
            _contemplex_logger.info("reply", extra={"tool": "brainstorm_reply"})
            return {"ok": True}

        with capture_legacy("contemplex") as legacy:
            brainstorm_reply()
            time.sleep(0.05)  # Allow events to export

        # Get cisternal records for this tool
        mcp_records = [
            r for r in shadow.records if r.fields.get("tool") == "brainstorm_reply"
        ]

        assert len(legacy) >= 1, "Legacy stream must have >= 1 record"
        assert len(mcp_records) >= 1, "Cisternal stream must have >= 1 record"
        assert_parity(legacy, mcp_records)
