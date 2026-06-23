"""M6.1b bathos telemetry cutover gate smoke tests."""

from __future__ import annotations

import time

import pytest

import cisterna
from cisterna.adapters.base import BathosAdapter
from cisterna.adapters.v2_decorator import traced_tool
from cisterna.probe.telemetry_env import consumer_telemetry_enabled
from cisterna.telemetry.exporter import ShadowExporter
from cisterna.telemetry.pipeline import shutdown_pipeline


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def test_consumer_telemetry_enabled_bathos_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M6-2a: CISTERNA_TELEMETRY=bathos enables bathos."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    assert consumer_telemetry_enabled("bathos") is True


def test_consumer_telemetry_disabled_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M6-2b: unset env → disabled."""
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    assert consumer_telemetry_enabled("bathos") is False


def test_traced_tool_emits_when_cutover_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """AC-M6-2c: traced_tool + BathosAdapter emits mcp.call_start."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    assert consumer_telemetry_enabled("bathos")

    shadow = ShadowExporter()
    cisterna.init(log_dir=tmp_path, exporters=[shadow], heartbeat_interval=30.0)

    @traced_tool(BathosAdapter())
    def demo_tool(msg: str) -> dict:
        return {"msg": msg}

    result = demo_tool(msg="hi")
    assert result["ok"] is True

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not any(
        r.name == "mcp.call_start" for r in shadow.records
    ):
        time.sleep(0.01)

    starts = [r for r in shadow.records if r.name == "mcp.call_start"]
    assert len(starts) >= 1
    assert starts[0].fields.get("tool") == "demo_tool"
