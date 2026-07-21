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


def test_rust_parity_job_is_blocking() -> None:
    """AC-M12-4a: rust-parity job exists without continue-on-error."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "  rust-parity-advisory:" not in text
    assert "  rust-parity:" in text
    block = _job_block(text, "rust-parity")
    assert "continue-on-error" not in block
    assert "CISTERNAL_PRAXIA_ASSETS_REV" in block
    assert "bundle-hash" in block


def test_native_validate_job_covers_all_surfaces() -> None:
    """AC-M11.2-1: native-validate runs self-manifest subprocess parity for 4 surfaces."""
    text = _WORKFLOW.read_text(encoding="utf-8")
    block = _job_block(text, "native-validate")
    assert "for surface in claude cursor copilot antigravity" in block
    assert "--use-native-cli" in block
    assert "--emit-command-bodies" in block
    assert "continue-on-error" not in block
