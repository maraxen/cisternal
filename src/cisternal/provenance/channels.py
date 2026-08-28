"""Multi-channel git-state capture: prefer a real repo, else env vars, else a sidecar file.

Ported from `bathos/git.py` (design: `260820_bathos-git-provenance-sidecar-spec.md`,
decision D6). This is the READER half of the myxcel<->bathos provenance
protocol -- myxcel (via `capture.py`/`record.py` in this same package) is the
WRITER. Moving both halves into one shared module is what actually closes the
schema-drift risk the original spec's pre-mortem worried about: before this
move, bathos independently re-implemented a reader for the exact schema
myxcel's writer produces, with no shared code enforcing the two agree.

`capture_git_state()` never raises (C6 of the spec): every caller-visible
failure degrades to the `_UNKNOWN` sentinel, because a provenance-capture
failure must never fail the run it's attached to.
"""

from __future__ import annotations

import json
import os
import subprocess
import warnings as _warnings
from dataclasses import dataclass
from pathlib import Path

from .capture import compute_dirty_content_id
from .record import PROVENANCE_FILENAME, _VALID_PROVENANCE_STATUSES


@dataclass
class GitState:
    hash: str
    branch: str
    dirty: bool
    dirty_content_id: str | None = None
    provenance_source: str = "git"  # "git" | "myxcel-env" | "myxcel-sidecar" | "none"


_UNKNOWN = GitState(hash="unknown", branch="unknown", dirty=False, provenance_source="none")


def _env_channel(cwd: str | Path) -> dict | None:
    """Read provenance from MYXCEL_PROVENANCE_SCHEMA env vars.

    Returns None if the schema var is absent. Empty string always means
    null/None. Ignored if cwd is not inside MYXCEL_PROVENANCE_ROOT (D5 guard).
    """
    if "MYXCEL_PROVENANCE_SCHEMA" not in os.environ:
        return None

    root_str = os.environ.get("MYXCEL_PROVENANCE_ROOT", "")
    if not root_str:
        return None
    try:
        cwd_path = Path(cwd).resolve()
        root_path = Path(root_str).resolve()
        if not cwd_path.is_relative_to(root_path):
            return None
    except (ValueError, OSError):
        return None

    status = os.environ.get("MYXCEL_PROVENANCE_STATUS", "")
    if status not in _VALID_PROVENANCE_STATUSES:
        return None

    return {
        "provenance_status": status,
        "git_sha": os.environ.get("MYXCEL_GIT_SHA", "") or None,
        "git_branch": os.environ.get("MYXCEL_GIT_BRANCH", "") or None,
        "git_dirty": os.environ.get("MYXCEL_GIT_DIRTY", ""),
        "dirty_content_id": os.environ.get("MYXCEL_GIT_DIRTY_CONTENT_ID", "") or None,
        "root": root_str or None,
    }


def _sidecar_channel(cwd: str | Path) -> dict | None:
    """Ascend from cwd up to 8 levels looking for .myxcel_provenance.json or .git.

    Stops at the first .git (file or directory) or PROVENANCE_FILENAME.
    Returns parsed sidecar record or None if not found.
    """
    cwd_path = Path(cwd).resolve()
    current = cwd_path

    for _ in range(8):
        git_path = current / ".git"
        if git_path.exists():
            return None

        sidecar_path = current / PROVENANCE_FILENAME
        if sidecar_path.exists():
            try:
                data = json.loads(sidecar_path.read_text())
                if (
                    "provenance_status" not in data
                    or data.get("provenance_status") not in _VALID_PROVENANCE_STATUSES
                    or "schema_version" not in data
                    or not isinstance(data.get("schema_version"), int)
                ):
                    return None
                if data.get("schema_version", 0) > 1:
                    _warnings.warn(
                        f"myxcel provenance sidecar at {sidecar_path} has schema_version="
                        f"{data.get('schema_version')}, newer than this reader understands "
                        f"(max known: 1) -- reading only the fields this version knows about.",
                        stacklevel=2,
                    )
                return {
                    "provenance_status": data.get("provenance_status"),
                    "git_sha": data.get("git_sha"),
                    "git_branch": data.get("git_branch"),
                    "git_dirty": data.get("git_dirty"),
                    "dirty_content_id": data.get("dirty_content_id"),
                    "root": data.get("provenance_root"),
                }
            except (json.JSONDecodeError, OSError):
                return None

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def _same_root(a: str | Path, b: str | Path) -> bool:
    """True iff a and b denote the same directory. Never raises."""
    try:
        if Path(a).samefile(b):
            return True
    except (OSError, ValueError):
        pass
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except (OSError, ValueError):
        return False


def _legacy_git_shellout(cwd: str | Path) -> GitState | None:
    """Plain git shellout, no channels. Returns None on any failure."""
    try:
        hash_ = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
        return GitState(hash=hash_, branch=branch, dirty=dirty, provenance_source="git")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_shellout_with_toplevel(cwd: str | Path) -> tuple[str, str, bool, str] | None:
    """Git shellout returning (hash, branch, dirty, toplevel) or None on failure."""
    try:
        hash_ = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
        toplevel = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        return (hash_, branch, dirty, toplevel)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def capture_git_state(cwd: Path | None = None) -> GitState:
    """Capture git provenance from multiple channels with defined precedence.

    D6 precedence:
    1. Check env and sidecar channels; if neither present, use legacy git or _UNKNOWN
    2. If a channel exists and a real repo exists at the same root, use the real repo
    3. Otherwise use the channel

    Never raises (C6).
    """
    try:
        cwd = cwd if cwd is not None else Path.cwd()
        cwd_str = str(cwd)

        env_prov = _env_channel(cwd_str)
        if env_prov is not None:
            prov = env_prov
            prov_source = "myxcel-env"
        else:
            prov = _sidecar_channel(cwd_str)
            prov_source = "myxcel-sidecar"

        if prov is None:
            result = _legacy_git_shellout(cwd_str)
            return result if result is not None else _UNKNOWN

        git_info = _git_shellout_with_toplevel(cwd_str)
        if git_info is not None:
            hash_, branch, dirty, toplevel = git_info
            if _same_root(toplevel, prov.get("root") or ""):
                dirty_content_id: str | None = None
                if dirty:
                    dirty_content_id = compute_dirty_content_id(Path(toplevel))
                return GitState(
                    hash=hash_, branch=branch, dirty=dirty, dirty_content_id=dirty_content_id,
                    provenance_source="git",
                )

        status = prov.get("provenance_status", "")
        git_sha = prov.get("git_sha")
        git_branch = prov.get("git_branch")
        git_dirty_value = prov.get("git_dirty", "")
        if isinstance(git_dirty_value, bool):
            dirty = git_dirty_value
        elif isinstance(git_dirty_value, str):
            dirty = git_dirty_value == "1" if git_dirty_value else False
        else:
            dirty = False

        if status == "nogit":
            git_sha = "nogit"
        elif status == "unavailable" or not git_sha:
            git_sha = "unknown"

        return GitState(
            hash=git_sha or "unknown", branch=git_branch or "unknown", dirty=dirty,
            dirty_content_id=prov.get("dirty_content_id"), provenance_source=prov_source,
        )
    except Exception:
        return _UNKNOWN
