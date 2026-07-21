"""M9.2 myxcel telemetry cutover gate smoke tests."""

from __future__ import annotations

import asyncio
import time

import pytest

import cisternal
from cisternal.adapters.base import MyxcelAdapter
from cisternal.adapters.v2_decorator import traced_tool
from cisternal.probe.telemetry_env import consumer_telemetry_enabled
from cisternal.telemetry.exporter import ShadowExporter
from cisternal.telemetry.pipeline import shutdown_pipeline


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def test_consumer_telemetry_enabled_myxcel_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M9.2-2a: CISTERNAL_TELEMETRY=myxcel enables myxcel."""
    monkeypatch.setenv("CISTERNAL_TELEMETRY", "myxcel")
    assert consumer_telemetry_enabled("myxcel") is True


def test_consumer_telemetry_disabled_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M9.2-2b: unset env → disabled."""
    monkeypatch.delenv("CISTERNAL_TELEMETRY", raising=False)
    assert consumer_telemetry_enabled("myxcel") is False


@pytest.mark.asyncio
async def test_traced_tool_emits_when_cutover_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """AC-M9.2-2c: async traced_tool + MyxcelAdapter emits mcp.call_start."""
    monkeypatch.setenv("CISTERNAL_TELEMETRY", "myxcel")
    assert consumer_telemetry_enabled("myxcel")

    shadow = ShadowExporter()
    cisternal.init(log_dir=tmp_path, exporters=[shadow], heartbeat_interval=30.0)

    @traced_tool(MyxcelAdapter())
    async def mount_project(remote: str, project: str) -> dict:
        await asyncio.sleep(0)
        return {"remote": remote, "project": project, "mounted": True}

    result = await mount_project(remote="hpc", project="demo")
    assert result["mounted"] is True

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not any(
        r.name == "mcp.call_start" for r in shadow.records
    ):
        await asyncio.sleep(0.01)

    starts = [r for r in shadow.records if r.name == "mcp.call_start"]
    assert len(starts) >= 1
    assert starts[0].fields.get("tool") == "mount_project"
