"""Submodule gitlinks in the tree manifest (task 261102_gitlink-manifest).

A submodule is recorded as a ``160000`` entry carrying its pinned commit sha, verified at
build time (initialised, HEAD == pin) and, on the no-.git reader, by being absent or an empty
directory. Everything else about a directory (plain dir, untracked nested repo, unknown commit)
keeps the old fail-closed ``gitlink:<path>`` skip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from cisternal.provenance.capture import clean_git_env
from cisternal.provenance.tree_manifest import (
    GITLINK_MODE,
    TreeManifest,
    build_tree_manifest,
    verify_tree,
)

_IDENT = ["-c", "user.email=test@example.com", "-c", "user.name=Test User"]
SUB = "vendor/sub"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *_IDENT, "-c", "protocol.file.allow=always", *args],
        cwd=cwd, capture_output=True, check=True, env=clean_git_env(),
    )
    return proc.stdout.decode().strip()


def _make_sub_repo(path: Path) -> str:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    (path / "mod.py").write_text("x = 1\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "sub")
    return _git(path, "rev-parse", "HEAD")


def _make_superproject(tmp_path: Path) -> tuple[Path, str, str]:
    """Return (superproject, its HEAD, the submodule pin)."""
    sub_origin = tmp_path / "sub_origin"
    _make_sub_repo(sub_origin)
    sup = tmp_path / "super"
    sup.mkdir()
    _git(sup, "init", "-q")
    (sup / "main.py").write_text("print(1)\n")
    _git(sup, "add", "-A")
    _git(sup, "submodule", "add", "-q", str(sub_origin), SUB)
    _git(sup, "commit", "-q", "-m", "super")
    return sup, _git(sup, "rev-parse", "HEAD"), _git(sup, "rev-parse", f"HEAD:{SUB}")


def _remote_copy(manifest: TreeManifest, src: Path, dst: Path, *, make_gitlink_dir: bool = True) -> Path:
    """Mimic a push: only the manifest's non-gitlink files, no .git; the gitlink is an empty dir."""
    dst.mkdir()
    for rel, (mode, _blob) in manifest.files.items():
        if mode == GITLINK_MODE:
            if make_gitlink_dir:
                (dst / rel).mkdir(parents=True)
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst / rel, follow_symlinks=False)
    return dst


# --- matching pin -> verified -------------------------------------------------------------


def test_matching_pin_is_recorded_and_verifies_on_a_no_git_copy(tmp_path):
    sup, head, pin = _make_superproject(tmp_path)

    manifest = build_tree_manifest(sup, commit=head)

    assert manifest is not None
    assert manifest.files[SUB] == (GITLINK_MODE, pin)
    assert manifest.skipped == ()
    assert manifest.matches_commit is True
    # With every tracked path covered, the manifest tree id IS git's own tree object id: the
    # 160000 entry is encoded exactly as git encodes a gitlink.
    assert manifest.tree_id == _git(sup, "rev-parse", "HEAD^{tree}")

    remote = _remote_copy(manifest, sup, tmp_path / "remote")
    v = verify_tree(remote, manifest)
    assert v.verified is True, v
    assert v.tree_id == manifest.tree_id


def test_gitlink_path_absent_on_the_reader_still_verifies(tmp_path):
    sup, head, _pin = _make_superproject(tmp_path)
    manifest = build_tree_manifest(sup, commit=head)
    assert manifest is not None

    remote = _remote_copy(manifest, sup, tmp_path / "remote", make_gitlink_dir=False)

    v = verify_tree(remote, manifest)
    assert v.verified is True, v
    assert v.missing == ()


def test_manifest_round_trips_with_a_gitlink_entry(tmp_path):
    sup, head, pin = _make_superproject(tmp_path)
    manifest = build_tree_manifest(sup, commit=head)
    assert manifest is not None

    again = TreeManifest.from_dict(manifest.to_dict())

    assert again == manifest
    assert again is not None and again.files[SUB] == (GITLINK_MODE, pin)


# --- pin mismatch -> not verified ---------------------------------------------------------


def test_checked_out_head_differs_from_pin_is_skipped_and_not_verified(tmp_path):
    sup, head, pin = _make_superproject(tmp_path)
    sub = sup / SUB
    (sub / "mod.py").write_text("x = 2\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "drift")
    assert _git(sub, "rev-parse", "HEAD") != pin  # precondition: the submodule moved off its pin

    manifest = build_tree_manifest(sup, commit=head)

    assert manifest is not None
    assert SUB not in manifest.files
    assert f"gitlink-mismatch:{SUB}" in manifest.skipped
    remote = _remote_copy(manifest, sup, tmp_path / "remote")
    assert verify_tree(remote, manifest).verified is False


# --- uninitialised submodule -> skipped with a reason, verdict unchanged --------------------


def test_uninitialised_submodule_is_skipped_with_reason_and_never_borrows_the_superproject_head(tmp_path):
    sup, head, _pin = _make_superproject(tmp_path)
    clone = tmp_path / "clone"  # a plain clone leaves the submodule an empty directory
    subprocess.run(["git", "clone", "-q", str(sup), str(clone)], check=True, capture_output=True, env=clean_git_env())
    assert (clone / SUB).is_dir() and not any((clone / SUB).iterdir())  # precondition

    manifest = build_tree_manifest(clone, commit=head)

    assert manifest is not None
    assert f"gitlink-uninitialized:{SUB}" in manifest.skipped
    # `git -C <empty dir> rev-parse HEAD` answers with the SUPERPROJECT's HEAD; it must not leak in.
    assert SUB not in manifest.files
    assert head not in {blob for _mode, blob in manifest.files.values()}
    remote = _remote_copy(manifest, clone, tmp_path / "remote")
    assert verify_tree(remote, manifest).verified is False


# --- reader refuses unhashed content under a pinned path ------------------------------------


def test_reader_rejects_a_pinned_path_that_holds_content(tmp_path):
    sup, head, _pin = _make_superproject(tmp_path)
    manifest = build_tree_manifest(sup, commit=head)
    assert manifest is not None
    remote = _remote_copy(manifest, sup, tmp_path / "remote")
    (remote / SUB / "evil.py").write_text("print('not in the manifest')\n")

    v = verify_tree(remote, manifest)

    assert v.verified is False
    assert SUB in v.mismatched


def test_reader_rejects_a_symlink_or_file_at_a_pinned_path(tmp_path):
    sup, head, _pin = _make_superproject(tmp_path)
    manifest = build_tree_manifest(sup, commit=head)
    assert manifest is not None

    as_file = _remote_copy(manifest, sup, tmp_path / "as_file", make_gitlink_dir=False)
    (as_file / SUB).parent.mkdir(parents=True, exist_ok=True)
    (as_file / SUB).write_text("a file where a submodule was pinned\n")
    assert verify_tree(as_file, manifest).verified is False

    as_link = _remote_copy(manifest, sup, tmp_path / "as_link", make_gitlink_dir=False)
    (as_link / SUB).parent.mkdir(parents=True, exist_ok=True)
    (as_link / SUB).symlink_to(sup)  # a link can point at arbitrary code
    assert verify_tree(as_link, manifest).verified is False


# --- non-submodule directories keep the old behaviour ---------------------------------------


def test_commit_none_keeps_the_old_gitlink_skip_for_a_submodule_path(tmp_path):
    sup, _head, _pin = _make_superproject(tmp_path)

    manifest = build_tree_manifest(sup, commit=None)

    assert manifest is not None
    assert f"gitlink:{SUB}" in manifest.skipped
    assert SUB not in manifest.files


def test_plain_untracked_nested_repo_keeps_the_old_gitlink_skip_even_with_a_commit(tmp_path):
    sup, head, _pin = _make_superproject(tmp_path)
    nested = sup / "scratch" / "nested"
    _make_sub_repo(nested)  # a repo inside the tree that is NOT a gitlink in `head`

    manifest = build_tree_manifest(sup, commit=head)

    assert manifest is not None
    assert any(s.rstrip("/") == "gitlink:scratch/nested" for s in manifest.skipped)
    assert not any(p.startswith("scratch/nested") for p in manifest.files)
    # The real submodule alongside it is still covered, but the manifest as a whole fails closed.
    assert manifest.files[SUB][0] == GITLINK_MODE
    remote = _remote_copy(manifest, sup, tmp_path / "remote")
    assert verify_tree(remote, manifest).verified is False
