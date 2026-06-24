"""AC-M7.2: export-dogfood workflow CI contract tests."""

from __future__ import annotations

from pathlib import Path

_WORKFLOW = Path(".github/workflows/export-dogfood.yml")


def test_otlp_collector_job_is_required() -> None:
    """AC-M7.2-1/6: otlp-collector job exists without continue-on-error."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "otlp-collector-advisory" not in text
    assert "  otlp-collector:" in text
    otlp_block = text[text.index("  otlp-collector:") :]
    assert "continue-on-error" not in otlp_block


def test_otlp_collector_ready_loop_checks_both_ports() -> None:
    """AC-M7.2-2b: ready loop probes gRPC 4317 and HTTP 4318."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    otlp_block = text[text.index("  otlp-collector:") :]
    assert "nc -z localhost 4317" in otlp_block
    assert "nc -z localhost 4318" in otlp_block
