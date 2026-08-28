"""Make a run's git provenance durable, not merely recorded.

`channels.py`/`capture.py` capture WHAT the repo looked like. This module
makes that capture survive, which is a separate problem and the one that
actually fails in practice. Ported from `bathos/git_pin.py`.

Motivating measurement (bathos, tev_design catalog, 2026-08-18): `git_hash`
was populated on 345/345 runs -- capture is not the gap -- but only 40.6% of
those hashes still resolved to a commit, and 92.2% of runs executed on a
DIRTY tree. So the median run recorded a clean-looking hash describing a tree
that never existed, and two runs in five cited a commit that is simply gone.
A recorded hash that cannot be resolved, or that describes a different tree
than the one that ran, is a false attestation: the field reads as a
reproducibility guarantee it cannot back.

Three mechanisms, in order of how much they buy:

1. **Worktree snapshot.** When the tree is dirty, commit its actual contents
   to a real object and record THAT, so the provenance describes what ran
   rather than what happened to be committed. Built through a temporary
   index, so the caller's index, worktree and branches are untouched.

2. **Durable per-run ref** (`<run_ref_prefix>/<run_id>`). A ref is a
   reachability root, so the cited commit cannot be garbage-collected and
   survives deletion of the branch it was made on -- the dominant loss mode
   when work happens in short-lived worktrees.

3. **Tracked manifest** (caller-supplied relative path). Refs live in
   `.git/` and therefore do not travel with a normal clone or survive a
   re-rooted history. The manifest is an ordinary tracked file: reviewable,
   diffable, and recoverable from any clone. The two are complements, not
   alternatives -- the ref protects the objects, the manifest preserves the
   mapping.

Everything here is best-effort by construction. Provenance capture must
never be able to fail a run, so every function degrades to `None`/empty
rather than raising.

`provenance_paths`, `run_ref_prefix`/`wip_ref_prefix`, and `manifest_relpath`
are caller-supplied rather than hardcoded, since they're specific to the tool
using this module (bathos's own `.bth/claims`/`.bth/refs`/`refs/bathos/*`
convention, in the original design) -- nothing else in this mechanism is.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fcntl import LOCK_EX, flock
from pathlib import Path

from .capture import clean_git_env

DEFAULT_RUN_REF_PREFIX = "refs/provenance/runs"
DEFAULT_WIP_REF_PREFIX = "refs/provenance/wip"
DEFAULT_MANIFEST_RELPATH = Path(".provenance") / "refs" / "manifest.jsonl"

# commit-tree refuses to run without an identity, and a run must not fail because the
# environment has no git user configured (CI containers, cluster nodes).
_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "cisternal-provenance",
    "GIT_AUTHOR_EMAIL": "cisternal-provenance@localhost",
    "GIT_COMMITTER_NAME": "cisternal-provenance",
    "GIT_COMMITTER_EMAIL": "cisternal-provenance@localhost",
}

# Above this many bytes of newly-staged content, capture metadata instead of blobs. A
# snapshot is permanently reachable via its ref, so an unignored output directory would
# grow the repository without bound -- a worse failure than incomplete provenance.
DEFAULT_MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024

SNAPSHOT_FULL = "full"
SNAPSHOT_METADATA_ONLY = "metadata_only"
SNAPSHOT_NONE = "none"


@dataclass
class PinResult:
    """What was durably recorded for one run. Empty strings mean "not done"."""

    run_ref: str = ""
    wip_ref: str = ""
    wip_commit: str = ""
    manifest_path: str = ""
    unpinned_reason: str = ""
    ignored_provenance_paths: tuple[str, ...] = ()
    run_ref_ok: bool = False
    wip_ref_ok: bool = False
    snapshot_mode: str = SNAPSHOT_NONE
    skipped_bytes: int = 0
    skipped_paths: tuple[str, ...] = ()
    ignored_declared_paths: tuple[str, ...] = ()
    bundle_path: str = ""

    @property
    def complete(self) -> bool:
        """Whether this run's provenance is fully durable. Deliberately strict."""
        return (
            self.run_ref_ok
            and self.snapshot_mode in (SNAPSHOT_FULL, SNAPSHOT_NONE)
            and not self.ignored_declared_paths
            and not self.unpinned_reason
        )


def _git(
    *args: str, cwd: Path, env_extra: dict[str, str] | None = None, check: bool = False
) -> subprocess.CompletedProcess[str]:
    env = {**clean_git_env(), **(env_extra or {})}
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, env=env, check=check
    )


def repo_root(cwd: Path) -> Path | None:
    """Absolute worktree root, or None if `cwd` is not inside a git repository."""
    try:
        result = _git("rev-parse", "--show-toplevel", cwd=cwd)
    except (OSError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def ignored_provenance_paths(cwd: Path, provenance_paths: tuple[str, ...] = (), root: Path | None = None) -> tuple[str, ...]:
    """Which of `provenance_paths` this repo is configured to IGNORE.

    A non-empty result is a configuration bug worth surfacing loudly: it means
    a manifest or claim written there will never be committed, so the
    artifact a run's provenance points at is silently discarded.
    """
    if root is None:
        root = repo_root(cwd)
    if root is None or not provenance_paths:
        return ()
    ignored = []
    for rel in provenance_paths:
        probe = f"{rel}/.provenance-probe"
        result = _git("check-ignore", "-q", "--no-index", probe, cwd=root)
        if result.returncode == 0:
            ignored.append(rel)
    return tuple(ignored)


@dataclass
class SnapshotResult:
    """Outcome of trying to capture the working tree."""

    commit: str = ""
    mode: str = SNAPSHOT_NONE
    skipped_bytes: int = 0
    skipped_paths: tuple[str, ...] = ()


def snapshot_worktree_detailed(
    run_id: str, cwd: Path, max_bytes: int = DEFAULT_MAX_SNAPSHOT_BYTES, root: Path | None = None,
    identity_name: str = "cisternal-provenance",
    identity_email: str = "cisternal-provenance@localhost",
    commit_message_template: str = "cisternal provenance snapshot for run {run_id}",
) -> SnapshotResult:
    """Capture the working tree, degrading explicitly when it is too large to store."""
    if root is None:
        root = repo_root(cwd)
    if root is None:
        return SnapshotResult()

    head = _git("rev-parse", "HEAD", cwd=root)
    if head.returncode != 0:
        return SnapshotResult()  # unborn branch: nothing to parent a snapshot onto
    parent = head.stdout.strip()

    identity_env = {
        "GIT_AUTHOR_NAME": identity_name,
        "GIT_AUTHOR_EMAIL": identity_email,
        "GIT_COMMITTER_NAME": identity_name,
        "GIT_COMMITTER_EMAIL": identity_email,
    }

    with tempfile.TemporaryDirectory(prefix="cisternal-provenance-index-") as tmpdir:
        index_env = {"GIT_INDEX_FILE": str(Path(tmpdir) / "index")}

        if _git("read-tree", parent, cwd=root, env_extra=index_env).returncode != 0:
            return SnapshotResult()
        if _git("add", "-A", cwd=root, env_extra=index_env).returncode != 0:
            return SnapshotResult()

        total, sized = _staged_bytes(cwd, index_env)
        if total > max_bytes:
            return SnapshotResult(
                mode=SNAPSHOT_METADATA_ONLY,
                skipped_bytes=total,
                skipped_paths=tuple(rel for _size, rel in sized[:10]),
            )

        tree = _git("write-tree", cwd=root, env_extra=index_env)
        if tree.returncode != 0:
            return SnapshotResult()
        tree_sha = tree.stdout.strip()

        if tree_sha == _git("rev-parse", f"{parent}^{{tree}}", cwd=root).stdout.strip():
            return SnapshotResult()

        commit_message = commit_message_template.format(run_id=run_id)
        commit = _git(
            "commit-tree", tree_sha, "-p", parent, "-m",
            commit_message,
            cwd=root, env_extra={**index_env, **identity_env},
        )
        if commit.returncode != 0:
            return SnapshotResult()
        sha = commit.stdout.strip()
        if not sha:
            return SnapshotResult()
        return SnapshotResult(commit=sha, mode=SNAPSHOT_FULL)


def snapshot_worktree(run_id: str, cwd: Path) -> str | None:
    """Backwards-compatible wrapper: the snapshot commit sha, or None."""
    return snapshot_worktree_detailed(run_id, cwd).commit or None


def update_ref(ref: str, sha: str, cwd: Path, root: Path | None = None) -> bool:
    """Point `ref` at `sha`, then READ IT BACK. Returns whether the ref really resolves.

    Verifying rather than trusting `update-ref`'s exit code is the difference
    between recording that something is durable and knowing it is.
    """
    if root is None:
        root = repo_root(cwd)
    if root is None or not sha:
        return False
    if _git("update-ref", ref, sha, cwd=root).returncode != 0:
        return False
    verify = _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=root)
    return verify.returncode == 0 and verify.stdout.strip() == sha


def ref_resolves(ref: str, cwd: Path) -> bool:
    """Whether `ref` currently resolves to a present commit object."""
    root = repo_root(cwd)
    if root is None:
        return False
    return _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=root).returncode == 0


def _staged_bytes(cwd: Path, index_env: dict[str, str]) -> tuple[int, list[tuple[int, str]]]:
    """Total size of paths differing from HEAD in the temp index, plus the largest contributors."""
    root = repo_root(cwd)
    if root is None:
        return 0, []
    listing = _git("diff", "--cached", "--name-only", "HEAD", cwd=root, env_extra=index_env)
    if listing.returncode != 0:
        return 0, []
    sized: list[tuple[int, str]] = []
    total = 0
    for rel in listing.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        try:
            size = (root / rel).stat().st_size
        except OSError:
            continue
        total += size
        sized.append((size, rel))
    sized.sort(reverse=True)
    return total, sized


def append_manifest(entry: dict, cwd: Path, manifest_relpath: Path = DEFAULT_MANIFEST_RELPATH) -> Path | None:
    """Append one JSONL record to the tracked ref manifest, creating it if needed."""
    root = repo_root(cwd)
    if root is None:
        return None
    path = root / manifest_relpath
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.parent / ".manifest.lock"
        with lock_path.open("a", encoding="utf-8") as lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        return None
    return path


def ignored_declared_paths(paths: list[str] | tuple[str, ...], cwd: Path, root: Path | None = None) -> tuple[str, ...]:
    """Which of the caller's DECLARED load-bearing paths this repo ignores.

    `git add -A` respects `.gitignore`, so a file that matters but is ignored
    is omitted from the snapshot silently. This can only enforce that what
    WAS declared is capturable -- an undeclared input read at runtime is
    beyond what this can see.
    """
    if root is None:
        root = repo_root(cwd)
    if root is None or not paths:
        return ()
    ignored = []
    for raw in paths:
        if not raw:
            continue
        result = _git("check-ignore", "-q", "--no-index", str(raw), cwd=root)
        if result.returncode == 0:
            ignored.append(str(raw))
    return tuple(ignored)


def pin_run(
    run_id: str,
    git_hash: str,
    git_branch: str,
    dirty: bool,
    cwd: Path,
    declared_paths: list[str] | tuple[str, ...] = (),
    max_snapshot_bytes: int = DEFAULT_MAX_SNAPSHOT_BYTES,
    export_dir: Path | None = None,
    provenance_paths: tuple[str, ...] = (),
    run_ref_prefix: str = DEFAULT_RUN_REF_PREFIX,
    wip_ref_prefix: str = DEFAULT_WIP_REF_PREFIX,
    manifest_relpath: Path = DEFAULT_MANIFEST_RELPATH,
    identity_name: str = "cisternal-provenance",
    identity_email: str = "cisternal-provenance@localhost",
    commit_message_template: str = "cisternal provenance snapshot for run {run_id}",
) -> PinResult:
    """Durably record one run's provenance. Never raises; degrades to a partial result.

    On a dirty tree the run ref points at the SNAPSHOT rather than at HEAD,
    because the snapshot is the tree that actually ran. `git_hash` is still
    recorded in the manifest so the relationship to the committed history
    stays visible.

    Bundle export (for a dirty run whose object store won't be read from
    directly, e.g. a remote/scheduled worker) fires whenever `export_dir` is
    given -- deciding WHETHER that's the case (bathos's original used
    `SLURM_JOB_ID`/`BTH_FORCE_PROVENANCE_EXPORT`) is the caller's job, not
    this module's: it would otherwise have to hardcode one tool's env var
    names, or guess a default export directory name that only made sense for
    one tool's layout.
    """
    computed_root = repo_root(cwd)
    result = PinResult(
        ignored_provenance_paths=ignored_provenance_paths(cwd, provenance_paths, root=computed_root),
        ignored_declared_paths=ignored_declared_paths(declared_paths, cwd, root=computed_root),
    )

    if computed_root is None:
        result.unpinned_reason = "not a git repository"
        return result
    if not git_hash or git_hash == "unknown":
        result.unpinned_reason = "no resolvable HEAD to pin"
        return result

    pinned_sha = git_hash
    if dirty:
        snap = snapshot_worktree_detailed(
            run_id, cwd, max_bytes=max_snapshot_bytes, root=computed_root,
            identity_name=identity_name, identity_email=identity_email,
            commit_message_template=commit_message_template,
        )
        result.snapshot_mode = snap.mode
        result.skipped_bytes = snap.skipped_bytes
        result.skipped_paths = snap.skipped_paths
        if snap.commit:
            result.wip_commit = snap.commit
            wip_ref = f"{wip_ref_prefix}/{run_id}"
            if update_ref(wip_ref, snap.commit, cwd, root=computed_root):
                result.wip_ref = wip_ref
                result.wip_ref_ok = True
            else:
                result.unpinned_reason = "could not create wip ref"
            pinned_sha = snap.commit
        elif snap.mode == SNAPSHOT_METADATA_ONLY:
            result.unpinned_reason = (
                f"working tree too large to snapshot ({snap.skipped_bytes:,} bytes)"
            )

    run_ref = f"{run_ref_prefix}/{run_id}"
    if update_ref(run_ref, pinned_sha, cwd, root=computed_root):
        result.run_ref = run_ref
        result.run_ref_ok = True
    else:
        result.unpinned_reason = result.unpinned_reason or "could not create run ref"

    entry = {
        "run_id": run_id,
        "head_sha": git_hash,
        "pinned_sha": pinned_sha,
        "branch": git_branch,
        "dirty": bool(dirty),
        "wip_commit": result.wip_commit,
        "run_ref_ok": result.run_ref_ok,
        "wip_ref_ok": result.wip_ref_ok,
        "snapshot_mode": result.snapshot_mode,
        "skipped_bytes": result.skipped_bytes,
        "skipped_paths": list(result.skipped_paths),
        "ignored_declared_paths": list(result.ignored_declared_paths),
        "unpinned_reason": result.unpinned_reason,
        "complete": result.complete,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    manifest = append_manifest(entry, cwd, manifest_relpath)
    if manifest is not None:
        result.manifest_path = str(manifest)

    if (
        export_dir is not None
        and result.snapshot_mode == SNAPSHOT_FULL
        and pinned_sha != git_hash
    ):
        bundle = export_bundle(run_id, pinned_sha, git_hash, cwd, export_dir=export_dir, run_ref_prefix=run_ref_prefix, wip_ref_prefix=wip_ref_prefix)
        if bundle is not None:
            result.bundle_path = str(bundle)
            with suppress(OSError):
                bundle.with_suffix(".json").write_text(
                    json.dumps(entry, sort_keys=True), encoding="utf-8"
                )

    return result


def manifest_candidates(cwd: Path, manifest_relpath: Path = DEFAULT_MANIFEST_RELPATH) -> list[Path]:
    """Every manifest that could describe a run in THIS repository.

    Refs are shared across linked worktrees but the manifest is an ordinary
    file in one checkout, so lookups consult the current worktree AND the
    main one (and every other linked worktree).
    """
    root = repo_root(cwd)
    if root is None:
        return []
    candidates = [root]

    listing = _git("worktree", "list", "--porcelain", cwd=root)
    if listing.returncode == 0:
        for line in listing.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            other = Path(line[len("worktree ") :].strip())
            if other != root and other not in candidates:
                candidates.append(other)

    return [c / manifest_relpath for c in candidates]


def manifest_entry(run_id: str, cwd: Path, manifest_relpath: Path = DEFAULT_MANIFEST_RELPATH) -> dict | None:
    """The most recent manifest record for `run_id`, from any manifest in this repository."""
    found = None
    for path in manifest_candidates(cwd, manifest_relpath):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("run_id") == run_id:
                    found = entry
        except OSError:
            continue
    return found


def uncommitted_diff_for_run(
    run_id: str, cwd: Path, name_only: bool = False,
    wip_ref_prefix: str = DEFAULT_WIP_REF_PREFIX, manifest_relpath: Path = DEFAULT_MANIFEST_RELPATH,
) -> str | None:
    """The uncommitted changes that were live when `run_id` executed.

    Returns "" when the run was clean, None when it cannot be reconstructed.
    Prefers the ref, falls back to the manifest's recorded sha.
    """
    root = repo_root(cwd)
    if root is None:
        return None

    entry = manifest_entry(run_id, cwd, manifest_relpath)
    wip_ref = f"{wip_ref_prefix}/{run_id}"
    have_ref = _git("rev-parse", "--verify", "--quiet", wip_ref, cwd=root).returncode == 0

    if have_ref:
        wip_sha = _git("rev-parse", wip_ref, cwd=root).stdout.strip()
    elif entry and entry.get("wip_commit"):
        wip_sha = str(entry["wip_commit"])
    else:
        if entry is not None and not entry.get("dirty"):
            return ""
        return None

    head_sha = str(entry["head_sha"]) if entry and entry.get("head_sha") else f"{wip_sha}^"
    args = ["diff", head_sha, wip_sha]
    if name_only:
        args.insert(1, "--name-only")
    result = _git(*args, cwd=root)
    if result.returncode != 0:
        return None
    return result.stdout


def pin_result_as_dict(result: PinResult) -> dict:
    """Flat dict for telemetry, with tuples rendered as lists."""
    payload = asdict(result)
    payload["ignored_provenance_paths"] = list(result.ignored_provenance_paths)
    return payload


# ---------------------------------------------------------------------------
# Cross-clone transport: a ref protects objects inside ONE object store. A run
# executed on a remote/scheduled worker pins into that machine's `.git`, which
# is not the one results get read from -- so provenance for a dirty remote
# run has to travel as a bundle file through whatever channel already moves
# results back.
# ---------------------------------------------------------------------------


@dataclass
class ImportReport:
    """Outcome of importing bundled provenance from another machine."""

    imported: tuple[str, ...] = ()
    already_present: tuple[str, ...] = ()
    unusable: tuple[tuple[str, str], ...] = ()  # (run_id, reason)


def export_bundle(
    run_id: str,
    pinned_sha: str,
    head_sha: str,
    cwd: Path,
    export_dir: Path,
    run_ref_prefix: str = DEFAULT_RUN_REF_PREFIX,
    wip_ref_prefix: str = DEFAULT_WIP_REF_PREFIX,
) -> Path | None:
    """Write a bundle carrying one run's snapshot to another clone.

    The bundle is a DELTA against `head_sha` (`--not`), which keeps it to the
    changed files rather than the whole history.
    """
    root = repo_root(cwd)
    if root is None or not pinned_sha or pinned_sha == head_sha:
        return None

    target_dir = export_dir
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    run_ref = f"{run_ref_prefix}/{run_id}"
    if _git("rev-parse", "--verify", "--quiet", run_ref, cwd=root).stdout.strip() != pinned_sha:
        return None

    refs = [run_ref]
    wip_ref = f"{wip_ref_prefix}/{run_id}"
    if _git("rev-parse", "--verify", "--quiet", wip_ref, cwd=root).returncode == 0:
        refs.append(wip_ref)

    bundle_path = target_dir / f"{run_id}.bundle"
    result = _git("bundle", "create", str(bundle_path), *refs, "--not", head_sha, cwd=root)
    if result.returncode != 0 or not bundle_path.exists():
        return None
    return bundle_path


def _ensure_refs_and_manifest(
    run_id: str, entry: dict, cwd: Path, root: Path,
    run_ref_prefix: str, wip_ref_prefix: str, manifest_relpath: Path,
) -> None:
    """Create this clone's refs for an imported run, and record it in the local manifest."""
    pinned = str(entry.get("pinned_sha", ""))
    if pinned and _git("cat-file", "-e", f"{pinned}^{{commit}}", cwd=root).returncode == 0:
        update_ref(f"{run_ref_prefix}/{run_id}", pinned, cwd)
        wip = str(entry.get("wip_commit", ""))
        if wip:
            update_ref(f"{wip_ref_prefix}/{run_id}", wip, cwd)

    if entry and manifest_entry(run_id, cwd, manifest_relpath) is None:
        append_manifest({**entry, "imported_from_bundle": True}, cwd, manifest_relpath)


def import_bundles(
    cwd: Path, import_dir: Path,
    run_ref_prefix: str = DEFAULT_RUN_REF_PREFIX,
    wip_ref_prefix: str = DEFAULT_WIP_REF_PREFIX,
    manifest_relpath: Path = DEFAULT_MANIFEST_RELPATH,
) -> ImportReport:
    """Import provenance bundles produced on another machine.

    Refuses to import a bundle whose prerequisites are absent, rather than
    creating a ref pointing at an object this clone does not have.
    """
    root = repo_root(cwd)
    if root is None:
        return ImportReport()

    source_dir = import_dir
    if not source_dir.is_dir():
        return ImportReport()

    imported: list[str] = []
    already: list[str] = []
    unusable: list[tuple[str, str]] = []

    for bundle_path in sorted(source_dir.glob("*.bundle")):
        run_id = bundle_path.stem
        sidecar = bundle_path.with_suffix(".json")
        entry: dict = {}
        if sidecar.exists():
            try:
                entry = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                entry = {}

        pinned = str(entry.get("pinned_sha", ""))
        if pinned and _git("cat-file", "-e", f"{pinned}^{{commit}}", cwd=root).returncode == 0:
            already.append(run_id)
            _ensure_refs_and_manifest(run_id, entry, cwd, root, run_ref_prefix, wip_ref_prefix, manifest_relpath)
            continue

        if _git("bundle", "verify", str(bundle_path), cwd=root).returncode != 0:
            unusable.append((run_id, "bundle prerequisites missing -- fetch the base commit first"))
            continue

        if _git("bundle", "unbundle", str(bundle_path), cwd=root).returncode != 0:
            unusable.append((run_id, "unbundle failed"))
            continue

        _ensure_refs_and_manifest(run_id, entry, cwd, root, run_ref_prefix, wip_ref_prefix, manifest_relpath)
        imported.append(run_id)

    return ImportReport(
        imported=tuple(imported), already_present=tuple(already), unusable=tuple(unusable)
    )
