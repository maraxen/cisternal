"""Debt #2100: a `.git` FILE whose gitdir target does not exist must not shadow the
sidecar/tree-manifest channel.

Measured 2026-09-29 on Engaging: ``~/projects/protamer`` carries a ``.git`` *file*
(``gitdir:`` -> a laptop path that does not exist) plus a myxcel sidecar. The sidecar
channel yielded to the ``.git`` and live git failed, so neither answered
(``provenance_source="none"``, ``hash="unknown"``).

The HARD RULE from debt #2060 is unchanged and is what most of these tests defend: a sha
is surfaced ONLY when verified, and a broken gitlink must never cause a *target repo's*
sha to be surfaced. So the negative controls (withhold) come first, then the fix, then the
controls showing that a ``.git`` git can still resolve keeps winning.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import warnings

import pytest

from cisternal.provenance import channels
from cisternal.provenance.channels import GitState, capture_git_state
from cisternal.provenance.record import PROVENANCE_FILENAME
from cisternal.provenance.tree_manifest import build_tree_manifest

from .test_provenance_channels import _init_repo, _make_verified_tree

DANGLING = "/nonexistent/laptop/path/.git/worktrees/protamer"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("MYXCEL_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(channels, "_WARNED", set())


def _dangle(root, target=DANGLING):
    (root / ".git").write_text(f"gitdir: {target}\n")


def _head(repo) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _assert_sha_absent(state: GitState, sha: str) -> None:
    assert sha not in repr(state)
    assert sha not in json.dumps(dataclasses.asdict(state), default=str)


def _linked_worktree(tmp_path):
    """A linked worktree W of repo S: W/.git is a FILE whose gitdir target exists."""
    s_dir = tmp_path / "S"
    s_dir.mkdir()
    primary = _init_repo(s_dir)
    wt = tmp_path / "W"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "wb"], cwd=primary, check=True)
    assert (wt / ".git").is_file()
    return wt


# --- negative controls first: each of these must WITHHOLD the sha -----------------------


def test_dangling_gitlink_with_modified_tree_is_withheld(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote)
    (remote / "src" / "pkg" / "a.py").write_text("print('modified')\n")

    state = capture_git_state(remote)

    assert state.hash == "unknown"
    assert state.sha is None
    assert state.code_verified is False
    assert state.provenance_source == "unverified-sidecar"
    assert "src/pkg/a.py" in state.verification.mismatched
    _assert_sha_absent(state, head_sha)


def test_dangling_gitlink_with_v1_sidecar_without_manifest_is_withheld(tmp_path):
    root = tmp_path / "protamer"
    root.mkdir()
    _dangle(root)
    claimed = "9d0b87513d484cdf103199d48450c5c5af42e6ef"
    (root / PROVENANCE_FILENAME).write_text(json.dumps({
        "schema_version": 1, "provenance_status": "git", "git_sha": claimed,
        "git_branch": "main", "git_dirty": False, "provenance_root": str(root),
    }))

    state = capture_git_state(root)

    assert state.hash == "unknown"
    assert state.sha is None
    assert state.code_verified is None
    assert state.provenance_source == "unverified-sidecar"
    _assert_sha_absent(state, claimed)


def test_dangling_gitlink_with_manifest_commit_mismatch_is_withheld(tmp_path):
    remote, _ = _make_verified_tree(tmp_path)
    _dangle(remote)
    sidecar = remote / PROVENANCE_FILENAME
    data = json.loads(sidecar.read_text())
    data["git_sha"] = "b" * 40
    sidecar.write_text(json.dumps(data))

    state = capture_git_state(remote)

    assert state.hash == "unknown"
    assert state.code_verified is False
    _assert_sha_absent(state, "b" * 40)


def test_dangling_gitlink_without_any_sidecar_reports_broken_gitlink_and_warns(tmp_path):
    root = tmp_path / "protamer"
    root.mkdir()
    _dangle(root)

    with pytest.warns(UserWarning, match=r"nonexistent/laptop/path"):
        state = capture_git_state(root)

    assert state.hash == "unknown"
    assert state.sha is None
    assert state.provenance_source == "broken-gitlink"
    assert state.code_verified is None


def test_gitlink_to_existing_target_that_git_rejects_fails_closed(tmp_path, monkeypatch):
    """(b) The gitdir target EXISTS but git refuses (ownership / safe.directory). A real
    repository is present and git is the authority we cannot consult, so a sidecar --
    even one whose manifest matches the tree -- must NOT answer for it, and the target
    repo's own sha must not surface either."""
    wt = _linked_worktree(tmp_path)
    wt_head = _head(wt)
    manifest = build_tree_manifest(wt, commit=wt_head)
    assert manifest is not None
    (wt / PROVENANCE_FILENAME).write_text(json.dumps({
        "schema_version": 2, "provenance_status": "git", "git_sha": wt_head,
        "git_branch": "wb", "git_dirty": False, "provenance_root": str(wt),
        "tree_manifest": manifest.to_dict(),
    }))
    # git >= 2.36: makes git treat every repo as foreign-owned (the real safe.directory failure).
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    state = capture_git_state(wt)

    assert state.hash == "unknown"
    assert state.sha is None
    assert state.provenance_source == "none"
    _assert_sha_absent(state, wt_head)


@pytest.mark.parametrize(
    "content",
    ["garbage\n", "gitdir:\n", "gitdir: \n", "gitdir: /a\nextra: /b\n", ""],
    ids=["garbage", "no-space-empty", "empty-target", "multiline", "empty-file"],
)
def test_malformed_gitfile_fails_closed(tmp_path, content):
    remote, head_sha = _make_verified_tree(tmp_path)
    (remote / ".git").write_text(content)

    state = capture_git_state(remote)

    assert state.hash == "unknown"
    assert state.sha is None
    assert state.provenance_source == "none"
    _assert_sha_absent(state, head_sha)


def test_unreadable_gitfile_fails_closed(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote)
    (remote / ".git").chmod(0)
    try:
        state = capture_git_state(remote)
    finally:
        (remote / ".git").chmod(0o644)

    assert state.hash == "unknown"
    assert state.sha is None
    _assert_sha_absent(state, head_sha)


def test_git_directory_never_falls_through_to_sidecar(tmp_path):
    """Only a dangling gitFILE is skipped. An existing `.git` DIRECTORY keeps its old
    behaviour: the ascent stops there, whether or not git can use it."""
    remote, head_sha = _make_verified_tree(tmp_path)
    (remote / ".git").mkdir()

    state = capture_git_state(remote)

    assert state.sha is None
    _assert_sha_absent(state, head_sha)


def test_dangling_gitlink_nested_in_valid_repo_does_not_surface_outer_sha(tmp_path):
    outer_dir = tmp_path / "outer"
    outer_dir.mkdir()
    outer = _init_repo(outer_dir)
    outer_head = _head(outer)
    inner = outer / "inner"
    inner.mkdir()
    _dangle(inner)

    state = capture_git_state(inner)

    assert state.hash == "unknown"
    assert state.sha is None
    _assert_sha_absent(state, outer_head)


# --- the fix ----------------------------------------------------------------------------


def test_dangling_gitlink_with_matching_manifest_surfaces_verified_sha(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote)

    with pytest.warns(UserWarning, match=r"nonexistent/laptop/path"):
        state = capture_git_state(remote)

    assert state.hash == head_sha
    assert state.sha == head_sha
    assert state.code_verified is True
    assert state.provenance_source == "myxcel-sidecar"
    assert state.verification is not None and state.verification.verified is True


def test_dangling_relative_gitlink_with_matching_manifest_surfaces_verified_sha(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote, target="../no-such-gitdir")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        state = capture_git_state(remote)

    assert state.sha == head_sha
    assert state.code_verified is True


def test_dangling_gitlink_cwd_in_subdirectory_still_verifies(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        state = capture_git_state(remote / "src" / "pkg")

    assert state.sha == head_sha
    assert state.code_verified is True


def test_warning_names_the_target_but_never_the_claimed_sha(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        capture_git_state(remote)

    assert any("nonexistent/laptop/path" in str(w.message) for w in caught)
    assert all(head_sha not in str(w.message) for w in caught)


def test_gitlink_warning_is_once_per_process(tmp_path):
    remote, _ = _make_verified_tree(tmp_path)
    _dangle(remote)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        capture_git_state(remote)
        first = sum("nonexistent/laptop/path" in str(w.message) for w in caught)
        capture_git_state(remote)
        second = sum("nonexistent/laptop/path" in str(w.message) for w in caught)

    assert first == 1
    assert second == first


def test_gitlink_warning_under_W_error_does_not_escape(tmp_path):
    remote, _ = _make_verified_tree(tmp_path)
    _dangle(remote)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        state = capture_git_state(remote)

    assert isinstance(state, GitState)


# --- controls: a .git that git can still resolve keeps winning --------------------------


def test_gitfile_pointing_at_valid_worktree_live_git_wins(tmp_path):
    wt = _linked_worktree(tmp_path)
    (wt / "b.txt").write_text("w\n")
    subprocess.run(["git", "add", "b.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "wt"], cwd=wt, check=True)
    (wt / PROVENANCE_FILENAME).write_text(json.dumps({
        "schema_version": 1, "provenance_status": "git", "git_sha": "c" * 40,
        "provenance_root": str(wt),
    }))

    state = capture_git_state(wt)

    assert state.provenance_source == "git"
    assert state.hash == _head(wt)
    assert state.code_verified is True
    _assert_sha_absent(state, "c" * 40)


def test_live_git_wins_even_if_the_gitlink_was_judged_dangling(tmp_path, monkeypatch):
    """Defence in depth (TOCTOU: the target appears after the stat): if git resolves, git wins
    over a sidecar even when `_dangling_gitlink` said the gitfile was dangling."""
    wt = _linked_worktree(tmp_path)
    (wt / PROVENANCE_FILENAME).write_text(json.dumps({
        "schema_version": 1, "provenance_status": "git", "git_sha": "c" * 40,
        "provenance_root": str(wt),
    }))
    monkeypatch.setattr(
        channels, "_dangling_gitlink", lambda p: channels._BrokenGitlink(path=p, target="/gone")
    )

    state = capture_git_state(wt)

    assert state.provenance_source == "git"
    assert state.hash == _head(wt)
    _assert_sha_absent(state, "c" * 40)


# --- a dangling gitfile is only skipped when the SIDECAR sits beside it (challenger B1) -------
# A gitfile BELOW the sidecar's directory is positive evidence that cwd belongs to a different
# checkout. verify_tree does not cover such a tree (gitignored/undeclared dirs), so climbing past
# the gitfile would let the parent's sidecar vouch, code_verified=True, for code nobody checked.


def test_nested_dangling_checkout_below_the_sidecar_is_not_vouched_for(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    nested = remote / "extern" / "tool"  # an undeclared top-level dir: verify_tree cannot see into it
    (nested / "pkg").mkdir(parents=True)
    (nested / "pkg" / "evil.py").write_text("print('not the pushed code')\n")
    _dangle(nested)

    for cwd in (nested, nested / "pkg"):
        state = capture_git_state(cwd)
        assert state.sha is None, cwd
        assert state.code_verified is None, cwd
        assert state.provenance_source == "broken-gitlink", cwd
        _assert_sha_absent(state, head_sha)


def test_nested_dangling_checkout_inside_a_declared_dir_is_not_vouched_for(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    vendored = remote / "src" / "vendored"
    vendored.mkdir()
    _dangle(vendored)

    state = capture_git_state(vendored)

    assert state.sha is None
    assert state.provenance_source == "broken-gitlink"
    _assert_sha_absent(state, head_sha)


def test_two_dangling_gitlinks_in_the_ascent_stop_at_the_first(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    _dangle(remote)  # the protamer shape at the sidecar root ...
    sub = remote / "extern" / "tool"
    sub.mkdir(parents=True)
    _dangle(sub, target="/another/gone/gitdir")  # ... plus a separate dangling checkout below it

    with pytest.warns(UserWarning, match=r"another/gone/gitdir"):
        state = capture_git_state(sub)

    assert state.sha is None
    assert state.provenance_source == "broken-gitlink"
    _assert_sha_absent(state, head_sha)


# --- fail-closed edges of the "definitely absent" test (challenger B2, M2, M3) ---------------


def test_non_utf8_gitdir_target_that_exists_fails_closed(tmp_path, monkeypatch):
    """The gitfile bytes must reach stat() unmangled: decoding with errors='replace' would turn
    a non-UTF-8 target that EXISTS into one that looks absent."""
    import os

    s_dir = tmp_path / "S"
    s_dir.mkdir()
    primary = _init_repo(s_dir)
    wt = tmp_path / os.fsdecode(b"W\xe9")
    try:
        subprocess.run(["git", "worktree", "add", "-q", os.fsencode(wt), "-b", "wb"], cwd=primary, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("filesystem cannot hold a non-UTF-8 path")
    assert b"\xe9" in (wt / ".git").read_bytes()
    wt_head = _head(wt)
    manifest = build_tree_manifest(wt, commit=wt_head)
    assert manifest is not None
    (wt / PROVENANCE_FILENAME).write_text(json.dumps({
        "schema_version": 2, "provenance_status": "git", "git_sha": wt_head,
        "git_branch": "wb", "git_dirty": False, "provenance_root": str(wt),
        "tree_manifest": manifest.to_dict(),
    }))
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    state = capture_git_state(wt)

    assert state.sha is None
    assert state.provenance_source == "none"
    _assert_sha_absent(state, wt_head)


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root ignores directory permissions")
def test_permission_denied_on_target_is_not_evidence_of_absence(tmp_path):
    remote, head_sha = _make_verified_tree(tmp_path)
    locked = tmp_path / "locked"
    (locked / "gitdir").mkdir(parents=True)
    _dangle(remote, target=str(locked / "gitdir"))
    locked.chmod(0)
    try:
        state = capture_git_state(remote)
    finally:
        locked.chmod(0o755)

    assert state.sha is None
    assert state.provenance_source == "none"
    _assert_sha_absent(state, head_sha)


def test_relative_target_is_resolved_against_the_gitfile_not_the_process_cwd(tmp_path, monkeypatch):
    wt = _linked_worktree(tmp_path)
    wt_head = _head(wt)
    (wt / ".git").write_text("gitdir: ../S/.git/worktrees/W\n")  # exists relative to the gitfile only
    manifest = build_tree_manifest(wt, commit=wt_head)
    assert manifest is not None
    (wt / PROVENANCE_FILENAME).write_text(json.dumps({
        "schema_version": 2, "provenance_status": "git", "git_sha": wt_head,
        "git_branch": "wb", "git_dirty": False, "provenance_root": str(wt),
        "tree_manifest": manifest.to_dict(),
    }))
    elsewhere = tmp_path / "elsewhere" / "deeper"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)  # "../S/..." does NOT exist from here
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    state = capture_git_state(wt)

    assert state.sha is None
    assert state.provenance_source == "none"
    _assert_sha_absent(state, wt_head)


def test_broken_gitlink_sentinel_does_not_claim_a_clean_tree(tmp_path):
    root = tmp_path / "protamer"
    root.mkdir()
    _dangle(root)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        state = capture_git_state(root)

    assert state.provenance_source == "broken-gitlink"
    assert state.dirty is True  # unknown state must not read as clean (same as _withheld)


# --- end to end with the REAL writer half (build_provenance_record + build_tree_manifest) ----


def test_e2e_real_writer_worktree_gitfile_copied_off_laptop_verifies(tmp_path):
    """The protamer shape end to end: a linked worktree's sidecar is written by the real writer,
    the tree (including its `.git` gitfile) is copied to a 'cluster' dir, and the original repo --
    the gitfile's target -- is gone. The reader must surface the verified sha; touching a file
    afterwards must withhold it."""
    import shutil

    from cisternal.provenance.capture import build_provenance_record
    from cisternal.provenance.record import to_json_bytes

    wt = _linked_worktree(tmp_path)
    (wt / "src").mkdir()
    (wt / "src" / "m.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add m"], cwd=wt, check=True)
    head = _head(wt)

    manifest = build_tree_manifest(wt, commit=head)
    assert manifest is not None
    cluster = tmp_path / "cluster" / "protamer"
    record, _ = build_provenance_record(
        wt, remote="engaging", project="protamer", provenance_root=str(cluster),
        capture_stage="push", tree_manifest=manifest,
    )
    assert record.schema_version == 2 and record.git_sha == head

    shutil.copytree(wt, cluster)  # carries the gitfile along, as rsync does
    (cluster / PROVENANCE_FILENAME).write_bytes(to_json_bytes(record))
    shutil.rmtree(tmp_path / "S")  # the laptop repo: the gitfile now dangles
    assert (cluster / ".git").is_file()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        state = capture_git_state(cluster)
    assert state.sha == head
    assert state.code_verified is True
    assert state.provenance_source == "myxcel-sidecar"

    (cluster / "src" / "m.py").write_text("x = 2\n")
    channels._WARNED.clear()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        state = capture_git_state(cluster)
    assert state.sha is None
    assert state.code_verified is False
