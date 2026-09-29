"""Tests for tree manifest building and verification.

Tests the writer path (build_tree_manifest) and reader path (verify_tree),
covering content hashing, ignore rules, budget constraints, and edge cases.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cisternal.provenance.tree_manifest import (
    HASH_ALGO,
    MANIFEST_VERSION,
    TreeManifest,
    blob_id,
    build_tree_manifest,
    tree_id,
    verify_tree,
)


def _init_test_repo(tmpdir: Path) -> Path:
    """Create a minimal git repo with test files."""
    tmpdir.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )

    # Create some test files
    src_dir = tmpdir / "src" / "pkg"
    src_dir.mkdir(parents=True)
    (src_dir / "a.py").write_text("def func_a():\n    pass\n")
    (src_dir / "b.py").write_text("def func_b():\n    pass\n")

    scripts_dir = tmpdir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "run.py").write_text("#!/usr/bin/env python3\n")

    (tmpdir / "README.md").write_text("# Test\n")

    # Create .gitignore
    (tmpdir / ".gitignore").write_text("outputs/\n*.log\n")

    # Commit
    subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )

    return tmpdir


def _copy_no_git(src: Path, dst: Path) -> None:
    """Copy directory, excluding .git."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git"))


class TestBlobId:
    """Test blob_id computation."""

    def test_blob_id_empty(self):
        """Empty file."""
        result = blob_id(b"")
        assert len(result) == 40
        # Git's empty blob: "blob 0\0"
        assert result == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"

    def test_blob_id_simple(self):
        """Simple text file."""
        result = blob_id(b"hello world")
        assert len(result) == 40
        # Verify against git
        proc = subprocess.run(
            ["git", "hash-object", "--no-filters", "--stdin"],
            input=b"hello world",
            capture_output=True,
        )
        if proc.returncode == 0:
            git_hash = proc.stdout.decode().strip()
            assert result == git_hash


class TestTreeId:
    """Test tree_id computation."""

    def test_tree_id_empty(self):
        """Empty file set."""
        result = tree_id({})
        assert len(result) == 40
        # Git's empty tree OID
        assert result == "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

    def test_tree_id_single_file(self):
        """Single file in tree."""
        files = {"file.txt": ("100644", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4")}
        result = tree_id(files)
        assert len(result) == 40


class TestTreeManifest:
    """Test TreeManifest dataclass."""

    def test_to_dict_and_from_dict_roundtrip(self):
        """Manifest round-trip through dict."""
        manifest = TreeManifest(
            manifest_version=MANIFEST_VERSION,
            hash_algo=HASH_ALGO,
            commit="abc123def456abc123def456abc123def456abc1",
            tree_id="def456789abc123def456789abc123def456789a",
            declared_dirs=("src", "scripts"),
            matches_commit=True,
            extra_excludes=("*.log", "outputs/"),
            files={"src/a.py": ("100644", "abc123def456abc123def456abc123def456abc1")},
            skipped=(),
        )

        d = manifest.to_dict()
        assert isinstance(d["files"]["src/a.py"], list)
        assert d["declared_dirs"] == ["src", "scripts"]

        manifest2 = TreeManifest.from_dict(d)
        assert manifest2 is not None
        assert manifest2.commit == "abc123def456abc123def456abc123def456abc1"
        assert manifest2.matches_commit is True

    def test_from_dict_invalid(self):
        """from_dict returns None on invalid input."""
        assert TreeManifest.from_dict({}) is None
        assert TreeManifest.from_dict({"manifest_version": 99}) is None
        assert TreeManifest.from_dict("not a dict") is None
        assert TreeManifest.from_dict({
            "manifest_version": 1,
            "hash_algo": "git-blob-sha1-nofilter",
            "commit": None,
            "tree_id": "notahex",  # Invalid hex
            "declared_dirs": [],
            "matches_commit": False,
            "extra_excludes": [],
            "files": {},
            "skipped": [],
        }) is None


class TestBuildTreeManifest:
    """Test build_tree_manifest."""

    def test_build_simple_manifest(self, tmp_path):
        """Build manifest from a simple repo."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)

        assert manifest is not None
        assert manifest.manifest_version == MANIFEST_VERSION
        assert manifest.hash_algo == HASH_ALGO
        assert len(manifest.files) >= 3
        assert "src/pkg/a.py" in manifest.files
        assert "scripts/run.py" in manifest.files
        assert "README.md" in manifest.files

    def test_build_manifest_with_git_commit(self, tmp_path):
        """Build manifest with commit SHA."""
        repo = _init_test_repo(tmp_path / "repo")

        # Get HEAD commit
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            check=True,
            text=True,
        )
        commit = proc.stdout.strip()

        manifest = build_tree_manifest(repo, commit=commit)
        assert manifest is not None
        assert manifest.commit == commit
        assert manifest.matches_commit is True

    def test_build_manifest_matches_commit_false_when_dirty(self, tmp_path):
        """matches_commit is False when tracked files are modified."""
        repo = _init_test_repo(tmp_path / "repo")

        # Get HEAD commit
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            check=True,
            text=True,
        )
        commit = proc.stdout.strip()

        # Modify a tracked file
        (repo / "src" / "pkg" / "a.py").write_text("modified content\n")

        manifest = build_tree_manifest(repo, commit=commit)
        assert manifest is not None
        assert manifest.matches_commit is False

    def test_build_manifest_matches_commit_false_with_untracked_in_paths(self, tmp_path):
        """matches_commit is False when untracked files are in paths."""
        repo = _init_test_repo(tmp_path / "repo")

        # Get HEAD commit
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            check=True,
            text=True,
        )
        commit = proc.stdout.strip()

        # Create an untracked file
        (repo / "new_file.py").write_text("untracked\n")

        # Build manifest with explicit paths including the untracked file
        paths = ["src/pkg/a.py", "src/pkg/b.py", "scripts/run.py", "README.md", "new_file.py"]
        manifest = build_tree_manifest(repo, commit=commit, paths=paths)
        assert manifest is not None
        assert manifest.matches_commit is False


class TestVerifyTree:
    """Test verify_tree function."""

    def test_verify_untouched_copy(self, tmp_path):
        """Verify an untouched copy of files."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files without .git
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Verify
        verification = verify_tree(copy, manifest)
        assert verification.verified is True
        assert verification.n_match == manifest.manifest_version or verification.n_match == len(manifest.files)
        assert len(verification.mismatched) == 0
        assert len(verification.missing) == 0
        assert len(verification.extra_untracked_under_declared_dirs) == 0

    def test_verify_modified_file(self, tmp_path):
        """Test 1: Modified file after manifest."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Modify a file
        (copy / "src" / "pkg" / "a.py").write_text("modified\n")

        # Verify
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert "src/pkg/a.py" in verification.mismatched

    def test_verify_missing_file(self, tmp_path):
        """Test 3: Missing file."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Delete a file
        (copy / "src" / "pkg" / "a.py").unlink()

        # Verify
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert "src/pkg/a.py" in verification.missing

    def test_verify_extra_untracked_file(self, tmp_path):
        """Test 4: Extra untracked non-ignored file."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Add an extra file under src/
        (copy / "src" / "extra.py").write_text("extra\n")

        # Verify
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert "src/extra.py" in verification.extra_untracked_under_declared_dirs

    def test_verify_extra_ignored_file(self, tmp_path):
        """Test 4b: Extra file matching .gitignore is NOT an extra."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Add a file that matches .gitignore pattern
        (copy / "src" / "test.log").write_text("log content\n")

        # Verify
        verification = verify_tree(copy, manifest)
        # The .log file should NOT be in extras because it's in .gitignore
        assert "src/test.log" not in verification.extra_untracked_under_declared_dirs

    def test_verify_stale_leftover(self, tmp_path):
        """Test 14: Stale leftover file under declared dirs."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Add an extra unignored file under scripts/
        (copy / "scripts" / "old_script.py").write_text("old\n")

        # Verify
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert "scripts/old_script.py" in verification.extra_untracked_under_declared_dirs

    def test_verify_manifest_ok_tampered_tree_id(self, tmp_path):
        """Test 15a: Tampered tree_id."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Tamper with tree_id
        bad_manifest = TreeManifest(
            manifest_version=manifest.manifest_version,
            hash_algo=manifest.hash_algo,
            commit=manifest.commit,
            tree_id="0000000000000000000000000000000000000000",  # Wrong
            declared_dirs=manifest.declared_dirs,
            matches_commit=manifest.matches_commit,
            extra_excludes=manifest.extra_excludes,
            files=manifest.files,
            skipped=manifest.skipped,
        )

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Verify
        verification = verify_tree(copy, bad_manifest)
        assert verification.manifest_ok is False
        assert verification.verified is False

    def test_verify_from_dict_malformed(self, tmp_path):
        """Test 15b: from_dict on garbage."""
        repo = _init_test_repo(tmp_path / "repo")
        _copy_no_git(repo, tmp_path / "copy")

        # Test various malformed inputs
        assert TreeManifest.from_dict({}) is None
        assert TreeManifest.from_dict({"manifest_version": 99}) is None
        assert TreeManifest.from_dict("invalid") is None

        # Invalid file hex
        bad_dict = {
            "manifest_version": 1,
            "hash_algo": "git-blob-sha1-nofilter",
            "commit": None,
            "tree_id": "abc123def456abc123def456abc123def456abc1",
            "declared_dirs": [],
            "matches_commit": False,
            "extra_excludes": [],
            "files": {"test.py": ["100644", "notahex"]},
            "skipped": [],
        }
        assert TreeManifest.from_dict(bad_dict) is None

    def test_verify_git_command_failure_simulation(self, tmp_path, monkeypatch):
        """Test 16a: git exits nonzero."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Monkeypatch subprocess.run to make git return nonzero
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            if args[0][0] == "git" and "ls-files" in args[0]:
                # Return a fake failure
                import subprocess as sp
                result = sp.CompletedProcess(args[0], returncode=128)
                result.stdout = b""
                result.stderr = b"fatal: something went wrong"
                return result
            return original_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Verify should fail with error set
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert verification.error is not None
        assert "git ls-files failed" in verification.error

    def test_verify_extra_excludes_pattern(self, tmp_path):
        """Test 16c: File matching extra_excludes pattern is not an extra."""
        repo = _init_test_repo(tmp_path / "repo")

        # Build manifest with extra_excludes
        manifest = build_tree_manifest(
            repo,
            commit=None,
            extra_excludes=["*.swp", ".DS_Store"],
        )
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Add a .swp file
        (copy / "src" / "test.swp").write_text("swap file\n")

        # Verify
        verification = verify_tree(copy, manifest)
        # The .swp file should NOT be in extras because it matches extra_excludes
        assert "src/test.swp" not in verification.extra_untracked_under_declared_dirs

    def test_verify_budget_max_bytes(self, tmp_path):
        """Test 17a: Budget exceeded (max_bytes)."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Verify with very low byte budget
        verification = verify_tree(copy, manifest, max_bytes=1)
        assert verification.verified is False
        assert "budget exceeded" in verification.error

    def test_verify_permission_error(self, tmp_path):
        """Test 17b: PermissionError on file."""
        if os.geteuid() == 0:
            pytest.skip("Running as root; cannot test PermissionError")

        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Chmod a file to 000
        (copy / "src" / "pkg" / "a.py").chmod(0o000)

        try:
            # Verify
            verification = verify_tree(copy, manifest)
            assert verification.verified is False
            assert verification.error is not None
        finally:
            # Restore permissions for cleanup
            (copy / "src" / "pkg" / "a.py").chmod(0o644)

    def test_verify_cwd_inside_root_but_extra_files(self, tmp_path):
        """Test cwd scanning."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Create a subdirectory not in declared_dirs and add an extra file
        new_dir = copy / "new_scratch"
        new_dir.mkdir()
        (new_dir / "extra.py").write_text("extra\n")

        # Verify with cwd in the new directory
        verification = verify_tree(copy, manifest, cwd=new_dir)
        assert verification.verified is False
        assert "new_scratch/extra.py" in verification.extra_untracked_under_declared_dirs

    def test_verify_cwd_outside_root(self, tmp_path):
        """Test cwd outside root."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Verify with cwd outside root
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        verification = verify_tree(copy, manifest, cwd=outside_dir)
        assert verification.verified is False
        assert "outside" in verification.error

    def test_verify_dirty_content_id_consistent(self, tmp_path):
        """Test dirty_content_id_consistent field."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Verify with a matching tree: prefix
        verification = verify_tree(copy, manifest, dirty_content_id=f"tree:{manifest.tree_id}")
        # If verified, dirty_content_id_consistent should be True
        if verification.tree_id is not None:
            assert verification.dirty_content_id_consistent is True

    def test_verify_blob_id_matches_git(self, tmp_path):
        """Test 9a: blob_id matches git hash-object."""
        repo = _init_test_repo(tmp_path / "repo")

        # Get each file and verify blob_id matches git
        for file_path in ["src/pkg/a.py", "README.md"]:
            full_path = repo / file_path
            if full_path.exists():
                file_content = full_path.read_bytes()
                our_hash = blob_id(file_content)

                # Get git's hash
                proc = subprocess.run(
                    ["git", "hash-object", "--no-filters", "--stdin"],
                    input=file_content,
                    capture_output=True,
                )
                if proc.returncode == 0:
                    git_hash = proc.stdout.decode().strip()
                    assert our_hash == git_hash

    def test_verify_tree_id_matches_git_write_tree(self, tmp_path):
        """Test 9b: tree_id matches git write-tree."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Get git's tree OID
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            git_tree_id = proc.stdout.strip()
            # Our tree_id should match
            assert manifest.tree_id == git_tree_id

    def test_verify_symlink(self, tmp_path):
        """Test symlink handling."""
        repo = _init_test_repo(tmp_path / "repo")

        # Create a symlink
        link_target = repo / "src" / "pkg" / "a.py"
        symlink = repo / "src" / "link.py"
        symlink.symlink_to(link_target)

        # Commit
        subprocess.run(["git", "add", "src/link.py"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add symlink"], cwd=repo, capture_output=True)

        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None
        assert "src/link.py" in manifest.files
        assert manifest.files["src/link.py"][0] == "120000"

        # Copy with symlinks preserved
        copy = tmp_path / "copy"
        shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"), symlinks=True)

        # Verify should work
        verification = verify_tree(copy, manifest)
        assert verification.verified is True

    def test_verify_exception_in_extras_scan_tempdir(self, tmp_path, monkeypatch):
        """Test 1: Exception in extras scan (tempfile.TemporaryDirectory) fails verification."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Monkeypatch TemporaryDirectory to raise
        import tempfile as tmp_module

        def broken_tmpdir(*args, **kwargs):
            raise RuntimeError("tempdir creation failed")

        monkeypatch.setattr(tmp_module, "TemporaryDirectory", broken_tmpdir)

        # Verify should fail with error set
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert verification.error is not None

    def test_verify_git_init_bare_fails(self, tmp_path, monkeypatch):
        """Test 1: git init --bare failure is caught."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Monkeypatch subprocess.run to make git init return nonzero
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            if args[0][0] == "git" and "init" in args[0] and "--bare" in args[0]:
                import subprocess as sp
                result = sp.CompletedProcess(args[0], returncode=128)
                result.stdout = b""
                result.stderr = b"fatal: could not create work tree dir"
                return result
            return original_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Verify should fail with error mentioning git init
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert verification.error is not None
        assert "git init" in verification.error.lower()

    def test_verify_empty_scan_dirs_root_extra(self, tmp_path):
        """Test 2: Empty scan_dirs with extra at root → verified True, extras empty."""
        # Create a simple root-only repo (files at root, no subdirs)
        repo = tmp_path / "root_only"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Create files at root only
        (repo / "main.py").write_text("main\n")
        (repo / "config.toml").write_text("[config]\n")
        (repo / ".gitignore").write_text("*.log\n")

        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Build manifest (should have no declared_dirs since no "/" in paths)
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None
        assert manifest.declared_dirs == ()  # No subdirs

        # Copy and add a non-ignored file at root
        copy = tmp_path / "copy_root"
        _copy_no_git(repo, copy)
        (copy / "extra.py").write_text("extra\n")

        # Verify: extras should be empty (root-level gap) and verified True
        verification = verify_tree(copy, manifest)
        # Per spec D1, root-level files not scanned (documented gap)
        assert len(verification.extra_untracked_under_declared_dirs) == 0
        assert verification.verified is True

    def test_verify_cwd_dir_non_recursive(self, tmp_path):
        """Test 3: cwd dir scanning is non-recursive, declared dirs recursive."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Create a cwd dir with nested and top-level extras
        cwd_dir = copy / "scratch"
        cwd_dir.mkdir()
        (cwd_dir / "top.py").write_text("top\n")

        # Create nested file (should NOT be detected since cwd is non-recursive)
        nested_dir = cwd_dir / "deep"
        nested_dir.mkdir()
        (nested_dir / "nested.py").write_text("nested\n")

        # Verify with cwd in scratch
        verification = verify_tree(copy, manifest, cwd=cwd_dir)
        # Only top.py should be in extras (non-recursive for cwd)
        assert "scratch/top.py" in verification.extra_untracked_under_declared_dirs
        assert "scratch/deep/nested.py" not in verification.extra_untracked_under_declared_dirs

    def test_verify_fallback_walk_nested(self, tmp_path, monkeypatch):
        """Test 4: Fallback walk (git absent) detects nested extras recursively."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Add nested extra file
        nested = copy / "src" / "pkg" / "sub"
        nested.mkdir()
        (nested / "new.py").write_text("new\n")

        # Monkeypatch subprocess.run to make git unavailable
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            if args[0][0] == "git":
                raise FileNotFoundError("git not found")
            return original_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Verify with fallback walk
        verification = verify_tree(copy, manifest)
        # Should detect nested extra via fallback walk
        assert "src/pkg/sub/new.py" in verification.extra_untracked_under_declared_dirs
        assert verification.extras_ignore_aware is False

    def test_verify_cwd_root_symlink_resolution(self, tmp_path):
        """Test 5: cwd/root comparison resolves symlinks."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy to a real directory
        copy_real = tmp_path / "copy_real"
        _copy_no_git(repo, copy_real)

        # Create a symlink to the copy
        copy_link = tmp_path / "copy_link"
        copy_link.symlink_to(copy_real)

        # Verify using the symlinked path as root and resolved real path as cwd
        verification = verify_tree(copy_link, manifest, cwd=copy_real)
        # Should work (symlinks resolved)
        assert verification.verified is True

    def test_verify_extra_excludes_from_git_path(self, tmp_path):
        """Test 6: extra_excludes reads from git rev-parse --git-path info/exclude."""
        repo = _init_test_repo(tmp_path / "repo")

        # Write a pattern to .git/info/exclude
        info_dir = repo / ".git" / "info"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "exclude").write_text("*.backup\n")

        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None
        # extra_excludes should contain the pattern from info/exclude
        assert "*.backup" in manifest.extra_excludes

    def test_verify_budget_error_not_none(self, tmp_path):
        """Test 8: Budget error is properly typed."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        verification = verify_tree(copy, manifest, max_bytes=1)
        # Error should not be None and should contain "budget"
        assert verification.error is not None
        assert "budget" in verification.error

    # ========== R1 FIXES ==========

    def test_empty_manifest_fails_verification(self, tmp_path):
        """R1.1: Empty manifest should verify to False, not True."""
        repo = _init_test_repo(tmp_path / "repo")
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Create an empty manifest
        empty_manifest = TreeManifest(
            manifest_version=MANIFEST_VERSION,
            hash_algo=HASH_ALGO,
            commit=None,
            tree_id="4b825dc642cb6eb9a060e54bf8d69288fbee4904",  # Empty tree ID
            declared_dirs=(),
            matches_commit=False,
            extra_excludes=(),
            files={},
            skipped=(),
        )

        # Verify should return False with error about empty manifest
        verification = verify_tree(copy, empty_manifest)
        assert verification.verified is False
        assert verification.error is not None
        assert "empty" in verification.error.lower()

    def test_build_manifest_returns_none_for_empty_files(self, tmp_path):
        """R1.1: build_tree_manifest should return None when resulting file set is empty."""
        # Create an empty repo (no files)
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Build manifest with empty paths list
        manifest = build_tree_manifest(repo, commit=None, paths=[])
        assert manifest is None

    def test_builtin_excludes_pycache_not_extra(self, tmp_path):
        """R1.2: __pycache__ and .pyc files should not be marked as extras."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy files
        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Create __pycache__ directory with a .pyc file (no .gitignore entry for it)
        pycache_dir = copy / "src" / "pkg" / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "a.cpython-313.pyc").write_bytes(b"fake bytecode")

        # Verify should pass despite __pycache__ not being in .gitignore
        verification = verify_tree(copy, manifest)
        assert "src/pkg/__pycache__/a.cpython-313.pyc" not in verification.extra_untracked_under_declared_dirs
        assert verification.verified is True
        assert verification.error is None

    def test_from_dict_rejects_non_bool_matches_commit(self):
        """R1.7: from_dict should reject non-bool matches_commit."""
        bad_dict = {
            "manifest_version": 1,
            "hash_algo": "git-blob-sha1-nofilter",
            "commit": None,
            "tree_id": "abc123def456abc123def456abc123def456abc1",
            "declared_dirs": [],
            "matches_commit": "false",  # String instead of bool
            "extra_excludes": [],
            "files": {},
            "skipped": [],
        }
        assert TreeManifest.from_dict(bad_dict) is None

    def test_from_dict_rejects_invalid_hex_tree_id(self):
        """R1.7: from_dict should reject invalid hex tree_id."""
        bad_dict = {
            "manifest_version": 1,
            "hash_algo": "git-blob-sha1-nofilter",
            "commit": None,
            "tree_id": "ABCDEF0123456789ABCDEF0123456789ABCDEF01",  # Uppercase
            "declared_dirs": [],
            "matches_commit": False,
            "extra_excludes": [],
            "files": {},
            "skipped": [],
        }
        assert TreeManifest.from_dict(bad_dict) is None

    def test_from_dict_rejects_invalid_hex_commit(self):
        """R1.7: from_dict should reject invalid hex commit when present."""
        bad_dict = {
            "manifest_version": 1,
            "hash_algo": "git-blob-sha1-nofilter",
            "commit": "not-hex-at-all",  # Invalid hex
            "tree_id": "abc123def456abc123def456abc123def456abc1",
            "declared_dirs": [],
            "matches_commit": False,
            "extra_excludes": [],
            "files": {},
            "skipped": [],
        }
        assert TreeManifest.from_dict(bad_dict) is None

    def test_verify_file_type_change_mismatched(self, tmp_path):
        """R1.6: File type change (mode 120000 vs regular) counts as mismatched."""
        repo = _init_test_repo(tmp_path / "repo")

        # Create a symlink
        link_target = repo / "src" / "pkg" / "a.py"
        symlink = repo / "src" / "link.py"
        symlink.symlink_to(link_target)

        subprocess.run(["git", "add", "src/link.py"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add symlink"], cwd=repo, capture_output=True)

        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None
        assert manifest.files["src/link.py"][0] == "120000"

        # Copy and replace symlink with regular file (same content as target)
        copy = tmp_path / "copy"
        shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"), symlinks=True)

        # Remove symlink and replace with regular file
        (copy / "src" / "link.py").unlink()
        (copy / "src" / "link.py").write_text("def func_a():\n    pass\n")

        # Verify should fail: mode changed from 120000 to 100644
        verification = verify_tree(copy, manifest)
        assert verification.verified is False
        assert "src/link.py" in verification.mismatched  # Different type → mismatched

    def test_verify_mode_changed_same_blob(self, tmp_path):
        """R1.6: Mode change (exec bit) with same blob → mode_changed, verified still True."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Change a file to executable (same content)
        (copy / "src" / "pkg" / "a.py").chmod(0o755)

        # Verify should show mode_changed
        verification = verify_tree(copy, manifest)
        assert "src/pkg/a.py" in verification.mode_changed
        assert verification.verified is True
        assert verification.error is None

    def test_verify_extra_ignored_file_and_mode_changed_assert(self, tmp_path):
        """R1.9: test_verify_extra_ignored_file must assert verified=True, error=None."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        (copy / "src" / "test.log").write_text("log content\n")

        verification = verify_tree(copy, manifest)
        assert "src/test.log" not in verification.extra_untracked_under_declared_dirs
        assert verification.verified is True
        assert verification.error is None

    def test_verify_extra_excludes_pattern_assert(self, tmp_path):
        """R1.9: test_verify_extra_excludes_pattern must assert verified=True, error=None."""
        repo = _init_test_repo(tmp_path / "repo")

        manifest = build_tree_manifest(
            repo,
            commit=None,
            extra_excludes=["*.swp", ".DS_Store"],
        )
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        (copy / "src" / "test.swp").write_text("swap file\n")

        verification = verify_tree(copy, manifest)
        assert "src/test.swp" not in verification.extra_untracked_under_declared_dirs
        assert verification.verified is True
        assert verification.error is None

    def test_tree_id_ordering_with_file_and_dir_names(self, tmp_path):
        """R1.9: Test tree_id ordering: files with similar prefixes."""
        # Create a test repo with files: "a.b", "a/x", "a-b" (ordered correctly)
        repo = tmp_path / "ordering_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        (repo / "a.b").write_text("file a.b\n")
        (repo / "a-b").write_text("file a-b\n")
        a_dir = repo / "a"
        a_dir.mkdir()
        (a_dir / "x").write_text("file a/x\n")

        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Build manifest and compare against git write-tree
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Get git's tree OID
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        git_tree_id = proc.stdout.strip()
        assert manifest.tree_id == git_tree_id

    def test_gitlink_nested_repo_not_extra(self, tmp_path):
        """R1.4: Nested git repos should not be marked as extras, use gitlink:<path> in skipped."""
        repo = tmp_path / "main_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Create a file in main repo
        (repo / "main.py").write_text("main\n")

        # Create a nested git repo
        vendor_dir = repo / "src" / "vendor"
        vendor_dir.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=vendor_dir, capture_output=True, check=True)
        (vendor_dir / "module.py").write_text("module\n")
        subprocess.run(["git", "add", "-A"], cwd=vendor_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "vendor"], cwd=vendor_dir, capture_output=True)

        # Commit in main repo (without adding the nested repo as submodule, just as untracked)
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        # Copy and verify
        copy = tmp_path / "copy"
        shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"))

        verification = verify_tree(copy, manifest)
        # Spec rev. C: a nested repo is recorded as a gitlink and is NOT hashed, so the
        # tree cannot be fully verified -> fail closed. Its contents are not reported
        # as extras (the gitlink reason is enough).
        assert any(s.rstrip("/") == "gitlink:src/vendor" for s in manifest.skipped)
        assert verification.verified is False
        assert not any(e.startswith("src/vendor/") for e in verification.extra_untracked_under_declared_dirs)

    def test_budget_exceeded_zero_max_seconds(self, tmp_path):
        """R1.5: Budget check: max_seconds=0 should fail quickly."""
        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        verification = verify_tree(copy, manifest, max_seconds=0)
        assert verification.verified is False
        assert "budget" in verification.error.lower()

    def test_fifo_not_regular_file_fails(self, tmp_path):
        """R1.5: FIFO at manifest path should fail quickly, not hang."""
        # Skip on non-POSIX systems
        if not hasattr(os, "mkfifo"):
            pytest.skip("os.mkfifo not available (non-POSIX)")

        repo = _init_test_repo(tmp_path / "repo")
        manifest = build_tree_manifest(repo, commit=None)
        assert manifest is not None

        copy = tmp_path / "copy"
        _copy_no_git(repo, copy)

        # Create a FIFO at a manifest path location
        fifo_path = copy / "src" / "pkg" / "a.py"
        fifo_path.unlink()
        try:
            os.mkfifo(str(fifo_path))

            # Verify with a timeout guard
            import threading
            result = [None]

            def verify_with_timeout():
                result[0] = verify_tree(copy, manifest, max_seconds=5)

            thread = threading.Thread(target=verify_with_timeout, daemon=True)
            thread.start()
            thread.join(timeout=10)  # Real timeout

            # Should have completed within the time limit
            assert thread is not None
            assert result[0] is not None
            assert result[0].verified is False
            assert "not a regular file" in result[0].error.lower() or "FIFO" in result[0].error

        finally:
            if fifo_path.exists():
                os.unlink(str(fifo_path))


def test_sourceless_legacy_pyc_is_an_extra(tmp_path):
    """Rev. C: src/pkg/mod.pyc with no mod.py is importable, so it must fail verification.

    Only bytecode inside __pycache__ is excluded by default.
    """
    root = tmp_path / "tree"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "a.py").write_text("x\n")
    manifest = build_tree_manifest(root, commit=None, paths=["src/pkg/a.py"])
    assert manifest is not None

    (root / "src" / "pkg" / "__pycache__").mkdir()
    (root / "src" / "pkg" / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"x")
    ok = verify_tree(root, manifest)
    assert ok.verified is True and ok.error is None

    (root / "src" / "pkg" / "mod.pyc").write_bytes(b"x")
    bad = verify_tree(root, manifest)
    assert bad.verified is False
    assert "src/pkg/mod.pyc" in bad.extra_untracked_under_declared_dirs


def test_non_utf8_name_from_ls_files_is_recorded_as_skipped(tmp_path):
    """Rev. C: a non-UTF-8 path from `git ls-files` is recorded (not dropped) and fails verification."""
    repo = _init_test_repo(tmp_path / "repo")
    try:
        (repo / os.fsdecode(b"src/bad\xff.py")).write_text("y\n")
    except (OSError, UnicodeError):
        pytest.skip("filesystem refuses non-UTF-8 names")
    manifest = build_tree_manifest(repo, commit=None)
    assert manifest is not None
    assert any(s.startswith("non-utf8:") for s in manifest.skipped)
    assert verify_tree(repo, manifest).verified is False
