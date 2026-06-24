"""AC-M7.2 / M12.1: export-dogfood workflow CI contract tests."""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = Path(".github/workflows/export-dogfood.yml")
_NEXT_JOB = re.compile(r"\n  [a-z][\w-]*:")


def _job_block(text: str, job_name: str) -> str:
    marker = f"  {job_name}:"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    match = _NEXT_JOB.search(rest)
    if match is None:
        return text[start:]
    return text[start : start + len(marker) + match.start()]


def test_otlp_collector_job_is_required() -> None:
    """AC-M7.2-1/6: otlp-collector job exists without continue-on-error."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "otlp-collector-advisory" not in text
    assert "  otlp-collector:" in text
    otlp_block = _job_block(text, "otlp-collector")
    assert "continue-on-error" not in otlp_block


def test_otlp_collector_ready_loop_checks_both_ports() -> None:
    """AC-M7.2-2b: ready loop probes gRPC 4317 and HTTP 4318."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    otlp_block = _job_block(text, "otlp-collector")
    assert "nc -z localhost 4317" in otlp_block
    assert "nc -z localhost 4318" in otlp_block


def test_rust_parity_advisory_job_is_non_blocking() -> None:
    """AC-M12-1k: rust-parity-advisory exists with continue-on-error."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "  rust-parity-advisory:" in text
    block = _job_block(text, "rust-parity-advisory")
    assert "continue-on-error: true" in block
    assert "CISTERNA_PRAXIA_ASSETS_REV" in block
    assert "bundle-hash" in block
