"""Tests for cisternal.provenance.channels: precedence between env/sidecar/live-git."""

from __future__ import annotations

import json
import subprocess

import pytest

from cisternal.provenance.channels import (
    GitState,
    _same_root,
    capture_git_state,
)
from cisternal.provenance.record import PROVENANCE_FILENAME


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


@pytest.fixture(autouse=True)
def clear_myxcel_env(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("MYXCEL_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def clean_repo(tmp_path):
    return _init_repo(tmp_path)


class TestNoChannelFallsThroughToLegacyGit:
    def test_real_repo_no_channel(self, clean_repo):
        state = capture_git_state(clean_repo)
        assert state.provenance_source == "git"
        assert state.hash != "unknown"

    def test_non_repo_no_channel_returns_unknown_sentinel(self, tmp_path):
        state = capture_git_state(tmp_path)
        assert state.hash == "unknown"
        assert state.provenance_source == "none"


class TestEnvChannel:
    def test_env_channel_used_when_no_real_repo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "a" * 40)
        monkeypatch.setenv("MYXCEL_GIT_BRANCH", "main")
        monkeypatch.setenv("MYXCEL_GIT_DIRTY", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        assert state.provenance_source == "myxcel-env"
        assert state.hash == "a" * 40
        assert state.dirty is True

    def test_env_channel_scope_guard_rejects_outside_root(self, tmp_path, monkeypatch):
        other = tmp_path / "unrelated"
        other.mkdir()
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "a" * 40)
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path / "elsewhere"))
        state = capture_git_state(other)
        assert state.provenance_source == "none"

    def test_real_repo_at_provenance_root_beats_env_channel(self, clean_repo, monkeypatch):
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "b" * 40)  # deliberately wrong sha
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(clean_repo))
        state = capture_git_state(clean_repo)
        assert state.provenance_source == "git"
        assert state.hash != "b" * 40

    def test_ancestor_repo_at_different_root_does_not_beat_channel(self, tmp_path, monkeypatch):
        # A real repo exists, but NOT at the same root the channel describes.
        outer_repo = _init_repo(tmp_path)
        inner = outer_repo / "subdir"
        inner.mkdir()
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "c" * 40)
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(inner))
        state = capture_git_state(inner)
        # toplevel resolves to outer_repo, which != inner -> channel wins
        assert state.provenance_source == "myxcel-env"
        assert state.hash == "c" * 40

    def test_linked_worktree_of_channel_root_beats_env_channel(self, tmp_path, monkeypatch):
        """A linked worktree W of repo S, when given S as MYXCEL_PROVENANCE_ROOT,
        should record W's HEAD (with source="git"), not S's HEAD from the channel."""
        # Create primary repo S
        s_dir = tmp_path / "S"
        s_dir.mkdir()
        primary = _init_repo(s_dir)

        # Create a linked worktree W with a different commit
        worktree_dir = tmp_path / "W"
        subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "-b", "test-branch"],
            cwd=primary,
            check=True,
        )
        # Make a different commit in the worktree
        (worktree_dir / "b.txt").write_text("world\n")
        subprocess.run(["git", "add", "b.txt"], cwd=worktree_dir, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "worktree commit"],
            cwd=worktree_dir,
            check=True,
        )

        # Get the actual hashes
        primary_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=primary,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        worktree_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Verify they are different
        assert primary_head != worktree_head

        # Set up env vars pointing to the primary repo S
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", primary_head)  # Primary's HEAD
        monkeypatch.setenv("MYXCEL_GIT_BRANCH", "main")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(primary))

        # Capture from worktree -- should get worktree's HEAD with source="git"
        state = capture_git_state(worktree_dir)
        assert state.provenance_source == "git", (
            f"Expected source='git' (worktree's own HEAD) but got source='{state.provenance_source}' "
            f"with hash={state.hash}. This is the bug: the channel won over the linked worktree."
        )
        assert state.hash == worktree_head, (
            f"Expected hash={worktree_head} (worktree) but got {state.hash} (channel's primary HEAD)"
        )

    def test_unrelated_nested_repo_defers_to_env_channel(self, tmp_path, monkeypatch):
        """A DIFFERENT repo nested inside the channel root (not a worktree of it)
        should still defer to the channel."""
        # Create channel root with env vars
        channel_root = tmp_path / "S"
        channel_root.mkdir()
        primary = _init_repo(channel_root)

        # Create an unrelated repo nested inside (vendor/other is NOT a worktree of primary)
        nested = channel_root / "vendor" / "other"
        nested.mkdir(parents=True)
        nested_repo = _init_repo(nested)

        # Get nested repo's HEAD
        nested_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=nested_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Set up env vars pointing to channel root S (not the nested repo)
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "n" * 40)  # Deliberately wrong
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(channel_root))

        # Capture from nested repo -- should use channel, not nested repo
        # (because nested_repo.toplevel != channel_root)
        state = capture_git_state(nested_repo)
        assert state.provenance_source == "myxcel-env", (
            f"A nested but unrelated repo should defer to the channel. "
            f"Got source={state.provenance_source} instead."
        )
        assert state.hash == "n" * 40


class TestSidecarChannel:
    def test_sidecar_used_when_no_git_and_no_env(self, tmp_path):
        sidecar = tmp_path / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1, "provenance_status": "git", "git_sha": "d" * 40,
            "git_branch": "main", "git_dirty": False, "provenance_root": str(tmp_path),
        }))
        state = capture_git_state(tmp_path)
        assert state.provenance_source == "myxcel-sidecar"
        assert state.hash == "d" * 40

    def test_env_beats_sidecar_when_both_present(self, tmp_path, monkeypatch):
        sidecar = tmp_path / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1, "provenance_status": "git", "git_sha": "e" * 40,
            "provenance_root": str(tmp_path),
        }))
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "f" * 40)
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        assert state.provenance_source == "myxcel-env"
        assert state.hash == "f" * 40

    def test_sidecar_ascent_is_bounded_and_stops_at_git(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        repo = _init_repo(repo_dir)
        sidecar = tmp_path / PROVENANCE_FILENAME  # above the repo root
        sidecar.write_text(json.dumps({
            "schema_version": 1, "provenance_status": "git", "git_sha": "0" * 40,
            "provenance_root": str(tmp_path),
        }))
        # cwd is INSIDE the repo -- ascent must stop at repo's .git, never reaching
        # the sidecar one level further up.
        state = capture_git_state(repo)
        assert state.provenance_source == "git"

    def test_malformed_sidecar_falls_through(self, tmp_path):
        sidecar = tmp_path / PROVENANCE_FILENAME
        sidecar.write_text("not json")
        state = capture_git_state(tmp_path)
        assert state.hash == "unknown"
        assert state.provenance_source == "none"

    def test_future_schema_version_is_accepted_with_warning(self, tmp_path):
        sidecar = tmp_path / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 99, "provenance_status": "git", "git_sha": "1" * 40,
            "provenance_root": str(tmp_path),
        }))
        with pytest.warns(UserWarning):
            state = capture_git_state(tmp_path)
        assert state.hash == "1" * 40


class TestSameRoot:
    def test_identical_path(self, tmp_path):
        assert _same_root(tmp_path, tmp_path) is True

    def test_nonexistent_path_never_raises(self, tmp_path):
        assert _same_root(tmp_path / "nope", tmp_path / "also-nope") is False

    def test_different_real_directories(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert _same_root(a, b) is False


class TestStatusMapping:
    def test_nogit_status_maps_to_literal_nogit_hash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "nogit")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        assert state.hash == "nogit"

    def test_unavailable_status_maps_to_unknown_hash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "unavailable")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        assert state.hash == "unknown"


def test_capture_git_state_never_raises(tmp_path, monkeypatch):
    """C6: a provenance capture failure must never propagate to the caller."""
    monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
    monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
    # A root that cannot possibly resolve to a real directory (not an OS-level
    # invalid string, which os.environ itself rejects before this code runs).
    monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", "/nonexistent/" + "x" * 4000)
    state = capture_git_state(tmp_path)
    assert isinstance(state, GitState)
