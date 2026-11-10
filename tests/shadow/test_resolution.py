"""Tests for cisternal.shadow.resolution log-dir and mode-state resolution.

Covers the unified writer/reader env precedence, fail-closed env disable
semantics (empty / "none" disables, no fall-through), Layer-5 exit codes,
and config-file layers. repo_root and user_config_file are always passed
explicitly so the real repo and home are never consulted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.shadow.resolution import (
    LOG_DIR_ENV_VARS,
    ResolutionError,
    resolve_log_dir,
    resolve_mode_state_dir,
)
from cisternal.telemetry.pipeline import resolve_writer_log_dir

ALL_LOG_VARS = ("CISTERNAL_TELEMETRY_LOG_DIR", "CISTERNAL_LOG_DIR", "BTH_LOG_DIR", "CTXP_LOG_DIR")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*ALL_LOG_VARS, "CISTERNAL_MODE_STATE_DIR", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def isolated(tmp_path: Path) -> dict[str, Path]:
    """An empty repo root and a non-existent user config (Layers 3/4 absent)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    return {"repo_root": repo, "user_config_file": tmp_path / "nope.toml"}


def test_precedence_order_is_defined_once() -> None:
    assert LOG_DIR_ENV_VARS == (
        "CISTERNAL_TELEMETRY_LOG_DIR",
        "CISTERNAL_LOG_DIR",
        "BTH_LOG_DIR",
        "CTXP_LOG_DIR",
    )


@pytest.mark.parametrize("var", LOG_DIR_ENV_VARS)
def test_reader_and_writer_agree_for_each_single_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: dict[str, Path], var: str
) -> None:
    target = tmp_path / f"from_{var.lower()}"
    monkeypatch.setenv(var, str(target))
    reader = resolve_log_dir(cli_arg=None, **isolated)
    writer = resolve_writer_log_dir(**isolated)
    assert reader.path == target.resolve()
    assert reader.layer == 2
    assert writer == reader.path


def test_precedence_first_set_var_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: dict[str, Path]
) -> None:
    for var in LOG_DIR_ENV_VARS:
        monkeypatch.setenv(var, str(tmp_path / var))
    for winner_idx, var in enumerate(LOG_DIR_ENV_VARS):
        # Every var above the current winner is removed in turn.
        if winner_idx > 0:
            monkeypatch.delenv(LOG_DIR_ENV_VARS[winner_idx - 1])
        reader = resolve_log_dir(cli_arg=None, **isolated)
        assert reader.path == (tmp_path / var).resolve()
        assert resolve_writer_log_dir(**isolated) == reader.path


def test_bth_log_dir_is_honoured_by_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: dict[str, Path]
) -> None:
    """Repro from the bug report: writer used BTH_LOG_DIR, reader ignored it."""
    monkeypatch.setenv("CISTERNAL_TELEMETRY_LOG_DIR", str(tmp_path / "X"))
    monkeypatch.setenv("BTH_LOG_DIR", str(tmp_path / "B"))
    # CISTERNAL_TELEMETRY_LOG_DIR outranks BTH_LOG_DIR, so both sides pick X.
    assert resolve_log_dir(cli_arg=None, **isolated).path == (tmp_path / "X").resolve()
    assert resolve_writer_log_dir(**isolated) == (tmp_path / "X").resolve()
    monkeypatch.delenv("CISTERNAL_TELEMETRY_LOG_DIR")
    assert resolve_log_dir(cli_arg=None, **isolated).path == (tmp_path / "B").resolve()
    assert resolve_writer_log_dir(**isolated) == (tmp_path / "B").resolve()


@pytest.mark.parametrize("disabled", ["", "   ", "none", "NONE", " None "])
def test_empty_or_none_disables_log_dir_without_fallthrough(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: dict[str, Path], disabled: str
) -> None:
    # Later var and a pyproject layer are both set: neither may be used.
    monkeypatch.setenv("CISTERNAL_TELEMETRY_LOG_DIR", disabled)
    monkeypatch.setenv("BTH_LOG_DIR", str(tmp_path / "bth"))
    (isolated["repo_root"] / "pyproject.toml").write_text(
        '[tool.cisternal.telemetry]\nlog_dir = "/from/pyproject"\n', encoding="utf-8"
    )
    with pytest.raises(ResolutionError) as exc_info:
        resolve_log_dir(cli_arg=None, **isolated)
    assert exc_info.value.exit_code == 3
    assert "CISTERNAL_TELEMETRY_LOG_DIR" in str(exc_info.value)
    assert "Layer 5" in str(exc_info.value)


def test_disabled_writer_keeps_legacy_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: dict[str, Path]
) -> None:
    monkeypatch.setenv("CISTERNAL_LOG_DIR", "none")
    monkeypatch.setenv("BTH_LOG_DIR", str(tmp_path / "bth"))
    assert resolve_writer_log_dir(**isolated) == Path.home() / ".cisternal" / "logs"


def test_unconfigured_writer_keeps_legacy_default(isolated: dict[str, Path]) -> None:
    assert resolve_writer_log_dir(**isolated) == Path.home() / ".cisternal" / "logs"


def test_layer5_log_dir_exit_code_is_3(isolated: dict[str, Path]) -> None:
    with pytest.raises(ResolutionError) as exc_info:
        resolve_log_dir(cli_arg=None, **isolated)
    assert exc_info.value.exit_code == 3
    assert "Layer 5 (off)" in str(exc_info.value)


def test_pyproject_layer3_and_relative_path(isolated: dict[str, Path]) -> None:
    repo = isolated["repo_root"]
    (repo / "pyproject.toml").write_text(
        '[tool.cisternal.telemetry]\nlog_dir = "logs/here"\n', encoding="utf-8"
    )
    res = resolve_log_dir(cli_arg=None, **isolated)
    assert res.layer == 3
    assert res.path == (repo / "logs/here").resolve()


def test_user_config_layer4_relative_resolves_against_config_dir(
    tmp_path: Path, isolated: dict[str, Path]
) -> None:
    cfg_dir = tmp_path / "cfgdir"
    cfg_dir.mkdir()
    cfg = cfg_dir / "config.toml"
    cfg.write_text('[telemetry]\nlog_dir = "rel/logs"\n', encoding="utf-8")
    res = resolve_log_dir(cli_arg=None, repo_root=isolated["repo_root"], user_config_file=cfg)
    assert res.layer == 4
    assert res.path == (cfg_dir / "rel/logs").resolve()


def test_user_config_layer4_absolute_path(tmp_path: Path, isolated: dict[str, Path]) -> None:
    cfg = tmp_path / "config.toml"
    target = tmp_path / "abs_logs"
    cfg.write_text(f'[telemetry]\nlog_dir = "{target}"\n', encoding="utf-8")
    res = resolve_log_dir(cli_arg=None, repo_root=isolated["repo_root"], user_config_file=cfg)
    assert res.layer == 4
    assert res.path == target.resolve()


@pytest.mark.parametrize(
    "content",
    [
        "tool = 3\n",
        "[tool]\ncisternal = []\n",
        "[tool.cisternal]\ntelemetry = \"x\"\n",
    ],
)
def test_non_table_pyproject_values_exit_3(tmp_path: Path, content: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(content, encoding="utf-8")
    with pytest.raises(ResolutionError) as exc_info:
        resolve_log_dir(cli_arg=None, repo_root=repo, user_config_file=tmp_path / "nope.toml")
    assert exc_info.value.exit_code == 3


def test_malformed_pyproject_exit_3(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool\n", encoding="utf-8")
    with pytest.raises(ResolutionError) as exc_info:
        resolve_log_dir(cli_arg=None, repo_root=repo, user_config_file=tmp_path / "nope.toml")
    assert exc_info.value.exit_code == 3


def test_writer_falls_back_with_warning_on_malformed_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The writer never raises at startup; the reader still exits 3 (above)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool\n", encoding="utf-8")
    got = resolve_writer_log_dir(repo_root=repo, user_config_file=tmp_path / "nope.toml")
    assert got == Path.home() / ".cisternal" / "logs"
    assert "Malformed" in capsys.readouterr().err


def test_writer_never_raises_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Any resolver failure (e.g. deleted cwd -> FileNotFoundError) falls back, never raises."""
    import cisternal.shadow.resolution as res_mod

    def boom(**_: object) -> None:
        raise FileNotFoundError("cwd was deleted")

    monkeypatch.setattr(res_mod, "resolve_log_dir", boom)
    assert resolve_writer_log_dir() == Path.home() / ".cisternal" / "logs"
    assert "cwd was deleted" in capsys.readouterr().err


def test_malformed_user_config_exit_3(tmp_path: Path, isolated: dict[str, Path]) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[telemetry\n", encoding="utf-8")
    with pytest.raises(ResolutionError) as exc_info:
        resolve_log_dir(cli_arg=None, repo_root=isolated["repo_root"], user_config_file=cfg)
    assert exc_info.value.exit_code == 3


def test_non_table_user_config_exit_3(tmp_path: Path, isolated: dict[str, Path]) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('telemetry = "oops"\n', encoding="utf-8")
    with pytest.raises(ResolutionError) as exc_info:
        resolve_log_dir(cli_arg=None, repo_root=isolated["repo_root"], user_config_file=cfg)
    assert exc_info.value.exit_code == 3


# --- mode-state disable semantics -------------------------------------------


@pytest.mark.parametrize("disabled", ["", "none", "None"])
def test_mode_state_env_disable_does_not_fall_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated: dict[str, Path], disabled: str
) -> None:
    monkeypatch.setenv("CISTERNAL_MODE_STATE_DIR", disabled)
    (isolated["repo_root"] / "pyproject.toml").write_text(
        '[tool.cisternal.shadow]\nmode_state_dir = "ms"\n', encoding="utf-8"
    )
    with pytest.raises(ResolutionError) as exc_info:
        resolve_mode_state_dir(cli_arg=None, **isolated)
    assert exc_info.value.exit_code == 3
    assert "CISTERNAL_MODE_STATE_DIR" in str(exc_info.value)


def test_mode_state_pyproject_relative_and_layer5_exit_3(
    tmp_path: Path, isolated: dict[str, Path]
) -> None:
    repo = isolated["repo_root"]
    (repo / "pyproject.toml").write_text(
        '[tool.cisternal.shadow]\nmode_state_dir = "ms"\n', encoding="utf-8"
    )
    res = resolve_mode_state_dir(cli_arg=None, **isolated)
    assert res.layer == 3
    assert res.path == (repo / "ms").resolve()

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ResolutionError) as exc_info:
        resolve_mode_state_dir(cli_arg=None, repo_root=empty, user_config_file=tmp_path / "x.toml")
    assert exc_info.value.exit_code == 3
