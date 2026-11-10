"""Actor isolation verification helper (spec §3.4).

Provides prove_isolation to audit candidate features before promotion:
- Executes baseline live run vs shadow run.
- Verifies return value equivalence and byte-identical filesystem deltas in live_roots.
- Detects unauthorized side-effect leaks outside shadow_log_dir.
- Emits shadow.isolation telemetry events.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cisternal.shadow.events import emit_isolation
from cisternal.shadow.resolution import find_repo_root


@dataclass(frozen=True)
class EntryInfo:
    """Detailed metadata for a filesystem entry (spec §3.4, REV2-02, REV2-04)."""

    kind: str  # "file", "dir", "symlink", "broken_symlink", "unreadable"
    size: int
    mode: int
    digest: str  # sha256 or "dir" or "target:<path>" or "unreadable:<error>"
    mtime_ns: int

    def content_equals(self, other: EntryInfo | None) -> bool:
        """Check content equivalence excluding mtime_ns."""
        if other is None:
            return False
        return (
            self.kind == other.kind
            and self.size == other.size
            and self.mode == other.mode
            and self.digest == other.digest
        )


@dataclass(frozen=True)
class IsolationResult:
    """Report payload from prove_isolation verification audit."""

    passed: bool
    live_output_identical: bool
    leaked_paths: list[Path]
    actor_output: Any
    shadow_output: Any


IGNORED_DIR_NAMES = {".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__"}


def _normalize_entry_path(p: Path) -> Path:
    """Normalize path, preserving symlink identity without resolving to target."""
    try:
        if p.is_symlink():
            return p.parent.resolve() / p.name
        return p.resolve()
    except OSError:
        return p.absolute()


def _inspect_entry(p: Path) -> EntryInfo:
    """Inspect a filesystem entry, capturing type, size, mode, sha256, and mtime."""
    try:
        st = p.lstat()
    except OSError as exc:
        return EntryInfo("unreadable", 0, 0, f"unreadable:{type(exc).__name__}", 0)

    mode = st.st_mode
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    size = st.st_size

    if p.is_symlink():
        try:
            target = os.readlink(p)
            is_broken = not p.exists()
            kind = "broken_symlink" if is_broken else "symlink"
            return EntryInfo(kind, size, mode, f"target:{target}", mtime_ns)
        except OSError as exc:
            return EntryInfo("symlink", size, mode, f"unreadable_link:{type(exc).__name__}", mtime_ns)

    if p.is_dir():
        return EntryInfo("dir", size, mode, "dir", mtime_ns)

    try:
        content = p.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        return EntryInfo("file", len(content), mode, digest, mtime_ns)
    except OSError as exc:
        return EntryInfo("file", size, mode, f"unreadable:{type(exc).__name__}", mtime_ns)


def _snapshot(roots: list[Path]) -> dict[Path, EntryInfo]:
    """Walk directories and snapshot paths, entries, modes, and digests."""
    snap: dict[Path, EntryInfo] = {}
    for root in roots:
        r = Path(root).resolve()
        if not r.exists() and not r.is_symlink():
            continue

        norm_r = _normalize_entry_path(r)
        snap[norm_r] = _inspect_entry(r)

        if r.is_dir() and not r.is_symlink():
            for dirpath, dirnames, filenames in os.walk(r, followlinks=False):
                dirnames[:] = [d for d in dirnames if d not in IGNORED_DIR_NAMES]
                for d in dirnames:
                    dp = Path(dirpath) / d
                    snap[_normalize_entry_path(dp)] = _inspect_entry(dp)
                for f in filenames:
                    fp = Path(dirpath) / f
                    snap[_normalize_entry_path(fp)] = _inspect_entry(fp)
    return snap


def _compute_delta(
    pre_snap: dict[Path, EntryInfo],
    post_snap: dict[Path, EntryInfo],
    *,
    track_mtime: bool = False,
) -> dict[Path, tuple[str, EntryInfo | None, EntryInfo | None]]:
    """Compute difference between pre-run and post-run filesystem snapshots."""
    delta: dict[Path, tuple[str, EntryInfo | None, EntryInfo | None]] = {}
    all_paths = set(pre_snap.keys()) | set(post_snap.keys())
    for p in sorted(all_paths):
        pre_entry = pre_snap.get(p)
        post_entry = post_snap.get(p)
        if pre_entry is None and post_entry is not None:
            delta[p] = ("created", None, post_entry)
        elif pre_entry is not None and post_entry is None:
            delta[p] = ("deleted", pre_entry, None)
        elif pre_entry is not None and post_entry is not None:
            is_mod = (pre_entry != post_entry) if track_mtime else (not pre_entry.content_equals(post_entry))
            if is_mod:
                delta[p] = ("modified", pre_entry, post_entry)
    return delta


def _delta_action_matches(
    a1: tuple[str, EntryInfo | None, EntryInfo | None],
    a2: tuple[str, EntryInfo | None, EntryInfo | None] | None,
) -> bool:
    """Check if two delta action tuples represent equivalent content mutations."""
    if a2 is None:
        return False
    action1, pre1, post1 = a1
    action2, pre2, post2 = a2
    if action1 != action2:
        return False
    if (pre1 is None) != (pre2 is None):
        return False
    if pre1 is not None and pre2 is not None and not pre1.content_equals(pre2):
        return False
    if (post1 is None) != (post2 is None):
        return False
    if post1 is not None and post2 is not None and not post1.content_equals(post2):
        return False
    return True


def _deltas_content_match(
    d1: dict[Path, tuple[str, EntryInfo | None, EntryInfo | None]],
    d2: dict[Path, tuple[str, EntryInfo | None, EntryInfo | None]],
) -> bool:
    """Check if two filesystem deltas are content-identical across all paths."""
    if set(d1.keys()) != set(d2.keys()):
        return False
    for k in d1:
        if not _delta_action_matches(d1[k], d2.get(k)):
            return False
    return True


logger = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.json"
_OWNER_RWX = stat.S_IRWXU


class IsolationRestoreError(RuntimeError):
    """A live root could not be restored. The backup is kept on disk at ``backup_path``."""

    def __init__(self, reason: str, backup_path: Path) -> None:
        super().__init__(f"{reason}; original contents are preserved in backup at {backup_path}")
        self.backup_path = backup_path


@contextmanager
def _temp_mode(p: Path, bits: int) -> Iterator[None]:
    """Temporarily add owner permission bits to p; the original mode is restored on exit."""
    st = os.lstat(p)
    original = stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode) or (original & bits) == bits:
        yield
        return
    os.chmod(p, original | bits)
    try:
        yield
    finally:
        os.chmod(p, original)


def _copy_meta(st: os.stat_result, dst: Path) -> None:
    """Apply mode and timestamps from st to dst (dst must not be a symlink)."""
    os.chmod(dst, stat.S_IMODE(st.st_mode))
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_bytes(a: Path, b: Path) -> bool:
    """Content equality; an unreadable operand counts as different so it gets rewritten."""
    try:
        with _temp_mode(a, stat.S_IRUSR), _temp_mode(b, stat.S_IRUSR):
            return _digest(a) == _digest(b)
    except OSError:
        return False


def _is_protected(rel: Path, protected: list[Path]) -> bool:
    """True if rel is an entry that backup could not read, or lies beneath one."""
    return any(rel == s or s in rel.parents for s in protected)


def _has_protected_below(rel: Path, protected: list[Path]) -> bool:
    return any(rel in s.parents for s in protected)


def _remove_path(p: Path) -> None:
    """Delete p, including read-only directories. Never follows symlinks."""
    st = os.lstat(p)
    if stat.S_ISDIR(st.st_mode):
        os.chmod(p, stat.S_IMODE(st.st_mode) | _OWNER_RWX)
        for name in os.listdir(p):
            _remove_path(p / name)
        os.rmdir(p)
    else:
        os.unlink(p)


def _mirror_entry(src: Path, dst: Path, rel: Path, skipped: list[Path]) -> None:
    """Copy src to dst keeping symlinks, modes and mtimes.

    Entries that cannot be read are recorded in ``skipped`` (relative to the root) and are
    never touched by the restore.
    """
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(src), dst)
        return
    if stat.S_ISDIR(st.st_mode):
        dst.mkdir()
        # Children are visited while src is still readable and searchable (lstat needs +x).
        with ExitStack() as stack:
            try:
                stack.enter_context(_temp_mode(src, stat.S_IRUSR | stat.S_IXUSR))
                names = sorted(os.listdir(src))
            except OSError:
                skipped.append(rel)
                names = []
            for name in names:
                _mirror_entry(src / name, dst / name, rel / name, skipped)
        _copy_meta(st, dst)
        return
    if not stat.S_ISREG(st.st_mode):
        skipped.append(rel)  # fifos, sockets, devices are never read
        return
    try:
        with _temp_mode(src, stat.S_IRUSR):
            shutil.copyfile(src, dst)
    except OSError:
        dst.unlink(missing_ok=True)
        skipped.append(rel)
        return
    _copy_meta(st, dst)


def _backup_roots(roots: list[Path], backup_dir: Path) -> None:
    """Mirror each existing live root into backup_dir and write a manifest last.

    The manifest records whether each root existed and which entries were skipped; restore
    refuses to run without it.
    """
    entries: list[dict[str, Any]] = []
    for idx, r in enumerate(roots):
        r_res = Path(r).resolve()
        existed = os.path.lexists(r_res)
        skipped: list[Path] = []
        if existed:
            _mirror_entry(r_res, backup_dir / f"root_{idx}", Path("."), skipped)
        entries.append(
            {
                "index": idx,
                "path": str(r_res),
                "existed": existed,
                "skipped": [p.as_posix() for p in skipped],
            }
        )
    (backup_dir / _MANIFEST_NAME).write_text(
        json.dumps({"roots": entries}, indent=2), encoding="utf-8"
    )


def _read_manifest(backup_dir: Path, n_roots: int) -> list[dict[str, Any]]:
    try:
        entries = json.loads((backup_dir / _MANIFEST_NAME).read_text(encoding="utf-8"))["roots"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise IsolationRestoreError(
            f"backup manifest unreadable ({type(exc).__name__})", backup_dir
        ) from exc
    if len(entries) != n_roots:
        raise IsolationRestoreError("backup manifest does not match live roots", backup_dir)
    return entries


def _materialize(bak: Path, live: Path, rel: Path, protected: list[Path]) -> None:
    """Create live (which does not exist) as a copy of bak."""
    bst = os.lstat(bak)
    if stat.S_ISLNK(bst.st_mode):
        os.symlink(os.readlink(bak), live)
        return
    if stat.S_ISDIR(bst.st_mode):
        live.mkdir()
        with _temp_mode(bak, stat.S_IRUSR | stat.S_IXUSR):
            for name in sorted(os.listdir(bak)):
                _sync_entry(live / name, bak / name, rel / name, protected)
        _copy_meta(bst, live)
        return
    with _temp_mode(bak, stat.S_IRUSR):
        shutil.copyfile(bak, live)
    _copy_meta(bst, live)


def _replace(live: Path, bak: Path, rel: Path, protected: list[Path]) -> None:
    if _has_protected_below(rel, protected):
        raise OSError(f"cannot replace {live}: unreadable entries lie beneath it")
    _remove_path(live)
    _materialize(bak, live, rel, protected)


def _sync_dir(live: Path, bak: Path, rel: Path, protected: list[Path], bst: os.stat_result) -> None:
    lst = os.lstat(live)
    os.chmod(live, stat.S_IMODE(lst.st_mode) | _OWNER_RWX)
    # bak must stay searchable while its children are compared (lstat needs +x).
    with _temp_mode(bak, stat.S_IRUSR | stat.S_IXUSR):
        bak_names = sorted(os.listdir(bak))
        bak_set = set(bak_names)
        for name in os.listdir(live):
            if name in bak_set or _is_protected(rel / name, protected):
                continue
            _remove_path(live / name)
        for name in bak_names:
            _sync_entry(live / name, bak / name, rel / name, protected)
    _copy_meta(bst, live)


def _sync_entry(live: Path, bak: Path, rel: Path, protected: list[Path]) -> None:
    """Make live match bak for one entry, touching only what differs.

    Entries that backup could not read are never modified or deleted.
    """
    if _is_protected(rel, protected):
        if not os.path.lexists(live):
            logger.warning("cannot restore unreadable entry %s (not backed up)", live)
        return
    if not os.path.lexists(live):
        _materialize(bak, live, rel, protected)
        return
    bst = os.lstat(bak)
    lst = os.lstat(live)
    if stat.S_IFMT(lst.st_mode) != stat.S_IFMT(bst.st_mode):
        _replace(live, bak, rel, protected)
        return
    if stat.S_ISLNK(bst.st_mode):
        if os.readlink(live) != os.readlink(bak):
            _replace(live, bak, rel, protected)
        return
    if stat.S_ISDIR(bst.st_mode):
        _sync_dir(live, bak, rel, protected, bst)
        return
    if not _same_bytes(live, bak):
        with _temp_mode(bak, stat.S_IRUSR), _temp_mode(live, stat.S_IWUSR):
            shutil.copyfile(bak, live)
    _copy_meta(bst, live)


def _restore_roots(roots: list[Path], backup_dir: Path) -> None:
    """Restore each live root in place from backup_dir.

    Nothing is deleted wholesale: extra entries created by the run are removed, differing
    entries are rewritten, and the backup stays on disk until the caller discards it.
    """
    entries = _read_manifest(backup_dir, len(roots))
    try:
        for idx, r in enumerate(roots):
            entry = entries[idx]
            r_res = Path(r).resolve()
            if not entry["existed"]:
                if os.path.lexists(r_res):
                    _remove_path(r_res)
                continue
            protected = [Path(s) for s in entry["skipped"]]
            _sync_entry(r_res, backup_dir / f"root_{idx}", Path("."), protected)
    except OSError as exc:
        raise IsolationRestoreError(f"restore of live root failed ({exc})", backup_dir) from exc


def _restore_after_failure(roots: list[Path], backup_dir: Path) -> IsolationRestoreError | None:
    try:
        _restore_roots(roots, backup_dir)
    except IsolationRestoreError as exc:
        logger.error("prove_isolation aborted and live restore failed: %s", exc)
        return exc
    return None


def _discard_backup(backup_dir: Path) -> None:
    try:
        _remove_path(backup_dir)
    except OSError as exc:
        logger.warning("could not delete isolation backup %s: %s", backup_dir, exc)


def prove_isolation(
    actor_live_fn: Callable[[], Any],
    actor_shadow_fn: Callable[[], Any],
    *,
    live_roots: list[Path],
    shadow_log_dir: Path,
    quiescence_wait_s: float = 0.0,
    check_roots: list[Path] | None = None,
    feature: str = "",
    enforced_by: str = "",
) -> IsolationResult:
    """Verify that candidate shadow arm preserves actor outputs and confines side-effects.

    Args:
        actor_live_fn: Callable executing baseline live logic.
        actor_shadow_fn: Callable executing candidate shadow logic.
        live_roots: Directories legitimate actor logic writes to.
        shadow_log_dir: Directory where shadow logs are permitted.
        quiescence_wait_s: Grace period in seconds to wait for background flushes.
        check_roots: Optional explicit directories to monitor for unauthorized write leaks.
        feature: Optional feature slug; if non-empty, emits shadow.isolation event.
        enforced_by: Test symbol identifier for telemetry audit trail.

    Returns:
        IsolationResult with passed, live_output_identical, and leaked_paths.
    """
    resolved_live_roots = [Path(r).resolve() for r in live_roots]
    resolved_shadow_log_dir = Path(shadow_log_dir).resolve()
    resolved_shadow_log_dir.mkdir(parents=True, exist_ok=True)

    # Determine directories to watch for leaks
    watched_dirs: set[Path] = set(resolved_live_roots)
    watched_dirs.add(resolved_shadow_log_dir)
    if check_roots:
        for cr in check_roots:
            watched_dirs.add(Path(cr).resolve())
    else:
        # Default watch set includes parents of roots, cwd, and repo root
        for r in resolved_live_roots:
            watched_dirs.add(r.parent)
        watched_dirs.add(resolved_shadow_log_dir.parent)
        watched_dirs.add(Path.cwd().resolve())
        repo = find_repo_root()
        if repo is not None:
            watched_dirs.add(repo.resolve())

    # The backup is kept on disk unless every step succeeds, so a failed restore never
    # leaves a live root destroyed with no copy of its contents.
    backup_path = Path(tempfile.mkdtemp(prefix="cisternal_isolation_backup_"))
    try:
        # Backup live_roots before baseline live run
        _backup_roots(resolved_live_roots, backup_path)
        pre_live_snap = _snapshot(resolved_live_roots)

        # Phase 1: Baseline live run
        actor_output = actor_live_fn()
        post_live_snap = _snapshot(resolved_live_roots)
        live_delta = _compute_delta(pre_live_snap, post_live_snap)

        # Reset live_roots to pre-run state
        _restore_roots(resolved_live_roots, backup_path)

        # Phase 2: Shadow run
        pre_shadow_watched = _snapshot(list(watched_dirs))
        shadow_output = actor_shadow_fn()

        if quiescence_wait_s > 0.0:
            time.sleep(quiescence_wait_s)

        post_shadow_live = _snapshot(resolved_live_roots)
        shadow_delta = _compute_delta(pre_live_snap, post_shadow_live)
        post_shadow_watched = _snapshot(list(watched_dirs))
        watched_delta = _compute_delta(pre_shadow_watched, post_shadow_watched, track_mtime=True)
    except BaseException as exc:
        restore_exc = _restore_after_failure(resolved_live_roots, backup_path)
        if restore_exc is not None:
            exc.add_note(str(restore_exc))
        raise

    # Shadow-phase writes must not persist in the audited live roots.
    _restore_roots(resolved_live_roots, backup_path)
    _discard_backup(backup_path)

    # Verification & Audit
    return_identical = (actor_output == shadow_output)
    fs_identical = _deltas_content_match(live_delta, shadow_delta)
    live_output_identical = return_identical and fs_identical

    # Leak detection
    leaked_paths: list[Path] = []
    for path in sorted(watched_delta.keys()):
        # Is it in shadow_log_dir?
        try:
            if path.is_relative_to(resolved_shadow_log_dir):
                continue
        except AttributeError:
            if str(path).startswith(str(resolved_shadow_log_dir)):
                continue

        # Is it inside one of live_roots?
        if path in resolved_live_roots:
            # The root directory container itself is not a leaked file
            continue

        in_live = False
        for lr in resolved_live_roots:
            try:
                if path.is_relative_to(lr):
                    in_live = True
                    break
            except AttributeError:
                if str(path).startswith(str(lr)):
                    in_live = True
                    break

        if in_live:
            # Inside live_root: permitted ONLY if part of identical live delta
            if path in live_delta and _delta_action_matches(live_delta[path], shadow_delta.get(path)):
                continue
            leaked_paths.append(path)
        else:
            # Outside live_roots and outside shadow_log_dir: unauthorized leak!
            leaked_paths.append(path)

    passed = live_output_identical and (len(leaked_paths) == 0)

    # Optional telemetry emission
    if feature:
        emit_isolation(
            feature=feature,
            writes_isolated=passed,
            leaked_paths=[str(p) for p in leaked_paths],
            enforced_by=enforced_by or "cisternal.shadow.isolation::prove_isolation",
        )

    return IsolationResult(
        passed=passed,
        live_output_identical=live_output_identical,
        leaked_paths=leaked_paths,
        actor_output=actor_output,
        shadow_output=shadow_output,
    )
