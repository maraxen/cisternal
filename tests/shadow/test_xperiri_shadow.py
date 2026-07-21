"""AC-SHADOW-3: Xperiri shadow test for parity verification.

xperiri MCP tools return JSON strings (see xperiri/mcp_server.py). Legacy
telemetry today uses event_log (stdout JSON); shadow fixtures use logger
\"xperiri\" as the cutover contract matching bathos/contemplex harness.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path

import pytest

from cisternal import init
from cisternal.adapters.base import XpeririAdapter
from cisternal.adapters.v2_decorator import traced_tool
from cisternal.telemetry.exporter import ShadowExporter

from .harness import assert_parity, capture_legacy

_xperiri_logger = logging.getLogger("xperiri")


@pytest.fixture
def temp_log_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def cleanup():
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


def _wait_for_records(shadow: ShadowExporter, tool: str, min_count: int = 1) -> list:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        records = [r for r in shadow.records if r.fields.get("tool") == tool]
        if len(records) >= min_count:
            return records
        time.sleep(0.01)
    return [r for r in shadow.records if r.fields.get("tool") == tool]


class TestAcShadow3:
    """AC-SHADOW-3: Xperiri stub pattern with legacy and cisternal parity."""

    def test_xperiri_shadow_parity(self, temp_log_dir: Path) -> None:
        """Given xperiri legacy logger + cisternal shadow;
        When expert_list_tool called;
        Then parity passes on tool name overlap.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(XpeririAdapter())
        def expert_list() -> str:
            _xperiri_logger.info(
                "tool_call",
                extra={"tool": "expert_list", "event": "call"},
            )
            return json.dumps({"experts": []})

        with capture_legacy("xperiri") as legacy:
            result = expert_list()
            _wait_for_records(shadow, "expert_list")

        assert json.loads(result) == {"experts": []}
        mcp_records = _wait_for_records(shadow, "expert_list")
        assert len(legacy) >= 1
        assert len(mcp_records) >= 1
        assert_parity(legacy, mcp_records)

    def test_xperiri_shadow_start_end_ordering(self, temp_log_dir: Path) -> None:
        """Given xperiri traced tool;
        When called;
        Then mcp.call_start precedes mcp.call_end in cisternal records.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(XpeririAdapter())
        def expert_resolve(expert_id: str) -> str:
            return json.dumps({"id": expert_id, "persona": "test"})

        expert_resolve(expert_id="domain-expert")
        tool_records = _wait_for_records(shadow, "expert_resolve", min_count=2)

        names = [r.name for r in tool_records]
        assert "mcp.call_start" in names
        assert "mcp.call_end" in names
        assert names.index("mcp.call_start") < names.index("mcp.call_end")

    def test_xperiri_traced_tool_returns_json_str(self, temp_log_dir: Path) -> None:
        """traced_tool(XpeririAdapter) preserves JSON-string return shape."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(XpeririAdapter())
        def expert_describe(expert_id: str) -> str:
            return json.dumps({"error": f"Expert not found: {expert_id}", "expert_id": expert_id})

        raw = expert_describe(expert_id="missing")
        parsed = json.loads(raw)
        assert parsed["expert_id"] == "missing"
        assert "error" in parsed
