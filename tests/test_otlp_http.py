"""M7.1 OTLP HTTP protocol + optional collector integration smoke tests."""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest

import cisterna
from cisterna.adapters.base import ContemplexAdapter
from cisterna.adapters.v2_decorator import traced_tool
from cisterna.telemetry.otlp_exporter import (
    OtlpExporter,
    create_otlp_span_exporter,
    otlp_sdk_available,
    resolve_otlp_protocol,
)
from cisterna.telemetry.pipeline import get_pipeline, shutdown_pipeline


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def _collector_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("grpc", "grpc"),
        ("http", "http"),
        ("http/protobuf", "http"),
        ("", "grpc"),
    ],
)
def test_resolve_otlp_protocol(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    expected: str,
) -> None:
    if env_value:
        monkeypatch.setenv("CISTERNA_OTLP_PROTOCOL", env_value)
    else:
        monkeypatch.delenv("CISTERNA_OTLP_PROTOCOL", raising=False)
    assert resolve_otlp_protocol() == expected


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_create_otlp_span_exporter_http() -> None:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as HttpExporter,
    )

    exporter = create_otlp_span_exporter("http://localhost:4318", protocol="http")
    assert isinstance(exporter, HttpExporter)


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_create_otlp_span_exporter_grpc() -> None:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as GrpcExporter,
    )

    exporter = create_otlp_span_exporter("http://localhost:4317", protocol="grpc")
    assert isinstance(exporter, GrpcExporter)


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
def test_dual_export_when_http_protocol_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-M7.1-1b: CISTERNA_OTLP_PROTOCOL=http still attaches OtlpExporter."""
    monkeypatch.setenv("CISTERNA_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("CISTERNA_OTLP_PROTOCOL", "http")
    cisterna.init(log_dir=tmp_path, heartbeat_interval=30.0)
    pipeline = get_pipeline()
    assert pipeline is not None
    types = [type(e).__name__ for e in pipeline._exporters]
    assert "OtlpExporter" in types


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
@pytest.mark.integration
def test_grpc_collector_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advisory: export span pair to local OTLP gRPC collector (port 4317)."""
    if not _collector_port_open("127.0.0.1", 4317):
        pytest.skip("otel-collector gRPC not listening on 4317")

    monkeypatch.setenv("CISTERNA_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("CISTERNA_OTLP_PROTOCOL", raising=False)
    cisterna.init(log_dir=tmp_path, heartbeat_interval=30.0)

    @traced_tool(ContemplexAdapter())
    def smoke_tool(msg: str) -> str:
        return f"ok:{msg}"

    assert smoke_tool(msg="ci") == "ok:ci"

    pipeline = get_pipeline()
    assert pipeline is not None
    for exporter in pipeline._exporters:
        if isinstance(exporter, OtlpExporter):
            exporter.flush()

    time.sleep(0.2)


@pytest.mark.skipif(not otlp_sdk_available(), reason="opentelemetry-sdk not installed")
@pytest.mark.integration
def test_http_collector_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advisory: export span pair to local OTLP HTTP collector (port 4318)."""
    if not _collector_port_open("127.0.0.1", 4318):
        pytest.skip("otel-collector HTTP not listening on 4318")

    monkeypatch.setenv("CISTERNA_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("CISTERNA_OTLP_PROTOCOL", "http")
    cisterna.init(log_dir=tmp_path, heartbeat_interval=30.0)

    @traced_tool(ContemplexAdapter())
    def smoke_tool(msg: str) -> str:
        return f"ok:{msg}"

    assert smoke_tool(msg="ci-http") == "ok:ci-http"

    pipeline = get_pipeline()
    assert pipeline is not None
    for exporter in pipeline._exporters:
        if isinstance(exporter, OtlpExporter):
            exporter.flush()

    time.sleep(0.2)
