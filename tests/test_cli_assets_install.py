"""Tests for `cisternal assets install` — export + real claude CLI registration."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

_FAKE_CLAUDE_SCRIPT = """#!/bin/sh
echo "$@" >> "$FAKE_CLAUDE_LOG"
if [ "$1" = "plugin" ] && [ "$2" = "$FAKE_CLAUDE_FAIL_STEP" ]; then
  echo "simulated failure at $2" >&2
  exit 1
fi
exit 0
"""


def _write_fake_claude(tmp_path: Path) -> Path:
    script = tmp_path / "fake-claude"
    script.write_text(_FAKE_CLAUDE_SCRIPT, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _write_manifest_with_marketplace(tmp_path: Path) -> Path:
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"

[plugin.marketplace]
name = "demo-marketplace"
""",
        encoding="utf-8",
    )
    return manifest_dir / "manifest.toml"


def _write_manifest_without_marketplace(tmp_path: Path) -> Path:
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"
""",
        encoding="utf-8",
    )
    return manifest_dir / "manifest.toml"


def _invoke_app(args: list[str], *, exit_code: int) -> None:
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code, (
        f"Expected exit {exit_code}; got: {exc_info.value.code}"
    )


def test_install_requires_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _invoke_app(["assets", "install", "--out", str(out_dir)], exit_code=2)


def test_install_requires_marketplace_table(tmp_path: Path) -> None:
    manifest = _write_manifest_without_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _invoke_app(
        ["assets", "install", "--manifest", str(manifest), "--out", str(out_dir)],
        exit_code=2,
    )


def test_install_dry_run_writes_nothing_and_prints_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--dry-run",
        ],
        exit_code=0,
    )

    assert list(out_dir.rglob("*")) == []
    captured = capsys.readouterr()
    assert "would run: claude plugin marketplace add" in captured.out
    assert "would run: claude plugin install demo-plugin@demo-marketplace --scope project" in captured.out


def test_install_runs_marketplace_add_and_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    log_path = tmp_path / "fake-claude.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    monkeypatch.delenv("FAKE_CLAUDE_FAIL_STEP", raising=False)

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
        ],
        exit_code=0,
    )

    assert (out_dir / ".claude-plugin" / "plugin.json").exists()
    assert (out_dir / ".claude-plugin" / "marketplace.json").exists()

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert log_lines[0] == f"plugin marketplace add {out_dir}"
    assert log_lines[1] == "plugin install demo-plugin@demo-marketplace --scope project"

    captured = capsys.readouterr()
    assert "Installed demo-plugin@demo-marketplace" in captured.out


def test_install_propagates_marketplace_add_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake-claude.log"))
    monkeypatch.setenv("FAKE_CLAUDE_FAIL_STEP", "marketplace")

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
        ],
        exit_code=1,
    )


def test_install_propagates_plugin_install_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake-claude.log"))
    monkeypatch.setenv("FAKE_CLAUDE_FAIL_STEP", "install")

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
        ],
        exit_code=1,
    )


def test_install_marketplace_name_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    log_path = tmp_path / "fake-claude.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    monkeypatch.delenv("FAKE_CLAUDE_FAIL_STEP", raising=False)

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
            "--marketplace-name",
            "override-marketplace",
            "--scope",
            "user",
        ],
        exit_code=0,
    )

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert log_lines[1] == "plugin install demo-plugin@override-marketplace --scope user"
