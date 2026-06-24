"""Tests for M10.1 / M10.2 / M10.4 ``cisterna telemetry doctor``."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from cisterna.probe.telemetry_doctor import (
    build_doctor_report,
    compute_doctor_exit_code,
    effective_check_status,
    format_doctor_json,
    format_doctor_report,
    resolve_doctor_consumer,
    resolve_doctor_strict_mode,
)
from cisterna.telemetry.pipeline import resolve_log_dir_from_env


def _check(report, check_id: str):
    for item in report.checks:
        if item.id == check_id:
            return item
    raise AssertionError(f"missing check {check_id!r}")


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


def test_build_doctor_report_telemetry_gate_warn_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.2-4: unset telemetry gate warns."""
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    report = build_doctor_report()
    gate = _check(report, "telemetry_gate")
    assert gate.status == "warn"


def test_build_doctor_report_telemetry_gate_pass_for_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_TELEMETRY", "all")
    report = build_doctor_report()
    assert _check(report, "telemetry_gate").status == "pass"


def test_build_doctor_report_telemetry_gate_warn_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bogus")
    report = build_doctor_report()
    assert _check(report, "telemetry_gate").status == "warn"


def test_compute_exit_code_warn_only_default_lenient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.2-2: warnings do not fail exit by default."""
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    report = build_doctor_report()
    assert compute_doctor_exit_code(report, strict=False) == 0


def test_compute_exit_code_strict_promotes_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.2-3: strict promotes telemetry_gate warn to fail."""
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    report = build_doctor_report()
    assert compute_doctor_exit_code(report, strict=True) == 1


def test_resolve_doctor_strict_mode_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_DOCTOR_STRICT", "true")
    assert resolve_doctor_strict_mode(cli_strict=False) is True
    assert resolve_doctor_strict_mode(cli_strict=True) is True


def test_format_doctor_json_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-M10.2-1: JSON schema fields."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    report = build_doctor_report()
    payload = json.loads(format_doctor_json(report, strict=False))
    assert payload["schema_version"] == 1
    assert payload["summary"]["strict"] is False
    assert isinstance(payload["checks"], list)
    gate = next(c for c in payload["checks"] if c["id"] == "telemetry_gate")
    assert gate["status"] == "pass"
    assert gate["effective_status"] == "pass"


def test_format_doctor_json_strict_effective_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    report = build_doctor_report()
    payload = json.loads(format_doctor_json(report, strict=True))
    gate = next(c for c in payload["checks"] if c["id"] == "telemetry_gate")
    assert gate["status"] == "warn"
    assert gate["effective_status"] == "fail"
    assert payload["summary"]["strict"] is True


def test_effective_check_status_promotion() -> None:
    from cisterna.probe.telemetry_doctor import DoctorCheck

    check = DoctorCheck(id="x", status="warn", message="m")
    assert effective_check_status(check, strict=False) == "warn"
    assert effective_check_status(check, strict=True) == "fail"


def test_doctor_cli_json_only_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-M10.2-1: --json emits JSON only."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--json"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "cisterna telemetry doctor" not in out
    payload = json.loads(out)
    assert payload["schema_version"] == 1


def test_doctor_cli_strict_exit_one_when_telemetry_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--strict"])
    assert exc_info.value.code == 1


def test_doctor_cli_strict_env_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CISTERNA_TELEMETRY", raising=False)
    monkeypatch.setenv("CISTERNA_DOCTOR_STRICT", "1")
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--json"])
    assert exc_info.value.code == 1


def test_ci_preflight_env_passes_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.3: export-dogfood doctor step env (CISTERNA_TELEMETRY=all + --strict)."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "all")
    monkeypatch.delenv("CISTERNA_DOCTOR_STRICT", raising=False)
    report = build_doctor_report()
    assert compute_doctor_exit_code(report, strict=True) == 0


def test_resolve_doctor_consumer_cli_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.4: CLI --consumer wins over CISTERNA_DOCTOR_CONSUMER."""
    monkeypatch.setenv("CISTERNA_DOCTOR_CONSUMER", "bathos")
    assert resolve_doctor_consumer(cli_consumer="contemplex") == "contemplex"


def test_resolve_doctor_consumer_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_DOCTOR_CONSUMER", "Xperiri")
    assert resolve_doctor_consumer(cli_consumer=None) == "xperiri"


def test_resolve_doctor_consumer_invalid_raises() -> None:
    with pytest.raises(ValueError, match="unknown consumer"):
        resolve_doctor_consumer(cli_consumer="bogus")


def test_build_doctor_report_scoped_gate_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.4: scoped gate passes when target consumer enabled."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "contemplex")
    report = build_doctor_report(consumer_filter="contemplex")
    assert report.consumer_filter == "contemplex"
    gate = _check(report, "telemetry_gate")
    assert gate.status == "pass"
    assert "target contemplex: enabled" in gate.message
    assert gate.detail == {"raw": "contemplex", "target_consumer": "contemplex"}


def test_build_doctor_report_scoped_gate_warn_when_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.4: scoped gate warns when target consumer disabled."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    report = build_doctor_report(consumer_filter="contemplex")
    gate = _check(report, "telemetry_gate")
    assert gate.status == "warn"
    assert "target contemplex: disabled" in gate.message


def test_build_doctor_report_scoped_gate_all_enables_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_TELEMETRY", "all")
    report = build_doctor_report(consumer_filter="myxcel")
    assert _check(report, "telemetry_gate").status == "pass"


def test_format_doctor_report_shows_target_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_TELEMETRY", "contemplex")
    report = build_doctor_report(consumer_filter="contemplex")
    text = format_doctor_report(report)
    assert "target consumer: contemplex" in text


def test_format_doctor_json_consumer_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.4: JSON summary includes consumer_filter."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "contemplex")
    report = build_doctor_report(consumer_filter="contemplex")
    payload = json.loads(format_doctor_json(report, strict=False))
    assert payload["summary"]["consumer_filter"] == "contemplex"


def test_doctor_cli_invalid_consumer_exit_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-M10.4: invalid consumer exits 2 before report."""
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--consumer", "bogus"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown consumer" in captured.err


def test_doctor_cli_invalid_consumer_json_no_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--consumer", "bogus", "--json"])
    assert exc_info.value.code == 2
    assert capsys.readouterr().out == ""


def test_doctor_cli_consumer_strict_contemplex_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-M10.4: cutover gate scoped to one consumer."""
    monkeypatch.setenv("CISTERNA_TELEMETRY", "bathos")
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--consumer", "contemplex", "--strict"])
    assert exc_info.value.code == 1


def test_doctor_cli_consumer_strict_pass_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CISTERNA_TELEMETRY", "contemplex")
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(["telemetry", "doctor", "--consumer", "contemplex", "--json", "--strict"])
    assert exc_info.value.code == 0
