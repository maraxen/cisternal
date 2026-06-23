"""AC-SHADOW-4: Myxcel shadow test for parity verification.

myxcel MCP tools return dict envelopes (see myxcel/mcp_server.py _tool_error).
Shadow fixtures use logger \"myxcel\" as the cutover contract.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import pytest

from cisterna import init, job_span
from cisterna.adapters.base import MyxcelAdapter
from cisterna.adapters.v2_decorator import traced_tool
from cisterna.telemetry.exporter import ShadowExporter

from .harness import assert_parity, capture_legacy

_myxcel_logger = logging.getLogger("myxcel")


@pytest.fixture
def temp_log_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    from cisterna.telemetry import pipeline as pm
    import cisterna.telemetry.self_obs as so_mod

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


class TestAcShadow4:
    """AC-SHADOW-4: Myxcel stub pattern with legacy and cisterna parity."""

    def test_myxcel_shadow_parity(self, temp_log_dir: Path) -> None:
        """Given myxcel legacy logger + cisterna shadow;
        When mount_project stub called;
        Then parity passes on tool name overlap.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(MyxcelAdapter())
        def mount_project(remote: str, project: str) -> dict:
            _myxcel_logger.info(
                "tool_call",
                extra={"tool": "mount_project", "event": "call"},
            )
            return {"remote": remote, "project": project, "mounted": True}

        with capture_legacy("myxcel") as legacy:
            result = mount_project(remote="hpc", project="demo")
            _wait_for_records(shadow, "mount_project")

        assert result == {"remote": "hpc", "project": "demo", "mounted": True}
        mcp_records = _wait_for_records(shadow, "mount_project")
        assert len(legacy) >= 1
        assert len(mcp_records) >= 1
        assert_parity(legacy, mcp_records)

    def test_myxcel_shadow_start_end_ordering(self, temp_log_dir: Path) -> None:
        """Given myxcel traced tool;
        When called;
        Then mcp.call_start precedes mcp.call_end in cisterna records.
        """
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(MyxcelAdapter())
        def mount_status(remote: str | None = None) -> list[dict]:
            return [{"remote": remote or "all", "mounted": False}]

        mount_status(remote="hpc")
        tool_records = _wait_for_records(shadow, "mount_status", min_count=2)

        names = [r.name for r in tool_records]
        assert "mcp.call_start" in names
        assert "mcp.call_end" in names
        assert names.index("mcp.call_start") < names.index("mcp.call_end")

    def test_myxcel_traced_tool_in_band_error_shape(self, temp_log_dir: Path) -> None:
        """traced_tool(MyxcelAdapter) preserves dict error envelope from shape_ok."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        @traced_tool(MyxcelAdapter())
        def mount_project(remote: str, project: str) -> dict:
            return {"error": "FileNotFoundError", "message": f"no profile: {remote}"}

        result = mount_project(remote="missing", project="demo")
        assert result["error"] == "FileNotFoundError"
        assert "missing" in result["message"]

    def test_myxcel_job_span_emits_with_task_id(self, temp_log_dir: Path, monkeypatch) -> None:
        """job_span fixture emits slurm.run.* with task_id for HPC path."""
        monkeypatch.setenv("MYX_JOB_ID", "shadow-job-1")
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        with capture_legacy("myxcel") as legacy:
            _myxcel_logger.info("job_start", extra={"job_id": "shadow-job-1"})
            with job_span("slurm.run", remote="hpc"):
                time.sleep(0.01)
            _myxcel_logger.info("job_end", extra={"job_id": "shadow-job-1"})

        time.sleep(0.05)
        span_records = [r for r in shadow.records if r.name.startswith("slurm.run.")]
        assert len(span_records) >= 2
        assert all(r.task_id == "shadow-job-1" for r in span_records)
        assert len(legacy) >= 1
