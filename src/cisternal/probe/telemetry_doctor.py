"""Telemetry operator diagnostic report (M10.1 / M10.2 / M10.4)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cisternal.probe.telemetry_env import consumer_telemetry_enabled

CheckStatus = Literal["pass", "warn", "fail"]

_KNOWN_CONSUMERS = ("bathos", "contemplex", "xperiri", "myxcel")
_RUNBOOK_PATH = ".praxia/docs/runbooks/cisternal-telemetry.md"
_STRICT_ENV_VALUES = frozenset({"1", "true", "yes"})
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DoctorCheck:
    """One doctor diagnostic check."""

    id: str
    status: CheckStatus
    message: str
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class DoctorReport:
    """Structured telemetry doctor report."""

    checks: tuple[DoctorCheck, ...]
    raw_telemetry: str
    consumer_filter: str | None = None
    runbook_path: str = _RUNBOOK_PATH


def resolve_doctor_consumer(*, cli_consumer: str | None = None) -> str | None:
    """Resolve optional consumer filter from CLI flag or env."""
    raw = (cli_consumer or "").strip()
    if not raw:
        raw = os.environ.get("CISTERNAL_DOCTOR_CONSUMER", "").strip()
    if not raw:
        return None
    name = raw.lower()
    if name not in _KNOWN_CONSUMERS:
        known = "|".join(_KNOWN_CONSUMERS)
        msg = f"unknown consumer {raw!r}; known: {known}"
        raise ValueError(msg)
    return name


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


def resolve_doctor_strict_mode(*, cli_strict: bool = False) -> bool:
    """Return whether strict exit promotion is active."""
    if cli_strict:
        return True
    raw = os.environ.get("CISTERNAL_DOCTOR_STRICT", "").strip().lower()
    return raw in _STRICT_ENV_VALUES


def effective_check_status(check: DoctorCheck, *, strict: bool) -> CheckStatus:
    """Return severity used for exit-code computation."""
    if strict and check.status == "warn":
        return "fail"
    return check.status


def compute_doctor_exit_code(report: DoctorReport, *, strict: bool) -> int:
    """Return process exit code (0 pass, 1 any effective fail)."""
    for check in report.checks:
        if effective_check_status(check, strict=strict) == "fail":
            return 1
    return 0


def _build_telemetry_gate_check(
    raw_telemetry: str,
    consumer_filter: str | None,
) -> DoctorCheck:
    """Build telemetry_gate check (any-consumer or scoped)."""
    if consumer_filter is not None:
        enabled = consumer_telemetry_enabled(consumer_filter)
        gate_status: CheckStatus = "pass" if enabled else "warn"
        raw_display = raw_telemetry or "(unset)"
        state = "enabled" if enabled else "disabled"
        gate_message = f"raw={raw_display}; target {consumer_filter}: {state}"
        detail: dict[str, Any] = {
            "raw": raw_telemetry or None,
            "target_consumer": consumer_filter,
        }
    elif not raw_telemetry:
        gate_status = "warn"
        gate_message = "CISTERNAL_TELEMETRY is unset"
        detail = {"raw": None}
    elif any(consumer_telemetry_enabled(c) for c in _KNOWN_CONSUMERS):
        gate_status = "pass"
        gate_message = "at least one consumer enabled"
        detail = {"raw": raw_telemetry}
    else:
        gate_status = "warn"
        gate_message = f"no known consumer enabled for raw={raw_telemetry!r}"
        detail = {"raw": raw_telemetry}

    return DoctorCheck(
        id="telemetry_gate",
        status=gate_status,
        message=gate_message,
        detail=detail,
    )


def build_doctor_report(consumer_filter: str | None = None) -> DoctorReport:
    """Collect structured telemetry doctor checks."""
    from cisternal.telemetry.otlp_exporter import (
        otlp_sdk_available,
        resolve_otlp_protocol,
    )
    from cisternal.telemetry.pipeline import get_pipeline, resolve_log_dir_from_env

    checks: list[DoctorCheck] = []
    raw_telemetry = os.environ.get("CISTERNAL_TELEMETRY", "").strip()

    checks.append(_build_telemetry_gate_check(raw_telemetry, consumer_filter))

    for name in _KNOWN_CONSUMERS:
        enabled = consumer_telemetry_enabled(name)
        checks.append(
            DoctorCheck(
                id=f"consumers.{name}",
                status="pass",
                message=f"{name}: {'enabled' if enabled else 'disabled'}",
                detail={"consumer": name, "enabled": enabled},
            )
        )

    log_dir = resolve_log_dir_from_env()
    writable = probe_log_dir_writable(log_dir)
    checks.append(
        DoctorCheck(
            id="log_dir_writable",
            status="fail" if not writable else "pass",
            message=f"log directory {log_dir} writable: {'yes' if writable else 'no'}",
            detail={"path": str(log_dir), "writable": writable},
        )
    )

    myx_job = os.environ.get("MYX_JOB_ID", "").strip()
    bth_task = os.environ.get("BTH_TASK_ID", "").strip()
    if myx_job:
        checks.append(
            DoctorCheck(
                id="job_context",
                status="pass",
                message=f"task_id: {myx_job} (from MYX_JOB_ID)",
                detail={"source": "MYX_JOB_ID", "task_id": myx_job},
            )
        )
    elif bth_task:
        checks.append(
            DoctorCheck(
                id="job_context",
                status="pass",
                message=f"task_id: {bth_task} (from BTH_TASK_ID)",
                detail={"source": "BTH_TASK_ID", "task_id": bth_task},
            )
        )

    endpoint = os.environ.get("CISTERNAL_OTLP_ENDPOINT", "").strip()
    protocol = resolve_otlp_protocol()
    sdk_available = otlp_sdk_available()
    checks.append(
        DoctorCheck(
            id="otlp_config",
            status="pass",
            message="OTLP configuration",
            detail={
                "endpoint": endpoint or None,
                "protocol": protocol,
                "sdk_installed": sdk_available,
            },
        )
    )
    if endpoint and not sdk_available:
        checks.append(
            DoctorCheck(
                id="otlp_sdk",
                status="fail",
                message="CISTERNAL_OTLP_ENDPOINT is set but OTLP SDK is missing",
                detail={"endpoint": endpoint},
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="otlp_sdk",
                status="pass",
                message="OTLP SDK availability OK",
                detail={"endpoint": endpoint or None, "sdk_installed": sdk_available},
            )
        )

    pipeline = get_pipeline()
    if pipeline is None:
        pipeline_message = "inactive (expected unless cisternal.init() ran)"
    else:
        pipeline_message = "active"
    checks.append(
        DoctorCheck(
            id="pipeline",
            status="pass",
            message=f"pipeline status: {pipeline_message}",
            detail={"active": pipeline is not None},
        )
    )

    return DoctorReport(
        checks=tuple(checks),
        raw_telemetry=raw_telemetry,
        consumer_filter=consumer_filter,
    )


def format_doctor_report(report: DoctorReport | None = None) -> str:
    """Build human-readable telemetry doctor output."""
    if report is None:
        report = build_doctor_report()

    lines: list[str] = [
        "cisternal telemetry doctor",
        f"runbook: {report.runbook_path}",
        "",
        "CISTERNAL_TELEMETRY gate",
        f"  raw: {report.raw_telemetry or '(unset)'}",
    ]
    if report.consumer_filter is not None:
        lines.append(f"  target consumer: {report.consumer_filter}")

    for check in report.checks:
        if check.id.startswith("consumers."):
            lines.append(f"  {check.message}")

    log_check = _check_by_id(report, "log_dir_writable")
    if log_check is not None:
        path = (log_check.detail or {}).get("path", "")
        writable = (log_check.detail or {}).get("writable", False)
        lines.extend(
            [
                "",
                "JSONL log directory",
                f"  resolved: {path}",
                f"  writable: {'yes' if writable else 'no'}",
            ]
        )

    job_check = _check_by_id(report, "job_context")
    if job_check is not None:
        lines.extend(["", "job_span context", f"  {job_check.message}"])

    otlp_config = _check_by_id(report, "otlp_config")
    if otlp_config is not None:
        detail = otlp_config.detail or {}
        endpoint = detail.get("endpoint") or "(unset)"
        protocol = detail.get("protocol", "")
        sdk_state = "installed" if detail.get("sdk_installed") else "missing"
        lines.extend(
            [
                "",
                "OTLP egress",
                f"  CISTERNAL_OTLP_ENDPOINT: {endpoint}",
                f"  CISTERNAL_OTLP_PROTOCOL: {protocol}",
                f"  otlp_sdk: {sdk_state}",
            ]
        )

    pipeline_check = _check_by_id(report, "pipeline")
    if pipeline_check is not None:
        status = pipeline_check.message.removeprefix("pipeline status: ")
        lines.extend(["", "pipeline", f"  status: {status}"])

    return "\n".join(lines)


def format_doctor_json(report: DoctorReport, *, strict: bool) -> str:
    """Serialize *report* as JSON (schema_version 1)."""
    summary: dict[str, Any] = {
        "pass": 0,
        "warn": 0,
        "fail": 0,
        "strict": strict,
        "consumer_filter": report.consumer_filter,
    }
    checks_out: list[dict[str, Any]] = []
    for check in report.checks:
        summary[check.status] += 1
        eff = effective_check_status(check, strict=strict)
        item: dict[str, Any] = {
            "id": check.id,
            "status": check.status,
            "effective_status": eff,
            "message": check.message,
        }
        if check.detail is not None:
            item["detail"] = check.detail
        checks_out.append(item)

    payload = {
        "schema_version": _SCHEMA_VERSION,
        "checks": checks_out,
        "summary": summary,
    }
    return json.dumps(payload, sort_keys=True, indent=2)


def _check_by_id(report: DoctorReport, check_id: str) -> DoctorCheck | None:
    for check in report.checks:
        if check.id == check_id:
            return check
    return None
