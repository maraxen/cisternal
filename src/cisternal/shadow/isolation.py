"""Actor isolation verification helper (spec §3.4).

Provides prove_isolation to audit candidate features before promotion:
- Executes baseline live run vs shadow run.
- Verifies return value equivalence and byte-identical filesystem deltas in live_roots.
- Detects unauthorized side-effect leaks outside shadow_log_dir.
- Emits shadow.isolation telemetry events.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
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


def _backup_roots(roots: list[Path], backup_dir: Path) -> None:
    """Backup all existing files under roots into backup_dir."""
    for idx, r in enumerate(roots):
        r_res = r.resolve()
        if r_res.exists():
            dest = backup_dir / f"root_{idx}"
            if r_res.is_dir():
                shutil.copytree(r_res, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(r_res, dest)


def _restore_roots(roots: list[Path], backup_dir: Path) -> None:
    """Restore roots to their exact state stored in backup_dir."""
    for idx, r in enumerate(roots):
        r_res = r.resolve()
        # Clean current state
        if r_res.exists():
            if r_res.is_dir():
                shutil.rmtree(r_res)
            else:
                r_res.unlink()
        # Restore backup if it existed
        src = backup_dir / f"root_{idx}"
        if src.exists():
            if src.is_dir():
                shutil.copytree(src, r_res)
            else:
                r_res.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, r_res)


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

    with tempfile.TemporaryDirectory(prefix="cisternal_isolation_backup_") as temp_backup:
        backup_path = Path(temp_backup)

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
