"""Tests for M10.1 ``cisterna telemetry doctor``."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from cisterna.probe.telemetry_doctor import format_doctor_report
from cisterna.telemetry.pipeline import resolve_log_dir_from_env


def test_resolve_log_dir_from_env_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M10.1-2: env precedence matches init_pipeline contract."""
    monkeypatch.delenv("CISTERNA_LOG_DIR", raising=False)
    monkeypatch.delenv("BTH_LOG_DIR", raising=False)
    monkeypatch.delenv("CTXP_LOG_DIR", raising=False)
    default = resolve_log_dir_from_env()
    assert default.name == "logs"
    assert default.parent.name == ".cisterna"

    monkeypatch.setenv("CTXP_LOG_DIR", "/ctxp/logs")
    assert resolve_log_dir_from_env() == Path("/ctxp/logs")

    monkeypatch.setenv("BTH_LOG_DIR", "/bth/logs")
    assert resolve_log_dir_from_env() == Path("/bth/logs")

    monkeypatch.setenv("CISTERNA_LOG_DIR", "/cisterna/logs")
    assert resolve_log_dir_from_env() == Path("/cisterna/logs")


def test_doctor_consumer_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M10.1-1: per-consumer enabled state from CISTERNA_TELEMETRY."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "contemplex")
    report = format_doctor_report()
    assert "raw: contemplex" in report
    assert "contemplex: enabled" in report
    assert "bathos: disabled" in report


def test_doctor_all_consumers_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CISTERNA_TELEMETRY", "all")
    report = format_doctor_report()
    for consumer in ("bathos", "contemplex", "xperiri", "myxcel"):
        assert f"{consumer}: enabled" in report


def test_doctor_log_dir_and_otlp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-M10.1-2/3: resolved log dir and OTLP lines."""
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("CISTERNA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("CISTERNA_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("CISTERNA_OTLP_PROTOCOL", "grpc")

    report = format_doctor_report()
    assert f"resolved: {log_dir}" in report
    assert "writable: yes" in report
    assert "CISTERNA_OTLP_ENDPOINT: http://localhost:4317" in report
    assert "CISTERNA_OTLP_PROTOCOL: grpc" in report
    assert "otlp_sdk: installed" in report


def test_doctor_job_context_myx(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M10.1-2b: MYX_JOB_ID takes precedence."""
    monkeypatch.setenv("MYX_JOB_ID", "job-42")
    monkeypatch.setenv("BTH_TASK_ID", "task-99")
    report = format_doctor_report()
    assert "task_id: job-42 (from MYX_JOB_ID)" in report


def test_doctor_job_context_bth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYX_JOB_ID", raising=False)
    monkeypatch.setenv("BTH_TASK_ID", "task-99")
    report = format_doctor_report()
    assert "task_id: task-99 (from BTH_TASK_ID)" in report


def test_doctor_pipeline_inactive() -> None:
    """AC-M10.1-4: CLI doctor reports inactive pipeline without init."""
    report = format_doctor_report()
    assert "inactive (expected unless cisterna.init() ran)" in report


def test_doctor_cli_invocation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-M10.1-0: cyclopts entry runs and prints report."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "cisterna telemetry doctor" in out
    assert "bathos: enabled" in out
    assert "runbook:" in out


def test_doctor_help_references_runbook(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-M10.1-6: help text references operator runbook path."""
    from cisterna.cli import app

    with pytest.raises(SystemExit):
        app(["telemetry", "doctor", "--help"])
    out = capsys.readouterr().out
    assert "cisterna-telemetry.md" in out


def test_cli_still_fastmcp_free() -> None:
    """AC-M10.1-5: doctor wiring does not add top-level fastmcp imports."""
    import inspect

    import cisterna.cli as cli_mod

    source = inspect.getsource(cli_mod)
    top_level = [
        line
        for line in source.splitlines()
        if line and not line[0].isspace()
        and (line.strip().startswith("import fastmcp") or line.strip().startswith("from fastmcp"))
    ]
    assert top_level == []
    mod = importlib.import_module("cisterna.cli")
    assert hasattr(mod, "telemetry_app")
