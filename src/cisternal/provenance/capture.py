"""Git commit/dirty/content-id capture, in mirrored sync and async pairs.

Two independent problems, both solved here:

1. **Resolve HEAD + dirty state**, loudly on failure. This is the primitive
   that was missing everywhere before this module existed: sweetprots had a
   bare ``except Exception: pass`` around it (found via jury audit,
   2026-08-27); myxcel's ``cli.py`` had an equivalent bare-except with a
   ``"nogit"`` fallback; naurmalade had no error handling at all. See
   `resolve_git_commit` / `aresolve_git_commit`.

2. **Identify a dirty tree's actual content**, not just a boolean. A
   ``dirty=True`` flag alone can't distinguish two runs at the same HEAD with
   materially different uncommitted edits. `compute_dirty_content_id` /
   `acompute_dirty_content_id` implement myxcel's D3 algorithm: a git tree
   OID computed from a throwaway index (falls back to a SHA-256 of the diff
   if the tree algorithm fails). Ported verbatim, including the linked-
   worktree fix (`rev-parse --git-path index`, not the literal
   ``<root>/.git/index`` -- a linked worktree's ``.git`` is a FILE, so the
   literal path breaks there).

Every function here is best-effort by construction for the record-building
path (never raises -- degrades to a null/`"unavailable"` field plus a logged
reason), EXCEPT `resolve_git_commit`/`aresolve_git_commit` themselves, which
support `strict=True` to raise instead when a caller actually wants to know
about a failure rather than silently degrade.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .record import ProvenanceRecord

_CaptureStage = Literal["push", "submit"]
_SyncState = Literal["verified", "drifted", "unverified"]
_ProvenanceStatus = Literal["git", "nogit", "unavailable"]

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 60.0
_WRITE_TREE_TIMEOUT = 60.0

GIT_REPO_LOCATION_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)


def clean_git_env() -> dict[str, str]:
    """Environment for git subprocess calls with repo-location overrides stripped.

    GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE (set whenever the calling process is
    itself running inside a git hook) override `-C <path>` repo discovery
    entirely -- confirmed empirically in myxcel's own test suite. Without
    stripping them, `git -C <path> ...` invoked from within a git hook
    context silently targets the ambient repo instead of `<path>`.
    """
    return {k: v for k, v in os.environ.items() if k not in GIT_REPO_LOCATION_ENV_VARS}


class GitResolutionError(RuntimeError):
    """Raised by `resolve_git_commit(..., strict=True)` on any resolution failure."""


@dataclass(frozen=True)
class GitCommitInfo:
    commit: str | None
    is_dirty: bool | None
    resolved_from: str


def _run_git(args: list[str], cwd: Path, timeout: float = _GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=clean_git_env(),
        timeout=timeout,
    )


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Send SIGTERM to the process group, then SIGKILL after a 2s grace period."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
            return
        except asyncio.TimeoutError:
            os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _arun_git(
    args: list[str], cwd: Path, timeout: float = _GIT_TIMEOUT
) -> tuple[int, bytes, bytes]:
    """Run `git -C <cwd> <args>` async, with a wall-clock timeout that kills the
    whole process group (not just the direct child) on expiry."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(cwd), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env=clean_git_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_process_group(proc)
        raise TimeoutError(f"git {' '.join(args)} timed out after {timeout}s in {cwd}")
    finally:
        try:
            await proc.wait()
        except Exception as exc:
            # Best-effort zombie reap after the real error (if any) is already
            # captured above -- logged rather than silently swallowed (S110).
            logger.debug("reaping git subprocess for %s failed: %s", args, exc)
    # communicate() has already completed above, so the process has exited and
    # returncode is set; the Optional in asyncio's own type stub reflects the
    # general Process API (before exit), not this call site. `assert` would be
    # stripped under `python -O`, silently letting a real None through, so
    # this is a real check, not a debug-only one.
    if proc.returncode is None:
        raise RuntimeError(f"git {' '.join(args)} in {cwd} exited with no returncode after communicate()")
    return proc.returncode, stdout, stderr


def _fail(msg: str, resolved_from: str, strict: bool) -> GitCommitInfo:
    if strict:
        raise GitResolutionError(msg)
    logger.warning(msg)
    return GitCommitInfo(commit=None, is_dirty=None, resolved_from=resolved_from)


def resolve_git_commit(path: Path | str, *, strict: bool = False) -> GitCommitInfo:
    """Resolve the git commit SHA and dirty-tree status for the repo containing `path`.

    `path` must be a directory inside the repo's working tree -- git walks up
    from any directory to find `.git`, but `git -C <file>` fails outright.
    Pass a package's containing directory (e.g. `Path(pkg.__file__).parent`),
    not the `__init__.py` file itself.

    On any failure (git not found, timeout, non-repo path, `rev-parse`
    failure): `strict=False` (default) logs a WARNING and returns
    `commit=None`; `strict=True` raises `GitResolutionError`. Never silently
    returns None without logging -- that was the original bug this function
    replaces (sweetprots' `_resolve_git_commit`, jury audit 2026-08-27).
    """
    path = Path(path)
    resolved_from = str(path)

    try:
        rev = _run_git(["rev-parse", "HEAD"], cwd=path)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _fail(f"git invocation failed for {resolved_from}: {exc}", resolved_from, strict)

    if rev.returncode != 0:
        return _fail(
            f"git rev-parse HEAD failed for {resolved_from} "
            f"(exit {rev.returncode}): {rev.stderr.strip()}",
            resolved_from, strict,
        )
    commit = rev.stdout.strip()

    is_dirty: bool | None
    try:
        status = _run_git(["status", "--porcelain"], cwd=path)
        is_dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        if status.returncode != 0:
            logger.warning(
                "git status --porcelain failed for %s (exit %d): %s -- dirty-state unknown",
                resolved_from, status.returncode, status.stderr.strip(),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("git status --porcelain failed for %s: %s -- dirty-state unknown", resolved_from, exc)
        is_dirty = None

    if is_dirty:
        logger.warning(
            "%s has a DIRTY working tree at commit %s -- this commit SHA does not "
            "fully describe the code that actually ran",
            resolved_from, commit,
        )
    return GitCommitInfo(commit=commit, is_dirty=is_dirty, resolved_from=resolved_from)


async def aresolve_git_commit(path: Path | str, *, strict: bool = False) -> GitCommitInfo:
    """Async twin of `resolve_git_commit`. See its docstring for behavior."""
    path = Path(path)
    resolved_from = str(path)

    try:
        rc, out, err = await _arun_git(["rev-parse", "HEAD"], cwd=path)
    except (OSError, TimeoutError) as exc:
        return _fail(f"git invocation failed for {resolved_from}: {exc}", resolved_from, strict)

    if rc != 0:
        return _fail(
            f"git rev-parse HEAD failed for {resolved_from} "
            f"(exit {rc}): {err.decode(errors='replace').strip()}",
            resolved_from, strict,
        )
    commit = out.decode().strip()

    is_dirty: bool | None
    try:
        src, sout, serr = await _arun_git(["status", "--porcelain"], cwd=path)
        is_dirty = bool(sout.decode().strip()) if src == 0 else None
        if src != 0:
            logger.warning(
                "git status --porcelain failed for %s (exit %d): %s -- dirty-state unknown",
                resolved_from, src, serr.decode(errors="replace").strip(),
            )
    except (OSError, TimeoutError) as exc:
        logger.warning("git status --porcelain failed for %s: %s -- dirty-state unknown", resolved_from, exc)
        is_dirty = None

    if is_dirty:
        logger.warning(
            "%s has a DIRTY working tree at commit %s -- this commit SHA does not "
            "fully describe the code that actually ran",
            resolved_from, commit,
        )
    return GitCommitInfo(commit=commit, is_dirty=is_dirty, resolved_from=resolved_from)


def compute_dirty_content_id(root: Path) -> str | None:
    """Sync twin of `acompute_dirty_content_id`. See its docstring."""
    tree_id = _compute_tree_oid(root)
    if tree_id is not None:
        return f"tree:{tree_id}"
    diff_hash = _compute_diff_sha256(root)
    if diff_hash is not None:
        return f"diff-sha256:{diff_hash}"
    return None


async def acompute_dirty_content_id(root: Path) -> str | None:
    """Compute dirty_content_id using the tree algorithm, with diff-sha256 fallback.

    Returns "tree:<40-hex>" on success, "diff-sha256:<64-hex>" on tree
    failure, or None if both algorithms fail. See D3 of
    myxcel's `260820_bathos-git-provenance-sidecar-spec.md` for the full
    rationale (tree OID is size-independent and covers untracked-but-not-
    ignored files; a diff hash varies with diff.algorithm/textconv/locale).

    Cross-tag comparability rule (normative for consumers): two
    dirty_content_id values are comparable ONLY if their tag prefixes match.
    `tree:X` vs `diff-sha256:Y` means "relationship unknown", never
    "different content".
    """
    tree_id = await _acompute_tree_oid(root)
    if tree_id is not None:
        return f"tree:{tree_id}"
    diff_hash = await _acompute_diff_sha256(root)
    if diff_hash is not None:
        return f"diff-sha256:{diff_hash}"
    return None


def _compute_tree_oid(root: Path) -> str | None:
    """Compute git tree OID from a throwaway temp index (sync).

    Uses `git rev-parse --git-path index` (NOT the literal `<root>/.git/index`)
    to find the real index -- a linked worktree's `.git` is a FILE, not a
    directory, so the literal path raises `NotADirectoryError` there.
    """
    try:
        real_index_result = _run_git(["rev-parse", "--git-path", "index"], cwd=root, timeout=_GIT_TIMEOUT)
        if real_index_result.returncode != 0:
            return None
        real_index_str = real_index_result.stdout.strip()
        real_index = (
            Path(real_index_str) if Path(real_index_str).is_absolute()
            else (Path(root) / real_index_str).resolve()
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".index") as tmp_file:
            tmp_index = Path(tmp_file.name)

        try:
            if real_index.exists():
                try:
                    shutil.copyfile(real_index, tmp_index)
                except OSError:
                    pass  # git add -A below will create a fresh index

            env = clean_git_env() | {"GIT_INDEX_FILE": str(tmp_index)}

            add_result = subprocess.run(
                ["git", "-C", str(root), "add", "-A"],
                capture_output=True, env=env, timeout=_WRITE_TREE_TIMEOUT,
            )
            if add_result.returncode != 0:
                return None

            write_tree_result = subprocess.run(
                ["git", "-C", str(root), "write-tree"],
                capture_output=True, text=True, env=env, timeout=_WRITE_TREE_TIMEOUT,
            )
            if write_tree_result.returncode != 0:
                return None

            tree_oid = write_tree_result.stdout.strip()
            if len(tree_oid) == 40 and all(c in "0123456789abcdef" for c in tree_oid):
                return tree_oid
            return None
        finally:
            try:
                tmp_index.unlink(missing_ok=True)
            except OSError:
                pass
    except (OSError, subprocess.TimeoutExpired):
        return None


async def _acompute_tree_oid(root: Path) -> str | None:
    """Async twin of `_compute_tree_oid`."""
    try:
        rc, out, _err = await _arun_git(["rev-parse", "--git-path", "index"], cwd=root)
        if rc != 0:
            return None
        real_index_str = out.decode().strip()
        real_index = (
            Path(real_index_str) if Path(real_index_str).is_absolute()
            else (Path(root) / real_index_str).resolve()
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".index") as tmp_file:
            tmp_index = Path(tmp_file.name)

        try:
            if real_index.exists():
                try:
                    shutil.copyfile(real_index, tmp_index)
                except OSError:
                    pass

            env = clean_git_env() | {"GIT_INDEX_FILE": str(tmp_index)}

            add_proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(root), "add", "-A",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
                start_new_session=True,
            )
            try:
                await asyncio.wait_for(add_proc.communicate(), timeout=_WRITE_TREE_TIMEOUT)
            except asyncio.TimeoutError:
                await _kill_process_group(add_proc)
                return None
            if add_proc.returncode != 0:
                return None

            wt_proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(root), "write-tree",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
                start_new_session=True,
            )
            try:
                wt_out, _wt_err = await asyncio.wait_for(wt_proc.communicate(), timeout=_WRITE_TREE_TIMEOUT)
            except asyncio.TimeoutError:
                await _kill_process_group(wt_proc)
                return None
            if wt_proc.returncode != 0:
                return None

            tree_oid = wt_out.decode().strip()
            if len(tree_oid) == 40 and all(c in "0123456789abcdef" for c in tree_oid):
                return tree_oid
            return None
        finally:
            try:
                tmp_index.unlink(missing_ok=True)
            except OSError:
                pass
    except (OSError, asyncio.TimeoutError, TimeoutError):
        return None


_DIFF_ARGS = [
    "-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff", "--binary",
    "--full-index", "HEAD",
]


def _compute_diff_sha256(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *_DIFF_ARGS],
            capture_output=True, env=clean_git_env(), timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


async def _acompute_diff_sha256(root: Path) -> str | None:
    try:
        rc, out, _err = await _arun_git(_DIFF_ARGS, cwd=root)
    except (OSError, TimeoutError):
        return None
    if rc != 0:
        return None
    return hashlib.sha256(out).hexdigest()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def build_provenance_record(
    local_root: Path,
    remote: str,
    project: str,
    provenance_root: str,
    capture_stage: _CaptureStage,
    sync_state: _SyncState = "verified",
    worktree: str | None = None,
    compute_dirty_content_id_flag: bool = True,
    myxcel_version: str = "",
) -> tuple[ProvenanceRecord, list[str]]:
    """Sync twin of `abuild_provenance_record`. See its docstring."""
    warnings: list[str] = []
    computed_at = _now_iso()

    def _record(status: _ProvenanceStatus, sha: str | None = None, branch: str | None = None,
                dirty: bool | None = None, content_id: str | None = None) -> ProvenanceRecord:
        return ProvenanceRecord(
            schema_version=1, provenance_status=status, git_sha=sha, git_branch=branch,
            git_dirty=dirty, dirty_content_id=content_id, capture_stage=capture_stage,
            sync_state=sync_state, computed_at=computed_at, provenance_root=provenance_root,
            remote=remote, project=project, worktree=worktree, myxcel_version=myxcel_version,
        )

    info = resolve_git_commit(local_root)
    if info.commit is None:
        if not local_root.is_dir():
            warnings.append(f"Local root not found: {local_root}")
            return _record("unavailable"), warnings
        if not (local_root / ".git").exists():
            return _record("nogit"), warnings
        warnings.append(f"git rev-parse HEAD failed in {local_root}")
        return _record("unavailable"), warnings

    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local_root)
    git_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    if git_branch is None:
        warnings.append(f"git rev-parse --abbrev-ref HEAD failed in {local_root}")
        git_branch = "unknown"

    git_dirty = bool(info.is_dirty)
    dirty_content_id: str | None = None
    if git_dirty and compute_dirty_content_id_flag:
        dirty_content_id = compute_dirty_content_id(local_root)
        if dirty_content_id is None:
            warnings.append(f"Could not compute dirty_content_id for {local_root}")

    return _record("git", sha=info.commit, branch=git_branch, dirty=git_dirty, content_id=dirty_content_id), warnings


async def abuild_provenance_record(
    local_root: Path,
    remote: str,
    project: str,
    provenance_root: str,
    capture_stage: _CaptureStage,
    sync_state: _SyncState = "verified",
    worktree: str | None = None,
    compute_dirty_content_id_flag: bool = True,
    myxcel_version: str = "",
) -> tuple[ProvenanceRecord, list[str]]:
    """Compute the provenance record for a local git tree.

    Returns (record, warnings). Never raises: every failure returns a record
    with provenance_status="unavailable" plus a warning string.

    `compute_dirty_content_id_flag=False` skips the git-tree-OID / write-tree
    step: callers that only need the cheap fields (e.g. a dry-run's dirty
    warning) must not pay for `git add -A` + `git write-tree` against a
    throwaway index, which writes loose objects into the object store -- a
    dry run is supposed to touch nothing.
    """
    warnings: list[str] = []
    computed_at = _now_iso()

    def _record(status: _ProvenanceStatus, sha: str | None = None, branch: str | None = None,
                dirty: bool | None = None, content_id: str | None = None) -> ProvenanceRecord:
        return ProvenanceRecord(
            schema_version=1, provenance_status=status, git_sha=sha, git_branch=branch,
            git_dirty=dirty, dirty_content_id=content_id, capture_stage=capture_stage,
            sync_state=sync_state, computed_at=computed_at, provenance_root=provenance_root,
            remote=remote, project=project, worktree=worktree, myxcel_version=myxcel_version,
        )

    info = await aresolve_git_commit(local_root)
    if info.commit is None:
        if not local_root.is_dir():
            warnings.append(f"Local root not found: {local_root}")
            return _record("unavailable"), warnings
        if not (local_root / ".git").exists():
            return _record("nogit"), warnings
        warnings.append(f"git rev-parse HEAD failed in {local_root}")
        return _record("unavailable"), warnings

    rc, out, _err = await _arun_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local_root)
    git_branch = out.decode().strip() if rc == 0 else None
    if git_branch is None:
        warnings.append(f"git rev-parse --abbrev-ref HEAD failed in {local_root}")
        git_branch = "unknown"

    git_dirty = bool(info.is_dirty)
    dirty_content_id: str | None = None
    if git_dirty and compute_dirty_content_id_flag:
        dirty_content_id = await acompute_dirty_content_id(local_root)
        if dirty_content_id is None:
            warnings.append(f"Could not compute dirty_content_id for {local_root}")

    return _record("git", sha=info.commit, branch=git_branch, dirty=git_dirty, content_id=dirty_content_id), warnings
