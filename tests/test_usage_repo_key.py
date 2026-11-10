"""Tests for worktree-aware repository key resolution and folding."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from cisternal.usage.transcript import _GIT_COMMON_DIR_CACHE, resolve_repo_key


@pytest.fixture(autouse=True)
def _clear_git_common_dir_cache():
    """Teardown fixture ensuring the process-global cache is cleared between tests."""
    yield
    _GIT_COMMON_DIR_CACHE.clear()


class TestResolveRepoKey:
    """Test repository key normalization for worktrees and slug fallbacks."""

    def test_worktree_dot_claude_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "my-repo"
        repo.mkdir()
        wt = repo / ".claude" / "worktrees" / "feature-1"
        wt.mkdir(parents=True)

        assert resolve_repo_key(str(wt), "slug") == str(repo.resolve())

    def test_worktree_dot_worktrees_path(self, tmp_path: Path) -> None:
        repo = tmp_path / "my-repo"
        repo.mkdir()
        wt = repo / ".worktrees" / "branch-a" / "src"
        wt.mkdir(parents=True)

        assert resolve_repo_key(str(wt), "slug") == str(repo.resolve())

    def test_git_rev_parse_common_dir(self, tmp_path: Path) -> None:
        # Create a real git repository and worktree
        main_repo = tmp_path / "main_repo"
        main_repo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=str(main_repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=str(main_repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(main_repo),
            check=True,
            capture_output=True,
        )

        # Initial commit
        (main_repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."], cwd=str(main_repo), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "--no-verify", "-m", "init"],
            cwd=str(main_repo),
            check=True,
            capture_output=True,
        )

        # Add a worktree
        wt_path = tmp_path / "worktree_1"
        subprocess.run(
            ["git", "worktree", "add", str(wt_path)],
            cwd=str(main_repo),
            check=True,
            capture_output=True,
        )

        resolved = resolve_repo_key(str(wt_path), "some-slug")
        assert resolved == str(main_repo.resolve())

    def test_git_rev_parse_caching(self, tmp_path: Path) -> None:
        p = tmp_path / "cached_dir"
        p.mkdir()
        path_str = str(p.resolve())

        _GIT_COMMON_DIR_CACHE[path_str] = "/custom/cached/root"
        assert resolve_repo_key(path_str, "slug") == "/custom/cached/root"

    def test_slug_fallback_worktree_suffix(self) -> None:
        assert resolve_repo_key(None, "proj--claude-worktrees-branch") == "proj"
        assert resolve_repo_key(None, "proj--worktrees-branch") == "proj"
        assert resolve_repo_key("", "my-repo--claude-worktrees-feat-xyz") == "my-repo"

    def test_slug_unmodified(self) -> None:
        assert resolve_repo_key(None, "normal-project") == "normal-project"
        assert resolve_repo_key("", "repo-without-worktree") == "repo-without-worktree"

    def test_plain_cwd(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain_project"
        plain.mkdir()

        assert resolve_repo_key(str(plain), "plain-slug") == str(plain.resolve())
