"""OTLP trace exporter — optional egress via CISTERNA_OTLP_ENDPOINT (M7)."""

from __future__ import annotations

import sys
import threading
from typing import Any

from opentelemetry.trace import Span, Status, StatusCode

from .exporter import ExporterBase
from .record import Record

_HEARTBEAT_NAMES = frozenset({"telemetry.heartbeat"})


def otlp_sdk_available() -> bool:
    """Return True when the OpenTelemetry SDK is installed ([otlp] extra)."""
    try:
        import opentelemetry.sdk.trace  # noqa: F401

        return True
    except ImportError:
        return False


def _ns_from_ts(ts: float) -> int:
    return int(ts * 1_000_000_000)


class OtlpExporter(ExporterBase):
    """Maps cisterna Records to OpenTelemetry spans and exports via OTLP gRPC.

    Span pairing:
    - ``mcp.call_start`` + ``mcp.call_end`` → one span (keyed by request_id)
    - ``*.start`` + ``*.end`` → one span (keyed by span_id or request_id)
    - ``mcp.tool_error`` → error span
    - ``telemetry.heartbeat`` → dropped (JSONL only)

    SDK imports are lazy — default ``import cisterna`` does not require [otlp].
    """

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        service_name: str | None = None,
        span_exporter: Any | None = None,
    ) -> None:
        import os

        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
            SpanExporter,
        )

        if span_exporter is None:
            if not endpoint:
                msg = "OtlpExporter requires endpoint or span_exporter"
                raise ValueError(msg)
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter: SpanExporter = OTLPSpanExporter(endpoint=endpoint)
            processor = BatchSpanProcessor(exporter)
        else:
            processor = SimpleSpanProcessor(span_exporter)

        resolved_service = (
            service_name
            or os.environ.get("OTEL_SERVICE_NAME")
            or "cisterna"
        )
        self._provider = TracerProvider(
            resource=Resource.create({"service.name": resolved_service}),
        )
        self._provider.add_span_processor(processor)
        self._tracer = self._provider.get_tracer("cisterna")
        self._pending: dict[str, Span] = {}
        self._lock = threading.Lock()

    def export(self, record: Record) -> None:
        try:
            if record.name in _HEARTBEAT_NAMES:
                return

            if record.name == "mcp.call_start":
                self._export_call_start(record)
            elif record.name == "mcp.call_end":
                self._export_call_end(record)
            elif record.name == "mcp.tool_error":
                self._export_tool_error(record)
            elif record.name.endswith(".start"):
                self._export_named_start(record)
            elif record.name.endswith(".end"):
                self._export_named_end(record)
        except Exception as exc:
            print(
                f"[cisterna] OtlpExporter.export() failed: {exc}",
                file=sys.stderr,
            )

    def flush(self) -> None:
        try:
            self._provider.force_flush()
        except Exception as exc:
            print(f"[cisterna] OtlpExporter.flush() failed: {exc}", file=sys.stderr)

    def close(self) -> None:
        try:
            self._provider.shutdown()
        except Exception as exc:
            print(f"[cisterna] OtlpExporter.close() failed: {exc}", file=sys.stderr)

    def _pair_key(self, record: Record) -> str:
        fields = record.fields
        for key in ("request_id", "span_id"):
            if value := fields.get(key):
                return str(value)
        if record.mcp_request_id:
            return str(record.mcp_request_id)
        if record.request_id:
            return str(record.request_id)
        return f"{record.name}:{record.ts}"

    def _export_call_start(self, record: Record) -> None:
        tool = str(record.fields.get("tool", "mcp.tool"))
        key = self._pair_key(record)
        span = self._tracer.start_span(
            tool,
            start_time=_ns_from_ts(record.ts),
        )
        span.set_attribute("tool", tool)
        span.set_attribute("request_id", key)
        if arg_keys := record.fields.get("arg_keys"):
            span.set_attribute("arg_keys", str(arg_keys))
        with self._lock:
            self._pending[key] = span

    def _export_call_end(self, record: Record) -> None:
        key = self._pair_key(record)
        with self._lock:
            span = self._pending.pop(key, None)
        if span is None:
            return
        if duration_ms := record.fields.get("duration_ms"):
            span.set_attribute("duration_ms", float(duration_ms))
        span.end(end_time=_ns_from_ts(record.ts))

    def _export_tool_error(self, record: Record) -> None:
        tool = str(record.fields.get("tool", "mcp.tool"))
        key = self._pair_key(record)
        with self._lock:
            pending = self._pending.pop(key, None)
        if pending is not None:
            pending.set_status(
                Status(
                    StatusCode.ERROR,
                    str(record.fields.get("exc_msg", record.fields.get("error", ""))),
                ),
            )
            pending.end(end_time=_ns_from_ts(record.ts))
            return

        span = self._tracer.start_span(tool, start_time=_ns_from_ts(record.ts))
        span.set_attribute("tool", tool)
        span.set_status(
            Status(
                StatusCode.ERROR,
                str(record.fields.get("exc_msg", record.fields.get("error", ""))),
            ),
        )
        span.end(end_time=_ns_from_ts(record.ts))

    def _export_named_start(self, record: Record) -> None:
        span_name = record.name[: -len(".start")]
        key = self._pair_key(record)
        span = self._tracer.start_span(
            span_name,
            start_time=_ns_from_ts(record.ts),
        )
        span.set_attribute("span_id", key)
        for field_key, value in record.fields.items():
            if field_key != "span_id":
                span.set_attribute(field_key, str(value))
        with self._lock:
            self._pending[key] = span

    def _export_named_end(self, record: Record) -> None:
        key = self._pair_key(record)
        with self._lock:
            span = self._pending.pop(key, None)
        if span is None:
            return
        if duration_ms := record.fields.get("duration_ms"):
            span.set_attribute("duration_ms", float(duration_ms))
        if record.fields.get("ok") is False:
            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=_ns_from_ts(record.ts))


def maybe_create_otlp_exporter() -> OtlpExporter | None:
    """Create OtlpExporter when endpoint is set and SDK is available."""
    import os

    endpoint = os.environ.get("CISTERNA_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return None
    if not otlp_sdk_available():
        print(
            "[cisterna] CISTERNA_OTLP_ENDPOINT set but opentelemetry-sdk not installed; "
            "install cisterna[otlp]",
            file=sys.stderr,
        )
        return None
    return OtlpExporter(endpoint=endpoint)
