"""Telemetry operator diagnostic report (M10.1)."""

from __future__ import annotations

import os
from pathlib import Path

from cisterna.probe.telemetry_env import consumer_telemetry_enabled

_KNOWN_CONSUMERS = ("bathos", "contemplex", "xperiri", "myxcel")
_RUNBOOK_PATH = ".praxia/docs/runbooks/cisterna-telemetry.md"


def probe_log_dir_writable(log_dir: Path) -> bool:
    """Return whether *log_dir* can be created and written (no fallback)."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        probe_file = log_dir / ".write_probe"
        probe_file.touch()
        probe_file.unlink()
    except OSError:
        return False
    return True


def _job_context_line() -> str | None:
    myx_job = os.environ.get("MYX_JOB_ID", "").strip()
    if myx_job:
        return f"task_id: {myx_job} (from MYX_JOB_ID)"
    bth_task = os.environ.get("BTH_TASK_ID", "").strip()
    if bth_task:
        return f"task_id: {bth_task} (from BTH_TASK_ID)"
    return None


def format_doctor_report() -> str:
    """Build human-readable telemetry doctor output."""
    from cisterna.telemetry.otlp_exporter import (
        otlp_sdk_available,
        resolve_otlp_protocol,
    )
    from cisterna.telemetry.pipeline import get_pipeline, resolve_log_dir_from_env

    lines: list[str] = [
        "cisterna telemetry doctor",
        f"runbook: {_RUNBOOK_PATH}",
        "",
        "CISTERNA_TELEMETRY gate",
    ]

    raw_telemetry = os.environ.get("CISTERNA_TELEMETRY", "").strip()
    lines.append(f"  raw: {raw_telemetry or '(unset)'}")
    for consumer in _KNOWN_CONSUMERS:
        state = "enabled" if consumer_telemetry_enabled(consumer) else "disabled"
        lines.append(f"  {consumer}: {state}")

    log_dir = resolve_log_dir_from_env()
    writable = probe_log_dir_writable(log_dir)
    lines.extend(
        [
            "",
            "JSONL log directory",
            f"  resolved: {log_dir}",
            f"  writable: {'yes' if writable else 'no'}",
        ]
    )

    job_line = _job_context_line()
    if job_line is not None:
        lines.extend(["", "job_span context", f"  {job_line}"])

    endpoint = os.environ.get("CISTERNA_OTLP_ENDPOINT", "").strip()
    protocol = resolve_otlp_protocol()
    sdk_state = "installed" if otlp_sdk_available() else "missing"
    lines.extend(
        [
            "",
            "OTLP egress",
            f"  CISTERNA_OTLP_ENDPOINT: {endpoint or '(unset)'}",
            f"  CISTERNA_OTLP_PROTOCOL: {protocol}",
            f"  otlp_sdk: {sdk_state}",
        ]
    )

    pipeline = get_pipeline()
    if pipeline is None:
        pipeline_state = "inactive (expected unless cisterna.init() ran)"
    else:
        pipeline_state = "active"
    lines.extend(["", "pipeline", f"  status: {pipeline_state}"])

    return "\n".join(lines)
