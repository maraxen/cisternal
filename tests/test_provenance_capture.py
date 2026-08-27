"""Tests for cisternal.provenance.capture: commit/dirty resolution, tree-OID, records."""

from __future__ import annotations

import logging
import subprocess

import pytest

from cisternal.provenance.capture import (
    GitResolutionError,
    abuild_provenance_record,
    acompute_dirty_content_id,
    aresolve_git_commit,
    build_provenance_record,
    compute_dirty_content_id,
    resolve_git_commit,
)


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


@pytest.fixture()
def clean_repo(tmp_path):
    return _init_repo(tmp_path)


@pytest.fixture()
def dirty_repo(clean_repo):
    (clean_repo / "b.txt").write_text("uncommitted\n")
    return clean_repo


class TestResolveGitCommit:
    def test_clean_repo_resolves_commit_not_dirty(self, clean_repo):
        info = resolve_git_commit(clean_repo)
        assert info.commit is not None and len(info.commit) == 40
        assert info.is_dirty is False

    def test_dirty_repo_detected(self, dirty_repo):
        info = resolve_git_commit(dirty_repo)
        assert info.is_dirty is True

    def test_non_repo_path_non_strict_returns_none_and_warns(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            info = resolve_git_commit(tmp_path)
        assert info.commit is None
        assert info.is_dirty is None
        assert any("git rev-parse" in r.message for r in caplog.records)

    def test_non_repo_path_strict_raises(self, tmp_path):
        with pytest.raises(GitResolutionError):
            resolve_git_commit(tmp_path, strict=True)

    def test_file_not_directory_fails_loudly_not_silently(self, tmp_path):
        """The exact bug this module replaces: git -C <file> always fails."""
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x")
        with pytest.raises(GitResolutionError):
            resolve_git_commit(f, strict=True)


class TestAsyncResolveGitCommit:
    @pytest.mark.asyncio
    async def test_clean_repo_resolves_commit(self, clean_repo):
        info = await aresolve_git_commit(clean_repo)
        assert info.commit is not None
        assert info.is_dirty is False

    @pytest.mark.asyncio
    async def test_dirty_repo_detected(self, dirty_repo):
        info = await aresolve_git_commit(dirty_repo)
        assert info.is_dirty is True

    @pytest.mark.asyncio
    async def test_sync_and_async_agree(self, dirty_repo):
        sync_info = resolve_git_commit(dirty_repo)
        async_info = await aresolve_git_commit(dirty_repo)
        assert sync_info.commit == async_info.commit
        assert sync_info.is_dirty == async_info.is_dirty


class TestDirtyContentId:
    def test_clean_repo_no_content_id_needed(self, clean_repo):
        # dirty_content_id is only meaningful when the tree is actually dirty;
        # a clean repo should still compute a stable (unchanged) tree OID.
        content_id = compute_dirty_content_id(clean_repo)
        assert content_id is None or content_id.startswith("tree:")

    def test_dirty_repo_gets_tree_tagged_id(self, dirty_repo):
        content_id = compute_dirty_content_id(dirty_repo)
        assert content_id is not None
        assert content_id.startswith("tree:")
        assert len(content_id.split(":", 1)[1]) == 40

    def test_deterministic_for_same_dirty_state(self, dirty_repo):
        first = compute_dirty_content_id(dirty_repo)
        second = compute_dirty_content_id(dirty_repo)
        assert first == second

    def test_does_not_mutate_real_index(self, dirty_repo):
        """The throwaway-index technique must leave the caller's index untouched."""
        before = subprocess.run(
            ["git", "status", "--porcelain"], cwd=dirty_repo, capture_output=True, text=True
        ).stdout
        compute_dirty_content_id(dirty_repo)
        after = subprocess.run(
            ["git", "status", "--porcelain"], cwd=dirty_repo, capture_output=True, text=True
        ).stdout
        assert before == after

    @pytest.mark.asyncio
    async def test_async_matches_sync(self, dirty_repo):
        sync_id = compute_dirty_content_id(dirty_repo)
        async_id = await acompute_dirty_content_id(dirty_repo)
        # Both computed independently against the same dirty tree -> same tree OID.
        assert sync_id == async_id

    def test_linked_worktree_does_not_crash(self, clean_repo, tmp_path):
        """D3's motivating bug: a linked worktree's .git is a FILE, not a directory."""
        wt_path = tmp_path / "linked-wt"
        result = subprocess.run(
            ["git", "worktree", "add", "-q", str(wt_path), "-b", "wt-branch"],
            cwd=clean_repo, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        (wt_path / "c.txt").write_text("dirty in worktree\n")
        content_id = compute_dirty_content_id(wt_path)
        assert content_id is not None
        assert content_id.startswith("tree:")


class TestBuildProvenanceRecord:
    def test_clean_repo_record(self, clean_repo):
        record, warnings = build_provenance_record(
            clean_repo, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
        )
        assert record.provenance_status == "git"
        assert record.git_dirty is False
        assert record.dirty_content_id is None
        assert warnings == []

    def test_dirty_repo_record_has_content_id(self, dirty_repo):
        record, warnings = build_provenance_record(
            dirty_repo, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
        )
        assert record.git_dirty is True
        assert record.dirty_content_id is not None

    def test_skip_content_id_flag_is_honored(self, dirty_repo):
        record, _ = build_provenance_record(
            dirty_repo, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
            compute_dirty_content_id_flag=False,
        )
        assert record.git_dirty is True
        assert record.dirty_content_id is None

    def test_non_repo_returns_nogit(self, tmp_path):
        record, _ = build_provenance_record(
            tmp_path, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
        )
        assert record.provenance_status == "nogit"

    def test_missing_local_root_returns_unavailable(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        record, warnings = build_provenance_record(
            missing, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
        )
        assert record.provenance_status == "unavailable"
        assert warnings

    @pytest.mark.asyncio
    async def test_async_matches_sync_on_clean_repo(self, clean_repo):
        sync_record, _ = build_provenance_record(
            clean_repo, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
        )
        async_record, _ = await abuild_provenance_record(
            clean_repo, remote="r", project="p", provenance_root="/remote/p", capture_stage="push",
        )
        assert sync_record.git_sha == async_record.git_sha
        assert sync_record.provenance_status == async_record.provenance_status
