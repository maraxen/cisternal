"""Tests for M4.3 / M11.1 / M11.2 subprocess validate (--use-native-cli) parity.

``--use-native-cli`` runs ``cisterna assets export`` in a subprocess and compares
the emitted file digest to goldens — not vendor IDE CLIs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)
SELF_MANIFEST = Path(".praxia/manifest.toml")
_SURFACES = ("claude", "cursor", "copilot", "antigravity")


def _invoke_app(args: list[str], *, exit_code: int = 0) -> None:
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code, (
        f"Expected exit {exit_code}; got {exc_info.value.code}"
    )


@pytest.mark.parametrize("surface", _SURFACES)
def test_native_cli_validate_manifest_minimal_names_only(surface: str) -> None:
    """AC-M4-3a / M11.2: --use-native-cli matches golden for manifest_minimal."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            surface,
            "--use-native-cli",
        ]
    )


def test_native_cli_validate_claude_with_bodies() -> None:
    """AC-M4-3c: subprocess path with emit_command_bodies (claude only)."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--surface",
            "claude",
            "--emit-command-bodies",
            "--use-native-cli",
        ]
    )


@pytest.mark.parametrize("surface", _SURFACES)
def test_native_cli_validate_self_manifest_names_only(surface: str) -> None:
    """AC-M11.1-3 / M11.2: self-manifest subprocess parity for each surface."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(SELF_MANIFEST),
            "--surface",
            surface,
            "--use-native-cli",
        ]
    )


def test_native_cli_validate_self_manifest_claude_with_bodies() -> None:
    """AC-M11.1-3: self-manifest claude with_command_bodies subprocess parity."""
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(SELF_MANIFEST),
            "--surface",
            "claude",
            "--emit-command-bodies",
            "--use-native-cli",
        ]
    )


@pytest.mark.parametrize("surface", _SURFACES)
def test_native_cli_matches_in_process_digest(surface: str) -> None:
    """AC-M4-3b / M11.2: in-process and native digests agree per surface."""
    from cisterna.assets.load import load_asset_report
    from cisterna.assets.validate_golden import surface_digest
    from cisterna.cli import _native_cli_surface_digest

    report = load_asset_report(manifest=FIXTURE_MANIFEST)
    in_proc = surface_digest(report.bundle, surface)
    native = _native_cli_surface_digest(
        registry="default",
        manifest=FIXTURE_MANIFEST,
        surface=surface,
        emit_command_bodies=False,
    )
    assert in_proc == native


def test_native_cli_zero_files_exits_one(tmp_path: Path) -> None:
    """AC-M4-3e: subprocess export with empty bundle → exit 1."""
    empty_manifest = tmp_path / "empty.toml"
    empty_manifest.write_text(
        """
[plugin]
name = "empty"
version = "0.0.0"
description = ""
requires_praxia = "0.0.0"
""".strip(),
        encoding="utf-8",
    )
    _invoke_app(
        [
            "assets",
            "validate",
            "--manifest",
            str(empty_manifest),
            "--surface",
            "claude",
            "--use-native-cli",
        ],
        exit_code=1,
    )
