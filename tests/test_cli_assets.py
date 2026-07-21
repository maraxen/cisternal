"""Tests for AC-M3-8 — CLI asset export.

AC-M3-8:
  - export --import <module> populates the registry in-process and emits files to tmp out dir.
  - Empty registry → WARNING + exit 0.
  - --dry-run prints "path  sha256" lines and writes nothing.
  - import cisterna.cli works without fastmcp installed (fastmcp-free import path).

Note: cyclopts raises SystemExit(0) after successful execution.  All app() calls
are wrapped in ``pytest.raises(SystemExit)`` with an assertion that the exit code is 0.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers — write a temp tool module importable via sys.path injection
# ---------------------------------------------------------------------------


def _write_tool_module(tmp_path: Path, module_name: str, *, tool_names: list[str]) -> Path:
    """Write a Python module at tmp_path/<module_name>.py that registers @tool entries.

    Returns the path to the file.  The caller must add tmp_path to sys.path
    before importing.
    """
    lines = ["import cisterna\n"]
    for tool_name in tool_names:
        lines.append(
            f"\n@cisterna.tool\ndef {tool_name}(x: int) -> int:\n"
            f'    """Auto-registered tool {tool_name}."""\n'
            f"    return x\n"
        )
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("".join(lines), encoding="utf-8")
    return module_file


def _invoke_app(args: list[str]) -> None:
    """Invoke the cisterna CLI app; raise AssertionError on non-zero exit."""
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == 0, (
        f"Expected exit code 0; got: {exc_info.value.code}"
    )


# ---------------------------------------------------------------------------
# AC-M3-8a: --import populates registry and emits files
# ---------------------------------------------------------------------------


def test_export_import_populates_registry_and_emits_files(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """--import <module> side-effects fire and result in tool export.

    M13 note: the real Claude Code plugin.json schema has no ``commands``
    key (see ``cisterna.export.claude`` module docstring) — registry-derived
    commands never carry a body (``registry_bundle`` in
    ``cisterna.assets.source`` always sets ``body=""``), so they leave no
    trace in Claude's emitted files either. The "registry got populated"
    signal this test can still check is the absence of the empty-registry
    WARNING (contrast ``test_export_empty_registry_emits_warning_and_exits_zero``)
    plus a valid plugin.json with the new (commands-free) shape.
    """
    module_name = "test_tools_for_cli_ac8a"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _write_tool_module(tmp_path, module_name, tool_names=["my_cli_tool", "another_cli_tool"])

    sys.path.insert(0, str(tmp_path))
    try:
        sys.modules.pop(module_name, None)
        with caplog.at_level(logging.WARNING, logger="cisterna.cli"):
            _invoke_app(["assets", "export", "--import", module_name, "--out", str(out_dir)])
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any(
        "empty" in str(m).lower() or "registry" in str(m).lower()
        for m in warning_messages
    ), f"Unexpected empty-registry WARNING with tools registered: {warning_messages}"

    plugin_file = out_dir / ".claude-plugin" / "plugin.json"
    assert plugin_file.exists(), "plugin.json must be written to out dir"

    import json

    manifest = json.loads(plugin_file.read_text(encoding="utf-8"))
    assert "commands" not in manifest, "real plugin.json schema has no commands key"


# ---------------------------------------------------------------------------
# AC-M3-8b: empty registry → WARNING + exit 0
# ---------------------------------------------------------------------------


def test_export_empty_registry_emits_warning_and_exits_zero(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty registry emits a WARNING to cisterna.cli and returns with exit 0."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # _clear_all_registries autouse fixture ensures registry is empty.
    with caplog.at_level(logging.WARNING, logger="cisterna.cli"):
        _invoke_app(["assets", "export", "--out", str(out_dir)])

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "empty" in str(m).lower() or "registry" in str(m).lower()
        for m in warning_messages
    ), f"Expected WARNING about empty registry; got: {warning_messages}"


def test_export_empty_registry_still_writes_valid_manifest(tmp_path: Path) -> None:
    """Even with an empty registry, a valid (name-only) plugin.json is written."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(["assets", "export", "--out", str(out_dir)])

    import json

    plugin_file = out_dir / ".claude-plugin" / "plugin.json"
    assert plugin_file.exists()
    manifest = json.loads(plugin_file.read_text(encoding="utf-8"))
    # Must have the always-present fields.
    assert "name" in manifest
    assert "version" in manifest
    assert "description" in manifest
    # commands key must be absent when empty.
    assert "commands" not in manifest


# ---------------------------------------------------------------------------
# AC-M3-8c: --dry-run prints "path  sha256" and writes nothing
# ---------------------------------------------------------------------------


def test_export_dry_run_prints_path_sha256(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--dry-run prints 'path  sha256' lines and writes nothing."""
    module_name = "test_tools_for_cli_dryrun"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _write_tool_module(tmp_path, module_name, tool_names=["dryrun_tool"])

    sys.path.insert(0, str(tmp_path))
    try:
        sys.modules.pop(module_name, None)
        _invoke_app(
            [
                "assets",
                "export",
                "--dry-run",
                "--import",
                module_name,
                "--out",
                str(out_dir),
            ]
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)

    # No files written.
    all_written = list(out_dir.rglob("*"))
    assert all_written == [], f"--dry-run must write nothing; found: {all_written}"

    # Stdout should have lines of the form "path  sha256".
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) >= 1, f"Expected at least one output line; got: {captured.out!r}"
    for line in lines:
        parts = line.split("  ", 1)
        assert len(parts) == 2, f"Expected 'path  sha256' format; got: {line!r}"
        _path_part, sha256_part = parts
        assert len(sha256_part) == 64, f"sha256 should be 64 hex chars; got: {sha256_part!r}"


def test_export_dry_run_empty_registry_writes_nothing(tmp_path: Path) -> None:
    """--dry-run with empty registry also writes nothing."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(["assets", "export", "--dry-run", "--out", str(out_dir)])

    all_written = list(out_dir.rglob("*"))
    assert all_written == [], f"--dry-run must write nothing; found: {all_written}"


# ---------------------------------------------------------------------------
# AC-M3-8d: --name and --version flags set bundle metadata
# ---------------------------------------------------------------------------


def test_export_custom_name_and_version(tmp_path: Path) -> None:
    """--name and --version set the bundle metadata fields."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(
        [
            "assets",
            "export",
            "--name",
            "custom-plugin",
            "--version",
            "9.9.9",
            "--out",
            str(out_dir),
        ]
    )

    import json

    manifest = json.loads(
        (out_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "custom-plugin"
    assert manifest["version"] == "9.9.9"


# ---------------------------------------------------------------------------
# AC-M3-8e: cisterna.cli importable (M4 fastmcp-free path)
# ---------------------------------------------------------------------------


def test_cli_module_has_no_top_level_fastmcp_import() -> None:
    """cisterna.cli must not import fastmcp at the top level (M4 fastmcp-free path)."""
    import cisterna.cli as _cli_mod

    source = inspect.getsource(_cli_mod)
    lines = source.splitlines()

    # Identify top-level (non-indented) import lines that reference fastmcp.
    top_level_fastmcp_imports = [
        line
        for line in lines
        if line and not line[0].isspace()
        and (line.strip().startswith("import fastmcp") or line.strip().startswith("from fastmcp"))
    ]

    assert top_level_fastmcp_imports == [], (
        f"cisterna.cli must not have top-level fastmcp imports; found: {top_level_fastmcp_imports}"
    )


def test_cli_importable_without_fastmcp() -> None:
    """import cisterna.cli must succeed (verified by import in-process)."""
    mod = importlib.import_module("cisterna.cli")
    assert hasattr(mod, "app"), "cisterna.cli must export 'app'"
