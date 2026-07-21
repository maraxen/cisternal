"""M8.2 xperiri telemetry cutover gate smoke tests."""

from __future__ import annotations

import json
import time

import pytest

import cisternal
from cisternal.adapters.base import XpeririAdapter
from cisternal.adapters.v2_decorator import traced_tool
from cisternal.probe.telemetry_env import consumer_telemetry_enabled
from cisternal.telemetry.exporter import ShadowExporter
from cisternal.telemetry.pipeline import shutdown_pipeline


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def test_consumer_telemetry_enabled_xperiri_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M8.2-2a: CISTERNAL_TELEMETRY=xperiri enables xperiri."""
    monkeypatch.setenv("CISTERNAL_TELEMETRY", "xperiri")
    assert consumer_telemetry_enabled("xperiri") is True


def test_consumer_telemetry_disabled_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M8.2-2b: unset env → disabled."""
    monkeypatch.delenv("CISTERNAL_TELEMETRY", raising=False)
    assert consumer_telemetry_enabled("xperiri") is False


def test_traced_tool_emits_when_cutover_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """AC-M8.2-2c: sync traced_tool + XpeririAdapter emits mcp.call_start."""
    monkeypatch.setenv("CISTERNAL_TELEMETRY", "xperiri")
    assert consumer_telemetry_enabled("xperiri")

    shadow = ShadowExporter()
    cisternal.init(log_dir=tmp_path, exporters=[shadow], heartbeat_interval=30.0)

    @traced_tool(XpeririAdapter())
    def expert_list() -> str:
        return json.dumps({"experts": []})

    result = expert_list()
    assert json.loads(result) == {"experts": []}

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not any(
        r.name == "mcp.call_start" for r in shadow.records
    ):
        time.sleep(0.01)

    starts = [r for r in shadow.records if r.name == "mcp.call_start"]
    assert len(starts) >= 1
    assert starts[0].fields.get("tool") == "expert_list"
