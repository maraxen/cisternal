"""Tests for cisternal.provenance.channels: precedence between env/sidecar/live-git."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import warnings

import pytest

from cisternal.provenance.channels import (
    GitState,
    _same_root,
    capture_git_state,
)
from cisternal.provenance.record import PROVENANCE_FILENAME
from cisternal.provenance.tree_manifest import build_tree_manifest


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _make_verified_tree(tmp_path):
    """Create a git repo with a verified tree manifest, suitable for testing.

    Returns (remote, head_sha) where:
    - repo is the original git repo (with .git)
    - remote is a copy of the repo without .git, containing a PROVENANCE_FILENAME sidecar
    - head_sha is the commit SHA
    """
    # Create the primary repo
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo = _init_repo(repo_path)

    # Add a couple more files
    (repo / "src").mkdir()
    (repo / "src" / "pkg").mkdir()
    (repo / "src" / "pkg" / "a.py").write_text("print('hello')\n")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "run.py").write_text("#!/usr/bin/env python3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add src and scripts"], cwd=repo, check=True)

    # Get the commit SHA
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Build the tree manifest
    manifest = build_tree_manifest(repo, commit=head_sha)
    assert manifest is not None, "Failed to build tree manifest"

    # Create a remote copy without .git
    remote = tmp_path / "remote"
    shutil.copytree(repo, remote, ignore=shutil.ignore_patterns(".git"))

    # Write the sidecar with the manifest
    sidecar_path = remote / PROVENANCE_FILENAME
    sidecar_path.write_text(json.dumps({
        "schema_version": 2,
        "provenance_status": "git",
        "git_sha": head_sha,
        "git_branch": "main",
        "git_dirty": False,
        "dirty_content_id": None,
        "provenance_root": str(remote),
        "capture_stage": "push",
        "sync_state": "verified",
        "computed_at": "2026-09-29T00:00:00+00:00",
        "remote": "test",
        "project": "test",
        "worktree": None,
        "tree_manifest": manifest.to_dict(),
    }))

    return remote, head_sha


@pytest.fixture(autouse=True)
def clear_myxcel_env(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("MYXCEL_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def clear_warned_sidecars(monkeypatch):
    """Clear the _WARNED set before each test so warnings are re-emitted."""
    from cisternal.provenance import channels
    monkeypatch.setattr(channels, "_WARNED", set())


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
        """Env channel without a verified manifest → withheld."""
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "a" * 40)
        monkeypatch.setenv("MYXCEL_GIT_BRANCH", "main")
        monkeypatch.setenv("MYXCEL_GIT_DIRTY", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        # Without a manifest, the sha is withheld
        assert state.provenance_source == "unverified-env"
        assert state.hash == "unknown"
        assert state.code_verified is None
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
        """A different repo nested inside the channel root (not a worktree of it)
        should defer to the channel, but without a manifest the sha is withheld."""
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
        # But without a manifest, the sha is withheld
        assert state.provenance_source == "unverified-env"
        assert state.hash == "unknown"
        assert state.code_verified is None

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
        should defer to the channel precedence; without manifest the sha is withheld."""
        # Create channel root with env vars
        channel_root = tmp_path / "S"
        channel_root.mkdir()
        _init_repo(channel_root)

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
        # Env channel precedence is preserved, but without manifest the sha is withheld
        assert state.provenance_source == "unverified-env", (
            f"A nested but unrelated repo should defer to the channel. "
            f"Got source={state.provenance_source} instead."
        )
        assert state.hash == "unknown", "unverified-env must withhold the sha"
        assert state.hash != nested_head, "nested repo's own HEAD must not win over the channel"


class TestSidecarChannel:
    def test_sidecar_used_when_no_git_and_no_env(self, tmp_path):
        """Sidecar precedence is preserved, but without manifest the sha is withheld."""
        sidecar = tmp_path / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1, "provenance_status": "git", "git_sha": "d" * 40,
            "git_branch": "main", "git_dirty": False, "provenance_root": str(tmp_path),
        }))
        state = capture_git_state(tmp_path)
        # Without a manifest, the sha is withheld
        assert state.provenance_source == "unverified-sidecar"
        assert state.hash == "unknown"
        assert state.code_verified is None

    def test_env_beats_sidecar_when_both_present(self, tmp_path, monkeypatch):
        """Env precedence is preserved, but without manifest both are withheld."""
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
        # Env precedence is preserved, but without manifest the sha is withheld
        assert state.provenance_source == "unverified-env"
        assert state.hash == "unknown"
        assert state.code_verified is None

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
        """Future schema version warns but is still processed (for forward compat)."""
        sidecar = tmp_path / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 3, "provenance_status": "git", "git_sha": "1" * 40,
            "provenance_root": str(tmp_path),
        }))
        with pytest.warns(UserWarning):
            state = capture_git_state(tmp_path)
        # Without a manifest, the sha is withheld even with future schema
        assert state.hash == "unknown"
        assert state.provenance_source == "unverified-sidecar"


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
        """nogit status surfaces hash='nogit' without verification."""
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "nogit")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        assert state.hash == "nogit"
        assert state.code_verified is None  # nogit doesn't need verification

    def test_unavailable_status_maps_to_unknown_hash(self, tmp_path, monkeypatch):
        """unavailable status maps to unknown hash."""
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "unavailable")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        state = capture_git_state(tmp_path)
        assert state.hash == "unknown"
        assert state.code_verified is None


def test_capture_git_state_never_raises(tmp_path, monkeypatch):
    """C6: a provenance capture failure must never propagate to the caller."""
    monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "1")
    monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
    # A root that cannot possibly resolve to a real directory (not an OS-level
    # invalid string, which os.environ itself rejects before this code runs).
    monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", "/nonexistent/" + "x" * 4000)
    state = capture_git_state(tmp_path)
    assert isinstance(state, GitState)


class TestVerificationGating:
    """Tests for the hard rule: sidecar/env shas surface only when verified."""

    def test_real_protamer_fixture_unverified_sidecar_withheld(self, tmp_path):
        """Real fixture from debt #2060: protamer/git_sha=9d0b875, no valid manifest."""
        fixture_dir = tmp_path / "protamer"
        fixture_dir.mkdir()
        # Create some unrelated files
        (fixture_dir / "src").mkdir()
        (fixture_dir / "src" / "x.py").write_text("x=1\n")
        # Write the real fixture (verbatim)
        sidecar = fixture_dir / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "capture_stage": "push",
            "computed_at": "2026-08-28T13:55:00+00:00",
            "dirty_content_id": "tree:3f3563fdff04c08552315284c53d2288ce2d9c69",
            "git_branch": "feat/chi-bb-scale-confirmatory",
            "git_dirty": True,
            "git_sha": "9d0b87513d484cdf103199d48450c5c5af42e6ef",
            "myxcel_version": "0.1.0",
            "project": "protamer",
            "provenance_root": str(fixture_dir),
            "provenance_status": "git",
            "remote": "titanix",
            "schema_version": 1,
            "sync_state": "verified",
            "worktree": None,
        }))

        state = capture_git_state(fixture_dir)
        assert state.hash == "unknown"
        assert state.sha is None
        assert state.provenance_source == "unverified-sidecar"
        assert state.code_verified is None
        # The sha must not leak anywhere
        state_repr = repr(state)
        assert "9d0b875" not in state_repr
        state_dict = dataclasses.asdict(state, dict_factory=dict)
        state_json = json.dumps(state_dict, default=str)
        assert "9d0b875" not in state_json
        assert state.branch == "unknown"
        assert state.dirty is True
        assert state.dirty_content_id is None

        # Check that a warning was emitted and contains no sha
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from cisternal.provenance import channels
            channels._WARNED.clear()  # Reset to force re-warning
            capture_git_state(fixture_dir)
            assert len(w) >= 1
            # The warning text must not contain the sha
            warning_text = str(w[-1].message)
            assert "9d0b875" not in warning_text

    def test_verified_tree_surfaces_sha(self, tmp_path):
        """An untouched, verified tree surfaces the sha with code_verified=True."""
        remote, head_sha = _make_verified_tree(tmp_path)

        state = capture_git_state(remote)
        assert state.hash == head_sha
        assert state.sha == head_sha
        assert state.provenance_source == "myxcel-sidecar"
        assert state.code_verified is True
        assert state.verification is not None
        assert state.verification.verified is True
        assert state.dirty is False

    def test_modified_file_withheld(self, tmp_path):
        """File modified after manifest was written → withheld, code_verified=False."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # Modify a file
        (remote / "src" / "pkg" / "a.py").write_text("print('modified')\n")

        state = capture_git_state(remote)
        assert state.hash == "unknown"
        assert state.code_verified is False
        assert state.verification is not None
        assert state.verification.verified is False
        assert len(state.verification.mismatched) > 0
        assert "src/pkg/a.py" in state.verification.mismatched

    def test_manifest_commit_mismatch_withheld(self, tmp_path):
        """Manifest commit != git_sha → withheld, code_verified=False."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # Edit the sidecar to have a different git_sha
        sidecar = remote / PROVENANCE_FILENAME
        data = json.loads(sidecar.read_text())
        data["git_sha"] = "b" * 40
        sidecar.write_text(json.dumps(data))

        state = capture_git_state(remote)
        assert state.hash == "unknown"
        assert state.code_verified is False

    def test_dirty_record_true_surfaces_with_dirty_true(self, tmp_path):
        """Verified tree but git_dirty=true → surfaces with dirty=True."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # Set git_dirty=true in the sidecar
        sidecar = remote / PROVENANCE_FILENAME
        data = json.loads(sidecar.read_text())
        data["git_dirty"] = True
        sidecar.write_text(json.dumps(data))

        state = capture_git_state(remote)
        assert state.hash == head_sha
        assert state.code_verified is True
        assert state.dirty is True

    def test_missing_git_dirty_means_dirty_true(self, tmp_path):
        """Missing git_dirty field → dirty=True (fail-safe)."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # Remove git_dirty from the sidecar
        sidecar = remote / PROVENANCE_FILENAME
        data = json.loads(sidecar.read_text())
        del data["git_dirty"]
        sidecar.write_text(json.dumps(data))

        state = capture_git_state(remote)
        assert state.hash == head_sha
        assert state.code_verified is True
        assert state.dirty is True

    def test_sha_property_returns_none_for_unknown(self, tmp_path):
        """For unverified sidecars, sha property returns None."""
        fixture_dir = tmp_path / "protamer"
        fixture_dir.mkdir()
        sidecar = fixture_dir / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1,
            "provenance_status": "git",
            "git_sha": "9d0b87513d484cdf103199d48450c5c5af42e6ef",
            "git_branch": "main",
            "provenance_root": str(fixture_dir),
        }))

        state = capture_git_state(fixture_dir)
        assert state.sha is None
        assert state.hash == "unknown"

    def test_env_channel_no_manifest_withheld(self, tmp_path, monkeypatch):
        """Env channel with no sidecar manifest at root → withheld."""
        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "2")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "a" * 40)
        monkeypatch.setenv("MYXCEL_GIT_BRANCH", "main")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(tmp_path))
        # No sidecar at tmp_path, so no manifest to read

        state = capture_git_state(tmp_path)
        assert state.hash == "unknown"
        assert state.code_verified is None
        assert state.provenance_source == "unverified-env"

    def test_env_sha_mismatch_with_sidecar_withheld(self, tmp_path, monkeypatch):
        """Env SHA != sidecar SHA with verified sidecar → withheld, code_verified=False."""
        remote, head_sha = _make_verified_tree(tmp_path)

        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "2")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", "c" * 40)  # Different from sidecar
        monkeypatch.setenv("MYXCEL_GIT_BRANCH", "main")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(remote))

        state = capture_git_state(remote)
        assert state.hash == "unknown"
        assert state.code_verified is False
        assert state.provenance_source == "unverified-env"

    def test_env_channel_with_valid_sidecar_surfaces(self, tmp_path, monkeypatch):
        """Env channel pointing to a verified sidecar → surfaces."""
        remote, head_sha = _make_verified_tree(tmp_path)

        monkeypatch.setenv("MYXCEL_PROVENANCE_SCHEMA", "2")
        monkeypatch.setenv("MYXCEL_PROVENANCE_STATUS", "git")
        monkeypatch.setenv("MYXCEL_GIT_SHA", head_sha)
        monkeypatch.setenv("MYXCEL_GIT_BRANCH", "main")
        monkeypatch.setenv("MYXCEL_PROVENANCE_ROOT", str(remote))

        state = capture_git_state(remote)
        assert state.hash == head_sha
        assert state.code_verified is True
        assert state.provenance_source == "myxcel-env"

    def test_live_git_beats_sidecar_with_manifest(self, tmp_path):
        """Live .git still wins over a sidecar with manifest."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # Also make it a real repo
        subprocess.run(["git", "init", "-q"], cwd=remote, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=remote, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=remote, check=True)
        # Add sidecar to .gitignore
        (remote / ".gitignore").write_text(f"{PROVENANCE_FILENAME}\n")
        subprocess.run(["git", "add", "-A"], cwd=remote, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=remote, check=True)

        state = capture_git_state(remote)
        assert state.provenance_source == "git"
        assert state.code_verified is True

    def test_future_schema_warning_but_withheld(self, tmp_path):
        """Future schema version warns but still withholds (no manifest reading)."""
        fixture_dir = tmp_path / "test"
        fixture_dir.mkdir()
        sidecar = fixture_dir / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 99,  # Way in the future
            "provenance_status": "git",
            "git_sha": "a" * 40,
            "git_branch": "main",
            "provenance_root": str(fixture_dir),
        }))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            state = capture_git_state(fixture_dir)

        # Should warn about future schema
        schema_warnings = [x for x in w if "schema_version" in str(x.message)]
        assert len(schema_warnings) >= 1

        # But still withholds (no manifest in future schema)
        assert state.hash == "unknown"

    def test_warning_not_raised_twice_per_sidecar(self, tmp_path):
        """Warning for a withheld sidecar is only emitted once per process."""
        fixture_dir = tmp_path / "test"
        fixture_dir.mkdir()
        sidecar = fixture_dir / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1,
            "provenance_status": "git",
            "git_sha": "a" * 40,
            "git_branch": "main",
            "provenance_root": str(fixture_dir),
        }))

        from cisternal.provenance import channels
        channels._WARNED.clear()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            capture_git_state(fixture_dir)
            count_after_first = len(w)

            capture_git_state(fixture_dir)
            count_after_second = len(w)

        # Second call should not have emitted another warning
        assert count_after_second == count_after_first

    def test_warning_error_handling(self, tmp_path):
        """Warnings with -W error do not escape into capture_git_state."""
        fixture_dir = tmp_path / "test"
        fixture_dir.mkdir()
        sidecar = fixture_dir / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1,
            "provenance_status": "git",
            "git_sha": "a" * 40,
            "git_branch": "main",
            "provenance_root": str(fixture_dir),
        }))

        from cisternal.provenance import channels
        channels._WARNED.clear()

        # Even with warnings as errors, capture_git_state should not raise
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            state = capture_git_state(fixture_dir)

        # Must return an unverified state, not raise
        assert isinstance(state, GitState)
        assert state.provenance_source == "unverified-sidecar"

    def test_extra_file_under_declared_dir_withheld(self, tmp_path):
        """Extra untracked file under a declared dir → withheld."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # Add an extra file that's not in the manifest
        (remote / "src" / "extra.py").write_text("# extra\n")

        state = capture_git_state(remote)
        assert state.hash == "unknown"
        assert state.code_verified is False
        assert state.verification is not None
        assert len(state.verification.extra_untracked_under_declared_dirs) > 0

    def test_cwd_outside_sidecar_withheld(self, tmp_path):
        """cwd outside sidecar directory → withheld."""
        remote, head_sha = _make_verified_tree(tmp_path)

        # cwd outside remote
        outside = tmp_path / "outside"
        outside.mkdir()

        state = capture_git_state(outside)
        assert state.hash == "unknown"
        # The sidecar is not found, so it's just _unknown()
        assert state.provenance_source == "none"

    def test_nogit_status_keeps_hash(self, tmp_path):
        """nogit status surfaces hash='nogit', no verification needed."""
        fixture_dir = tmp_path / "nogit"
        fixture_dir.mkdir()
        sidecar = fixture_dir / PROVENANCE_FILENAME
        sidecar.write_text(json.dumps({
            "schema_version": 1,
            "provenance_status": "nogit",
            "git_branch": "none",
            "git_dirty": False,
            "provenance_root": str(fixture_dir),
        }))

        state = capture_git_state(fixture_dir)
        assert state.hash == "nogit"
        # nogit doesn't need verification, so code_verified is None
        assert state.code_verified is None
