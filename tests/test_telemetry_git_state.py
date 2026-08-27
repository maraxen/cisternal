"""Tests for cisternal.telemetry.git_state (spec 260827, AC-1/AC-2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cisternal.telemetry.git_state import GitState, capture_git_state


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh git repo with one commit."""
    _git(["init"], tmp_path)
    _git(["config", "user.email", "test@example.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    (tmp_path / "file.txt").write_text("hello\n")
    _git(["add", "file.txt"], tmp_path)
    _git(["commit", "-m", "initial"], tmp_path)
    return tmp_path


def test_clean_repo(repo: Path) -> None:
    """AC-1: a clean repo reports the real hash/branch, dirty=False."""
    state = capture_git_state(repo)
    assert state.provenance_source == "git"
    assert state.dirty is False
    assert state.dirty_content_id is None
    assert len(state.hash) == 40
    assert all(c in "0123456789abcdef" for c in state.hash)
    assert state.branch  # non-empty; exact name depends on git's default
    assert state.toplevel is not None
    assert Path(state.toplevel).resolve() == repo.resolve()


def test_dirty_repo(repo: Path) -> None:
    """AC-1/AC-2: an uncommitted edit reports dirty=True with a content id."""
    (repo / "file.txt").write_text("hello, modified\n")
    state = capture_git_state(repo)
    assert state.dirty is True
    assert state.dirty_content_id is not None
    assert state.provenance_source == "git"


def test_dirty_content_id_distinguishes_different_dirty_states(repo: Path) -> None:
    """AC-2: dirty_content_id differs for two different uncommitted states at
    the same commit -- proving it's content-addressable, not just a bool."""
    (repo / "file.txt").write_text("edit one\n")
    state_a = capture_git_state(repo)

    (repo / "file.txt").write_text("edit two, totally different\n")
    state_b = capture_git_state(repo)

    assert state_a.hash == state_b.hash  # same commit both times
    assert state_a.dirty and state_b.dirty
    assert state_a.dirty_content_id != state_b.dirty_content_id


def test_dirty_content_id_sees_untracked_files(repo: Path) -> None:
    """AC-2: an untracked file also changes dirty_content_id -- this is the
    specific case a bare `git write-tree` (no throwaway index) would miss."""
    state_clean = capture_git_state(repo)
    assert state_clean.dirty is False

    (repo / "untracked.txt").write_text("new file, never git add'ed\n")
    state_dirty = capture_git_state(repo)
    assert state_dirty.dirty is True
    assert state_dirty.dirty_content_id is not None

    (repo / "untracked.txt").write_text("different content\n")
    state_dirty_2 = capture_git_state(repo)
    assert state_dirty_2.dirty_content_id != state_dirty.dirty_content_id


def test_dirty_content_id_skipped_when_disabled(repo: Path) -> None:
    (repo / "file.txt").write_text("modified\n")
    state = capture_git_state(repo, compute_dirty_content_id=False)
    assert state.dirty is True
    assert state.dirty_content_id is None


def test_not_a_git_repo(tmp_path: Path) -> None:
    """AC-1: a plain directory (no .git) reports the nogit sentinel."""
    state = capture_git_state(tmp_path)
    assert state == GitState(
        hash="nogit", branch="nogit", dirty=False, provenance_source="nogit"
    )


def test_git_binary_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1: git binary unavailable reports the unavailable sentinel, never raises."""
    monkeypatch.setenv("PATH", "")
    state = capture_git_state(tmp_path)
    assert state == GitState(
        hash="unknown", branch="unknown", dirty=False, provenance_source="unavailable"
    )


def test_never_raises_on_unexpected_subprocess_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1: any unexpected internal failure degrades to the sentinel, never raises."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(subprocess, "run", _boom)
    state = capture_git_state(repo)
    assert state.hash == "unknown"
    assert state.provenance_source == "unavailable"


def test_default_cwd_is_process_cwd(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cwd=None defaults to Path.cwd(), not an error."""
    monkeypatch.chdir(repo)
    state = capture_git_state()
    assert state.provenance_source == "git"
