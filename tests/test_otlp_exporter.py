"""M7 OTLP egress tests — OtlpExporter + init_pipeline env gate."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

import cisterna
from cisterna.adapters.base import ContemplexAdapter
from cisterna.adapters.v2_decorator import traced_tool
from cisterna.telemetry.exporter import ExporterBase, ShadowExporter
from cisterna.telemetry.otlp_exporter import OtlpExporter, otlp_sdk_available
from cisterna.telemetry.pipeline import get_pipeline, shutdown_pipeline
from cisterna.telemetry.record import Record


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def _exporter_types() -> list[str]:
    pipeline = get_pipeline()
    assert pipeline is not None
    return [type(e).__name__ for e in pipeline._exporters]


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_jsonl_only_when_otlp_endpoint_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-M7-1a: unset endpoint → JsonlExporter only."""
    monkeypatch.delenv("CISTERNA_OTLP_ENDPOINT", raising=False)
    cisterna.init(log_dir=tmp_path, heartbeat_interval=30.0)
    types = _exporter_types()
    assert "JsonlExporter" in types
    assert "OtlpExporter" not in types


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_dual_export_when_otlp_endpoint_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-M7-1b: endpoint set → JsonlExporter + OtlpExporter."""
    monkeypatch.setenv("CISTERNA_OTLP_ENDPOINT", "http://localhost:4317")
    cisterna.init(log_dir=tmp_path, heartbeat_interval=30.0)
    types = _exporter_types()
    assert "JsonlExporter" in types
    assert "OtlpExporter" in types


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_raising_otlp_exporter_does_not_break_jsonl(
    tmp_path: Path,
) -> None:
    """AC-M7-1c: OTLP failure isolated; JSONL still receives records."""

    class RaisingOtlp(ExporterBase):
        def export(self, record: Record) -> None:
            raise RuntimeError("otlp down")

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    shadow = ShadowExporter()
    cisterna.init(
        log_dir=tmp_path,
        exporters=[RaisingOtlp(), shadow],
        heartbeat_interval=30.0,
    )
    cisterna.emit_event("test.event", field="value")

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(shadow.records) < 1:
        time.sleep(0.01)

    assert len(shadow.records) >= 1
    assert shadow.records[0].name == "test.event"


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_call_pair_exports_span_with_tool_attribute(tmp_path: Path) -> None:
    """AC-M7-1d / AC-M7-2a: mcp.call_start/end → span with tool attribute."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    memory = InMemorySpanExporter()
    otlp = OtlpExporter(span_exporter=memory)
    shadow = ShadowExporter()
    cisterna.init(
        log_dir=tmp_path,
        exporters=[otlp, shadow],
        heartbeat_interval=30.0,
    )

    @traced_tool(ContemplexAdapter())
    def demo_tool(msg: str) -> str:
        return f"ok:{msg}"

    result = demo_tool(msg="hi")
    assert result == "ok:hi"

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(memory.get_finished_spans()) < 1:
        time.sleep(0.01)

    otlp.flush()
    spans = memory.get_finished_spans()
    assert len(spans) >= 1
    assert spans[0].name == "demo_tool"
    assert spans[0].attributes.get("tool") == "demo_tool"


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_heartbeat_dropped_from_otlp(tmp_path: Path) -> None:
    """AC-M7-2b: heartbeat records do not create OTLP spans."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    memory = InMemorySpanExporter()
    otlp = OtlpExporter(span_exporter=memory)
    cisterna.init(
        log_dir=tmp_path,
        exporters=[otlp],
        heartbeat_interval=30.0,
    )

    cisterna.emit_event("telemetry.heartbeat", pipeline_alive=True)
    otlp.flush()

    assert len(memory.get_finished_spans()) == 0


def test_sdk_lazy_until_otlp_init(tmp_path: Path) -> None:
    """AC-M7-0b: importing cisterna does not load opentelemetry.sdk until OTLP init."""
    if not otlp_sdk_available():
        pytest.skip("opentelemetry-sdk not installed")

    script = f"""
import importlib
import sys
from pathlib import Path

for name in list(sys.modules):
    if name.startswith("cisterna") or name.startswith("opentelemetry.sdk"):
        del sys.modules[name]

importlib.import_module("cisterna")
assert "opentelemetry.sdk.trace" not in sys.modules

import os
os.environ["CISTERNA_OTLP_ENDPOINT"] = "http://localhost:4317"
mod = importlib.import_module("cisterna")
mod.init(log_dir={str(tmp_path)!r}, heartbeat_interval=30.0)
assert "opentelemetry.sdk.trace" in sys.modules
mod.get_pipeline().shutdown()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
