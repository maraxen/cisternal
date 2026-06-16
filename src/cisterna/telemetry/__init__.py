"""Telemetry core: event pipeline, records, exporters, context, and spans."""

from .context import (
    run_uuid_var,
    mcp_request_id_var,
    task_id_var,
    request_id_var,
    session_id_var,
    phase_var,
    _build_record,
)
from .record import Record
from .exporter import ExporterBase, JsonlExporter, ShadowExporter
from .pipeline import EventPipeline, init_pipeline, get_pipeline, shutdown_pipeline
from .span import span, aspan
from .self_obs import status, StatusReport

__all__ = [
    "run_uuid_var",
    "mcp_request_id_var",
    "task_id_var",
    "request_id_var",
    "session_id_var",
    "phase_var",
    "_build_record",
    "Record",
    "ExporterBase",
    "JsonlExporter",
    "ShadowExporter",
    "EventPipeline",
    "init_pipeline",
    "get_pipeline",
    "shutdown_pipeline",
    "span",
    "aspan",
    "status",
    "StatusReport",
]
