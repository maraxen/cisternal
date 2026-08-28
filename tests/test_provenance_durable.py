"""Tests for cisternal.provenance.durable: worktree snapshots, durable refs, manifest, bundles."""

from __future__ import annotations

import subprocess

import pytest

from cisternal.provenance.durable import (
    SNAPSHOT_FULL,
    SNAPSHOT_METADATA_ONLY,
    SNAPSHOT_NONE,
    export_bundle,
    import_bundles,
    manifest_entry,
    pin_run,
    ref_resolves,
    snapshot_worktree_detailed,
    uncommitted_diff_for_run,
    update_ref,
)


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _head(path):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def clean_repo(tmp_path):
    return _init_repo(tmp_path)


@pytest.fixture()
def dirty_repo(clean_repo):
    (clean_repo / "b.txt").write_text("uncommitted\n")
    return clean_repo


class TestSnapshotWorktreeDetailed:
    def test_clean_tree_no_snapshot_needed(self, clean_repo):
        result = snapshot_worktree_detailed("run1", clean_repo)
        assert result.mode == SNAPSHOT_NONE
        assert result.commit == ""

    def test_dirty_tree_produces_full_snapshot(self, dirty_repo):
        result = snapshot_worktree_detailed("run1", dirty_repo)
        assert result.mode == SNAPSHOT_FULL
        assert len(result.commit) == 40

    def test_snapshot_does_not_disturb_working_tree_or_index(self, dirty_repo):
        before_status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=dirty_repo, capture_output=True, text=True
        ).stdout
        snapshot_worktree_detailed("run1", dirty_repo)
        after_status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=dirty_repo, capture_output=True, text=True
        ).stdout
        assert before_status == after_status

    def test_oversized_tree_degrades_to_metadata_only(self, clean_repo):
        big = clean_repo / "big.bin"
        big.write_bytes(b"\0" * 1000)
        result = snapshot_worktree_detailed("run1", clean_repo, max_bytes=100)
        assert result.mode == SNAPSHOT_METADATA_ONLY
        assert result.skipped_bytes >= 1000
        assert result.commit == ""

    def test_non_repo_returns_empty_result(self, tmp_path):
        result = snapshot_worktree_detailed("run1", tmp_path)
        assert result.mode == SNAPSHOT_NONE
        assert result.commit == ""


class TestUpdateRef:
    def test_valid_sha_ref_resolves_after_update(self, clean_repo):
        sha = _head(clean_repo)
        ok = update_ref("refs/provenance/runs/r1", sha, clean_repo)
        assert ok is True
        assert ref_resolves("refs/provenance/runs/r1", clean_repo) is True

    def test_empty_sha_refuses(self, clean_repo):
        assert update_ref("refs/provenance/runs/r1", "", clean_repo) is False

    def test_non_repo_refuses(self, tmp_path):
        assert update_ref("refs/provenance/runs/r1", "a" * 40, tmp_path) is False


class TestPinRun:
    def test_clean_run_pins_head_directly(self, clean_repo):
        sha = _head(clean_repo)
        result = pin_run("run1", sha, "main", dirty=False, cwd=clean_repo)
        assert result.run_ref_ok is True
        assert result.snapshot_mode == SNAPSHOT_NONE
        assert result.complete is True

    def test_dirty_run_pins_snapshot_not_head(self, dirty_repo):
        sha = _head(dirty_repo)
        result = pin_run("run1", sha, "main", dirty=True, cwd=dirty_repo)
        assert result.run_ref_ok is True
        assert result.snapshot_mode == SNAPSHOT_FULL
        assert result.wip_commit != ""
        assert result.wip_commit != sha

    def test_no_resolvable_head_refuses(self, clean_repo):
        # A real repo, but the CALLER passed an unresolvable hash (e.g. resolve_git_commit
        # upstream already failed) -- distinct from "not a git repository" at all.
        result = pin_run("run1", "unknown", "main", dirty=False, cwd=clean_repo)
        assert result.unpinned_reason == "no resolvable HEAD to pin"
        assert result.run_ref_ok is False

    def test_non_repo_refuses_with_distinct_reason(self, tmp_path):
        result = pin_run("run1", "unknown", "main", dirty=False, cwd=tmp_path)
        assert result.unpinned_reason == "not a git repository"
        assert result.run_ref_ok is False

    def test_manifest_entry_recorded(self, clean_repo):
        sha = _head(clean_repo)
        pin_run("run-manifest", sha, "main", dirty=False, cwd=clean_repo)
        entry = manifest_entry("run-manifest", clean_repo)
        assert entry is not None
        assert entry["head_sha"] == sha
        assert entry["complete"] is True

    def test_custom_ref_prefixes_are_respected(self, clean_repo):
        sha = _head(clean_repo)
        result = pin_run(
            "run1", sha, "main", dirty=False, cwd=clean_repo,
            run_ref_prefix="refs/mytool/runs",
        )
        assert result.run_ref == "refs/mytool/runs/run1"
        assert ref_resolves("refs/mytool/runs/run1", clean_repo)


class TestUncommittedDiffForRun:
    def test_clean_run_returns_empty_string(self, clean_repo):
        sha = _head(clean_repo)
        pin_run("run-clean", sha, "main", dirty=False, cwd=clean_repo)
        assert uncommitted_diff_for_run("run-clean", clean_repo) == ""

    def test_dirty_run_returns_the_diff(self, dirty_repo):
        sha = _head(dirty_repo)
        pin_run("run-dirty", sha, "main", dirty=True, cwd=dirty_repo)
        diff = uncommitted_diff_for_run("run-dirty", dirty_repo)
        assert diff is not None
        assert "b.txt" in diff

    def test_unknown_run_returns_none(self, clean_repo):
        assert uncommitted_diff_for_run("never-ran", clean_repo) is None


class TestBundleExportImport:
    def test_export_then_import_into_fresh_clone(self, dirty_repo, tmp_path):
        sha = _head(dirty_repo)
        pin_run("run-bundle", sha, "main", dirty=True, cwd=dirty_repo)
        export_dir = tmp_path / "export"
        entry = manifest_entry("run-bundle", dirty_repo)
        bundle = export_bundle("run-bundle", entry["pinned_sha"], sha, dirty_repo, export_dir=export_dir)
        assert bundle is not None
        assert bundle.exists()

        # A fresh clone of the ORIGINAL (clean) history has the base commit but not the snapshot.
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", "-q", str(dirty_repo), str(clone)], check=True)
        # dirty_repo's uncommitted change never made it into the clone's history either,
        # so this exercises the real "clone has base, not snapshot" scenario.
        bundle.with_suffix(".json").write_text(
            __import__("json").dumps({**entry}), encoding="utf-8"
        )
        report = import_bundles(clone, import_dir=export_dir)
        assert "run-bundle" in report.imported or "run-bundle" in report.already_present

    def test_import_from_empty_dir_is_noop(self, clean_repo, tmp_path):
        report = import_bundles(clean_repo, import_dir=tmp_path / "nonexistent")
        assert report.imported == ()
        assert report.already_present == ()
        assert report.unusable == ()
