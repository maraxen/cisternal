"""bathos run-lock manifests are not contamination: they must not make a stamped tree fail verification.

Written BEFORE the implementation. The defect (myxcel debt 2296 class, seen three times in two days on the protamer live titanix
directory): every tracked ``bth run`` writes ``<script>.bth.<run-uuid>.bth.lock.toml`` NEXT TO the script. On a no-.git host that
directory is a declared dir, so the new file is an untracked non-ignored file under it, ``verify_tree`` lists it as an EXTRA, and
the checkout stops verifying (``code_verified=False``, the run's git sha withheld) until the file is committed or moved aside.
The run that produced the lock is exactly the run that verified, so each tracked run un-verified its own host for the next one.

The exemption must be NARROW, because extras detection is the contamination check. A lock manifest is a TOML data file that bathos
itself writes at run time; it cannot be imported or executed. So exactly this basename shape is exempt and nothing else::

    <stem>.bth.<8-4-4-4-12 lowercase hex uuid>.bth.lock.toml

and only while UNTRACKED: a manifest that IS in the tree manifest is verified by content like any other file, so a modified tracked
lock still fails. The exempted names are reported (``exempt_lock_manifests``), never silently dropped.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from cisternal.provenance.tree_manifest import (
    build_tree_manifest,
    is_bathos_lock_manifest,
    verify_tree,
)

UUID = "209401b3-160c-49de-b917-5b1cc41da4d2"
LOCK = f"scripts/run.bth.{UUID}.bth.lock.toml"


def _repo(tmpdir: Path) -> Path:
    tmpdir.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
        subprocess.run(
            ["git", "config", k, v], cwd=tmpdir, capture_output=True, check=True
        )
    (tmpdir / "src" / "pkg").mkdir(parents=True)
    (tmpdir / "src" / "pkg" / "a.py").write_text("def a():\n    pass\n")
    (tmpdir / "scripts").mkdir()
    (tmpdir / "scripts" / "run.py").write_text("print('run')\n")
    (tmpdir / "scripts" / "run.bth.toml").write_text('[experiment]\nhypothesis = "h"\n')
    (tmpdir / ".gitignore").write_text("outputs/\n")
    subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True, check=True
    )
    return tmpdir


def _stamped_copy(tmp_path: Path):
    """A manifest built from a repo and a no-.git copy of it (what a pushed host looks like)."""
    repo = _repo(tmp_path / "repo")
    manifest = build_tree_manifest(repo, commit=None)
    assert manifest is not None and "scripts" in manifest.declared_dirs
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"))
    assert (
        verify_tree(copy, manifest).verified is True
    )  # the control: the stamped copy verifies before anything is added
    return manifest, copy


# ---------------------------------------------------------------- the predicate: exactly one shape


@pytest.mark.parametrize(
    "name",
    [
        LOCK,
        f"run.bth.{UUID}.bth.lock.toml",  # no directory
        f"scripts/deep/er/x.bth.{UUID}.bth.lock.toml",  # any depth
        "scripts/method/rate_probe_v2_within_well.bth.6fe6df73-14d9-458c-892c-dec8cb8de2b1.bth.lock.toml",
        f"scripts/a.b.c.bth.{UUID}.bth.lock.toml",  # a dotted stem
    ],
)
def test_the_exact_bathos_lock_shape_is_recognised(name):
    assert is_bathos_lock_manifest(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "scripts/run.bth.lock.toml",  # no uuid
        f"scripts/run.bth.{UUID}.lock.toml",  # missing the second .bth
        f"scripts/run.bth.{UUID}.bth.lock.py",  # IMPORTABLE extension: must stay an extra
        f"scripts/run.bth.{UUID}.bth.lock.toml.py",
        f"scripts/run.bth.{UUID}.bth.lock.toml.bak",
        f"scripts/run.bth.{UUID.upper()}.bth.lock.toml",  # bathos run ids are lowercase
        "scripts/run.bth.209401b3-160c-49de-b917.bth.lock.toml",  # truncated uuid
        "scripts/run.bth.209401b3-160c-49de-b917-5b1cc41da4dg.bth.lock.toml",  # non-hex
        f"scripts/.bth.{UUID}.bth.lock.toml",  # empty stem
        f"scripts/run.bth.{UUID}.bth.lock.toml/evil.py",  # a FILE inside a directory named like a lock
        "scripts/run.bth.toml",  # the sidecar itself
        "scripts/evil.py",
        "",
        f"scripts/run.bth.{UUID}.bth.lock.toml\n",  # `$` would match before a trailing newline; the shape is EXACT
        f"scripts/run.bth.{UUID}.bth.lock.toml\r",
        f"scripts/run.bth.{UUID}.bth.lock.toml ",
        f" scripts/run.bth.{UUID}.bth.lock.toml\n\n",
    ],
)
def test_near_misses_are_not_exempt(name):
    assert is_bathos_lock_manifest(name) is False


# ---------------------------------------------------------------- verify_tree


def test_an_untracked_lock_manifest_is_not_an_extra_and_is_reported(tmp_path):
    manifest, copy = _stamped_copy(tmp_path)
    (copy / LOCK).write_text('[manifest]\nrun_id = "x"\n')
    v = verify_tree(copy, manifest)
    assert v.verified is True and v.error is None
    assert v.extra_untracked_under_declared_dirs == ()
    assert v.exempt_lock_manifests == (LOCK,)  # exempted, and visibly so


def test_a_name_with_a_trailing_newline_is_not_the_exact_shape_and_stays_an_extra(
    tmp_path,
):
    # code review finding: re.match with `$` also matched a name ending in "\n" (git -z and os.walk both return such names)
    manifest, copy = _stamped_copy(tmp_path)
    name = LOCK + "\n"
    try:
        (copy / name).write_text("x\n")
    except OSError:
        pytest.skip("filesystem refuses a newline in a file name")
    v = verify_tree(copy, manifest)
    assert v.verified is False
    assert name in v.extra_untracked_under_declared_dirs
    assert v.exempt_lock_manifests == ()


def test_the_exemption_is_logged_so_it_is_visible_to_anyone_who_only_sees_code_verified(
    tmp_path, caplog
):
    # code review finding: the exempted names live on TreeVerification, which downstream provenance records do not carry
    manifest, copy = _stamped_copy(tmp_path)
    (copy / LOCK).write_text("a\n")
    with caplog.at_level(logging.INFO, logger="cisternal.provenance.tree_manifest"):
        assert verify_tree(copy, manifest).verified is True
    assert any(
        LOCK in r.getMessage() and "exempt" in r.getMessage().lower()
        for r in caplog.records
    )


def test_nothing_is_logged_when_nothing_was_exempt(tmp_path, caplog):
    manifest, copy = _stamped_copy(tmp_path)
    with caplog.at_level(logging.INFO, logger="cisternal.provenance.tree_manifest"):
        assert verify_tree(copy, manifest).verified is True
    assert not [r for r in caplog.records if "exempt" in r.getMessage().lower()]


def test_several_locks_at_several_depths_are_all_exempt(tmp_path):
    manifest, copy = _stamped_copy(tmp_path)
    other = (
        "scripts/sub/dir/other.bth.6fe6df73-14d9-458c-892c-dec8cb8de2b1.bth.lock.toml"
    )
    (copy / "scripts" / "sub" / "dir").mkdir(parents=True)
    (copy / LOCK).write_text("a\n")
    (copy / other).write_text("b\n")
    v = verify_tree(copy, manifest)
    assert v.verified is True
    assert v.exempt_lock_manifests == tuple(sorted((LOCK, other)))


def test_a_real_extra_beside_a_lock_still_fails_and_only_the_extra_is_listed(tmp_path):
    manifest, copy = _stamped_copy(tmp_path)
    (copy / LOCK).write_text("a\n")
    (copy / "scripts" / "evil.py").write_text("import os\n")
    v = verify_tree(copy, manifest)
    assert v.verified is False
    assert v.extra_untracked_under_declared_dirs == ("scripts/evil.py",)
    assert v.exempt_lock_manifests == (LOCK,)


@pytest.mark.parametrize(
    "bad_name",
    [
        f"scripts/run.bth.{UUID}.bth.lock.py",  # importable: the reason the exemption is narrow
        "scripts/run.bth.lock.toml",
        f"scripts/run.bth.{UUID.upper()}.bth.lock.toml",
    ],
)
def test_near_miss_names_still_fail_verification(tmp_path, bad_name):
    manifest, copy = _stamped_copy(tmp_path)
    (copy / bad_name).write_text("x\n")
    v = verify_tree(copy, manifest)
    assert v.verified is False
    assert bad_name in v.extra_untracked_under_declared_dirs
    assert v.exempt_lock_manifests == ()


def test_a_file_inside_a_directory_named_like_a_lock_is_still_an_extra(tmp_path):
    manifest, copy = _stamped_copy(tmp_path)
    (copy / LOCK).mkdir()  # a directory whose NAME matches the lock shape
    (copy / LOCK / "evil.py").write_text("import os\n")
    v = verify_tree(copy, manifest)
    assert v.verified is False
    assert f"{LOCK}/evil.py" in v.extra_untracked_under_declared_dirs


def test_a_tracked_lock_is_verified_by_content_so_modifying_it_still_fails(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / LOCK).write_text("original\n")
    manifest = build_tree_manifest(repo, commit=None, paths=[p for p in _ls(repo) if p])
    assert (
        manifest is not None and LOCK in manifest.files
    )  # it is TRACKED by this manifest
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git"))
    assert verify_tree(copy, manifest).verified is True
    (copy / LOCK).write_text("tampered\n")
    v = verify_tree(copy, manifest)
    assert (
        v.verified is False and LOCK in v.mismatched
    )  # the exemption does not reach tracked files


def _ls(repo: Path) -> list[str]:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return [p.decode() for p in out.split(b"\0")]


def test_the_python_walk_fallback_exempts_locks_too_and_still_catches_extras(
    tmp_path, monkeypatch
):
    manifest, copy = _stamped_copy(tmp_path)
    (copy / LOCK).write_text("a\n")
    (copy / "scripts" / "evil.py").write_text("x\n")
    original_run = subprocess.run

    def no_git(*args, **kwargs):
        if args[0][0] == "git":
            raise FileNotFoundError("git not found")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_git)
    v = verify_tree(copy, manifest)
    assert v.extras_ignore_aware is False  # we really did take the fallback path
    assert v.extra_untracked_under_declared_dirs == ("scripts/evil.py",)
    assert v.exempt_lock_manifests == (LOCK,)


def test_the_cwd_scan_path_exempts_locks_too(tmp_path):
    manifest, copy = _stamped_copy(tmp_path)
    undeclared = copy / "tools"  # not one of the manifest's declared dirs
    undeclared.mkdir()
    lock = f"tools/t.bth.{UUID}.bth.lock.toml"
    (copy / lock).write_text("a\n")
    v = verify_tree(copy, manifest, cwd=undeclared)
    assert v.verified is True and v.exempt_lock_manifests == (lock,)
    (undeclared / "evil.py").write_text("x\n")
    bad = verify_tree(copy, manifest, cwd=undeclared)
    assert (
        bad.verified is False
        and "tools/evil.py" in bad.extra_untracked_under_declared_dirs
    )


def test_the_fallback_walk_of_the_cwd_dir_exempts_locks_too(tmp_path, monkeypatch):
    manifest, copy = _stamped_copy(tmp_path)
    undeclared = copy / "tools"
    undeclared.mkdir()
    lock = f"tools/t.bth.{UUID}.bth.lock.toml"
    (copy / lock).write_text("a\n")
    original_run = subprocess.run

    def no_git(*args, **kwargs):
        if args[0][0] == "git":
            raise FileNotFoundError("git not found")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_git)
    v = verify_tree(copy, manifest, cwd=undeclared)
    assert v.extras_ignore_aware is False
    assert v.verified is True and v.exempt_lock_manifests == (lock,)
    (undeclared / "evil.py").write_text("x\n")
    bad = verify_tree(copy, manifest, cwd=undeclared)
    assert bad.verified is False and bad.extra_untracked_under_declared_dirs == (
        "tools/evil.py",
    )


def test_verifying_twice_is_stable_and_nothing_else_changes(tmp_path):
    manifest, copy = _stamped_copy(tmp_path)
    before = verify_tree(copy, manifest)
    (copy / LOCK).write_text("a\n")
    after = verify_tree(copy, manifest)
    assert (after.n_files, after.n_match, after.mismatched, after.missing) == (
        before.n_files,
        before.n_match,
        before.mismatched,
        before.missing,
    )
    assert (
        after.tree_id == before.tree_id
    )  # the lock is not folded into the recomputed tree id
    assert before.exempt_lock_manifests == ()
