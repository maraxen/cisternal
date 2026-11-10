"""Tests for CLI cisternal skill-coverage command."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cisternal.cli import app


def test_cli_skill_coverage_synthetic_situations_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cisternal skill-coverage on synthetic situations fixture prints summary and exits 0."""
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                "tests/fixtures/situations/synthetic_situations.jsonl",
                "--threshold",
                "0.80",
            ]
        )
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "=== Cisternal Skill Coverage Evaluation ===" in captured.out
    assert "Matched turns (n): 60" in captured.out
    assert "Gate Status: PASS" in captured.out
    assert "Precision (p_hat): 1.0000" in captured.out


def test_cli_skill_coverage_json_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cisternal skill-coverage --json produces machine-readable JSON matching report schema."""
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                "tests/fixtures/situations/synthetic_situations.jsonl",
                "--json",
            ]
        )
    assert exc.value.code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_situations"] == 80
    assert data["matched_turns"] == 60
    assert data["status"] == "PASS"
    assert data["precision"] == 1.0
    assert "per_skill_stats" in data
    assert "triage-tool" in data["per_skill_stats"]


def test_cli_skill_coverage_situations_out(tmp_path: Path) -> None:
    """cisternal skill-coverage --situations-out writes valid evaluated JSONL."""
    out_file = tmp_path / "out_situations.jsonl"
    with pytest.raises(SystemExit) as exc:
        app(
            [
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                "tests/fixtures/situations/synthetic_situations.jsonl",
                "--situations-out",
                str(out_file),
            ]
        )
    assert exc.value.code == 0
    assert out_file.is_file()
    lines = [
        json.loads(line)
        for line in out_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 80
    assert lines[0]["id"] == "sit_export_trust_01"


def test_cli_skill_coverage_gate_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cisternal skill-coverage exits 1 when precision gate fails."""
    fail_file = tmp_path / "fail.jsonl"
    with open(fail_file, "w", encoding="utf-8") as f:
        # Create 60 items where none match expected
        for i in range(60):
            f.write(
                json.dumps(
                    {
                        "id": f"fail_{i}",
                        "prompt": "Run prune-list now",
                        "expected_skills": ["unexpected-skill"],
                    }
                )
                + "\n"
            )

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                str(fail_file),
                "--threshold",
                "0.80",
            ]
        )
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Gate Status: FAIL" in captured.out


def test_cli_validate_baseline_ref_invalid_exit_2(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """cisternal assets validate --baseline-ref exits 2 on unresolvable git ref."""
    with caplog.at_level(logging.ERROR, logger="cisternal.cli"):
        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "assets",
                    "validate",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--baseline-ref",
                    "nonexistent_ref_xyz123",
                ]
            )
        assert exc.value.code == 2
    err_output = caplog.text + capsys.readouterr().err
    assert "invalid baseline ref" in err_output
