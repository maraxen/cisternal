"""AC-SHADOW-1: Bathos shadow test for parity verification.

Tests that bathos legacy telemetry and cisternal shadow capture the same
tool invocations with matching event names and field parity.

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
from cisternal.adapters.base import BathosAdapter
from cisternal.adapters.v2_decorator import traced_tool
from cisternal.telemetry.exporter import ShadowExporter
from .harness import assert_parity, capture_legacy

_bathos_logger = logging.getLogger("bathos")


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


class TestAcShadow1:
    """AC-SHADOW-1: Bathos stub pattern with legacy and cisternal parity."""

    def test_bathos_shadow_parity(self, temp_log_dir):
        """Given bathos legacy telemetry + cisternal shadow active;
        When list_runs_tool called;
        Then capture_legacy("bathos") and capture_cisternal each captured >=1 matching record;
        parity passes.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(BathosAdapter())
        def list_runs_tool():
            # Emit legacy telemetry: extra dict becomes LogRecord attributes
            _bathos_logger.info(
                "call",
                extra={"tool": "list_runs_tool", "event": "call"},
            )
            return {"runs": []}

        with capture_legacy("bathos") as legacy:
            list_runs_tool()
            time.sleep(0.05)  # Allow events to export

        # Get cisternal records for this tool
        mcp_records = [
            r for r in shadow.records if r.fields.get("tool") == "list_runs_tool"
        ]

        assert len(legacy) >= 1, "Legacy stream must have >= 1 record"
        assert len(mcp_records) >= 1, "Cisternal stream must have >= 1 record"
        assert_parity(legacy, mcp_records)

    def test_bathos_shadow_start_end_ordering(self, temp_log_dir):
        """Given bathos legacy telemetry;
        When list_runs_tool called;
        Then mcp.call_start appears before mcp.call_end in cisternal records.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(BathosAdapter())
        def list_runs_tool():
            return {"runs": []}

        list_runs_tool()
        time.sleep(0.05)

        tool_records = [
            r for r in shadow.records if r.fields.get("tool") == "list_runs_tool"
        ]
        names = [r.name for r in tool_records]

        assert "mcp.call_start" in names, f"Missing call_start in {names}"
        assert "mcp.call_end" in names, f"Missing call_end in {names}"

        start_idx = names.index("mcp.call_start")
        end_idx = names.index("mcp.call_end")
        assert (
            start_idx < end_idx
        ), f"call_start at {start_idx} should come before call_end at {end_idx}"
