"""Tests for M3.1a inspect CLI (AC-M31a-7, AC-M31a-10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def _invoke_app(args: list[str], *, exit_code: int = 0) -> None:
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code, (
        f"Expected exit {exit_code}; got {exc_info.value.code}"
    )


def test_inspect_help() -> None:
    """inspect --help exits zero."""
    from cisternal.cli import assets_app

    with pytest.raises(SystemExit) as exc_info:
        assets_app(["inspect", "--help"])
    assert exc_info.value.code == 0


def test_inspect_prints_json_no_writes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-M31a-7: inspect prints JSON LoadReport; writes no files."""
    marker = tmp_path / "marker"
    marker.write_text("untouched", encoding="utf-8")

    _invoke_app(
        [
            "assets",
            "inspect",
            "--manifest",
            str(FIXTURE_MANIFEST),
        ]
    )

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["bundle"]["metadata"]["name"] == "fixture-plugin"
    assert data["warnings"] == []
    assert data["conflicts"] == []
    assert marker.read_text(encoding="utf-8") == "untouched"


def test_inspect_resolve_tools_enriches_agents(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-M31a-10: --resolve-tools adds concrete tools for agents."""
    _invoke_app(
        [
            "assets",
            "inspect",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--resolve-tools",
            "--surface",
            "claude_code",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    resolved = data["resolved_tools"]
    assert "recon" in resolved
    assert resolved["recon"] == ["Glob", "Grep", "Read"]


def test_inspect_resolve_tools_requires_surface() -> None:
    """--resolve-tools without --surface exits 2."""
    _invoke_app(
        [
            "assets",
            "inspect",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--resolve-tools",
        ],
        exit_code=2,
    )
