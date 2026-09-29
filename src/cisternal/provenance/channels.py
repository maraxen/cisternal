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

VERIFICATION (debt #2060): sidecar and env channels now verify their reported
git_sha against the actual files on disk using an embedded tree manifest.
A channel surfaces its sha only if the manifest parses, commits match, and
the disk content matches the manifest. Otherwise the sha is withheld and
code_verified is False/None. This prevents stale or corrupted sidecars from
reporting unrelated shas to bathos and other downstream consumers.

The "no channel data, just ask git directly" tier below delegates to
`cisternal.telemetry.git_state.capture_git_state()` rather than shelling out
to git itself. That module was merged into `main` (PR #29) while this one was
still on a feature branch, built independently for the same purpose -- its
own docstring calls it "the shared substrate other Praxia-family tools
delegate their local-shellout tier to, rather than each maintaining a
slightly-different subprocess-calling implementation of the same thing."
Maintaining a second implementation of that exact tier here, inside the very
module meant to be the canonical one, would be the same class of duplication
this whole provenance migration exists to eliminate -- just relocated one
level down. See `capture.py`'s module docstring for why `resolve_git_commit`/
`compute_dirty_content_id` do NOT also delegate here (different contract:
`strict=True` needs real error detail telemetry's always-degrade design
doesn't expose, and standalone dirty-id-only calls would otherwise pay for a
redundant full re-capture).
"""

from __future__ import annotations

import json
import os
import re as _re
import subprocess as _subprocess
import warnings as _warnings
from dataclasses import dataclass
from pathlib import Path

from cisternal.telemetry.git_state import capture_git_state as _capture_live_git_state

from .record import PROVENANCE_FILENAME, _VALID_PROVENANCE_STATUSES, MAX_KNOWN_SCHEMA_VERSION, read_sidecar
from .tree_manifest import TreeManifest, TreeVerification, verify_tree


@dataclass
class GitState:
    hash: str
    branch: str
    dirty: bool
    dirty_content_id: str | None = None
    provenance_source: str = "git"  # "git" | "myxcel-env" | "myxcel-sidecar" | "unverified-env" | "unverified-sidecar" | "none"
    code_verified: bool | None = None  # True: checked against disk NOW; False: checked and failed; None: could not check
    verification: TreeVerification | None = None

    @property
    def sha(self) -> str | None:
        """Return hash iff it is 40 lowercase hex, else None.

        This property guards access to the hash for callers who need only
        authoritative (verified) shas. The hard rule: a sidecar or env channel
        surfaces its hash ONLY when all verification conditions pass. For those
        channels, sha == hash iff code_verified is True. For live git or nogit,
        sha == hash always.
        """
        if self.hash and _re.fullmatch(r"[0-9a-f]{40}", self.hash):
            return self.hash
        return None


_WARNED: set[str] = set()


def _unknown() -> GitState:
    """Return a fresh unknown sentinel (not a shared mutable instance)."""
    return GitState(hash="unknown", branch="unknown", dirty=False, provenance_source="none")


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

    schema_version_str = os.environ.get("MYXCEL_PROVENANCE_SCHEMA", "")
    try:
        schema_version = int(schema_version_str) if schema_version_str else 0
    except ValueError:
        schema_version = 0

    return {
        "provenance_status": status,
        "git_sha": os.environ.get("MYXCEL_GIT_SHA", "") or None,
        "git_branch": os.environ.get("MYXCEL_GIT_BRANCH", "") or None,
        "git_dirty": os.environ.get("MYXCEL_GIT_DIRTY", ""),
        "dirty_content_id": os.environ.get("MYXCEL_GIT_DIRTY_CONTENT_ID", "") or None,
        "root": root_str or None,
        "schema_version": schema_version,
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
                schema_version = data.get("schema_version", 0)
                if schema_version > MAX_KNOWN_SCHEMA_VERSION:
                    _warnings.warn(
                        f"myxcel provenance sidecar at {sidecar_path} has schema_version="
                        f"{schema_version}, newer than this reader understands "
                        f"(max known: {MAX_KNOWN_SCHEMA_VERSION}) -- reading only the fields this version knows about.",
                        stacklevel=2,
                    )
                return {
                    "provenance_status": data.get("provenance_status"),
                    "git_sha": data.get("git_sha"),
                    "git_branch": data.get("git_branch"),
                    "git_dirty": data.get("git_dirty"),
                    "dirty_content_id": data.get("dirty_content_id"),
                    "root": data.get("provenance_root"),
                    "tree_manifest": data.get("tree_manifest") if isinstance(data.get("tree_manifest"), dict) else None,
                    "sidecar_path": str(sidecar_path),
                    "schema_version": schema_version,
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


def _is_worktree_of(cwd: str | Path, repo_root: str | Path) -> bool:
    """Check if cwd is a linked worktree of the repository at repo_root.

    Returns True iff the parent of cwd's git-common-dir equals repo_root.
    Never raises (C6): any failure returns False.
    """
    try:
        result = _subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        common_dir_str = result.stdout.strip()
        if not common_dir_str:
            return False
        common_dir = Path(common_dir_str)
        common_dir_parent = common_dir.parent
        repo_root_path = Path(repo_root).resolve()
        return _same_root(common_dir_parent, repo_root_path)
    except Exception:
        return False


def _record_says_clean(value: object) -> bool:
    """Check if git_dirty explicitly says clean: False (bool) or "0" (str).

    Anything else (None, "", True, "1", garbage) means not-clean.
    """
    return value is False or value == "0"


def _warn_withheld(key: str, reason: str) -> None:
    """Emit a one-time warning per key when a sidecar's sha is withheld.

    The warning text MUST NOT include the claimed git_sha or any commit hash,
    only the path, reason, and fix.
    """
    if key in _WARNED:
        return
    _WARNED.add(key)
    try:
        _warnings.warn(
            f"provenance channel at {key} withheld its git sha: {reason}. "
            f"Re-push with a tree-manifest-writing myxcel (#2059), or `myxcel clean` stale files.",
            stacklevel=3,
        )
    except Exception:
        # -W error cannot escape into capture_git_state's catch-all
        pass


def _gate(prov: dict, prov_source: str, cwd: Path) -> GitState:
    """Verify a sidecar/env channel record and return an authoritative GitState.

    If verification succeeds, surfaces the sha with code_verified=True.
    Otherwise withholds the sha and returns hash="unknown" with code_verified
    False (checked and failed) or None (could not check).
    """
    status = prov.get("provenance_status", "")
    claimed_sha = prov.get("git_sha")
    git_branch = prov.get("git_branch") or "unknown"

    # Parse dirty from the record (not recomputable; used as-is)
    git_dirty_value = prov.get("git_dirty", "")
    record_says_clean = _record_says_clean(git_dirty_value)

    # For env channels, we may have a sidecar_rec to check against
    sidecar_rec_for_env = None

    # nogit status: no sha to protect, surface it as-is
    if status == "nogit":
        return GitState(
            hash="nogit",
            branch=git_branch,
            dirty=not record_says_clean,
            dirty_content_id=None,
            provenance_source=prov_source,
            code_verified=None,
        )

    # No sha claimed, or unavailable status: return unknown
    if status == "unavailable" or not claimed_sha:
        return GitState(
            hash="unknown",
            branch="unknown",
            dirty=False,
            provenance_source=prov_source,
            code_verified=None,
        )

    # A sha IS claimed: verify it against the tree manifest

    # Determine root_dir and manifest based on channel source
    if prov_source == "myxcel-sidecar":
        sidecar_path_str = prov.get("sidecar_path")
        if not sidecar_path_str:
            # No sidecar_path means we cannot verify against the correct directory
            reason = "sidecar path unknown"
            _warn_withheld(str(claimed_sha or "unknown"), reason)
            return GitState(
                hash="unknown",
                branch="unknown",
                dirty=True,
                dirty_content_id=None,
                provenance_source="unverified-sidecar",
                code_verified=None,
            )
        root_dir = Path(sidecar_path_str).parent
        manifest_dict = prov.get("tree_manifest")
    else:  # myxcel-env
        root_dir = Path(prov.get("root", "."))
        # For env, try to read the sidecar at root to get the manifest
        sidecar_rec = read_sidecar(root_dir)
        sidecar_rec_for_env = sidecar_rec
        if sidecar_rec is None or sidecar_rec.tree_manifest is None:
            if sidecar_rec is None:
                reason = "no tree manifest at MYXCEL_PROVENANCE_ROOT"
            else:
                reason = "no tree manifest at MYXCEL_PROVENANCE_ROOT"
            _warn_withheld(str(root_dir), reason)
            return GitState(
                hash="unknown",
                branch="unknown",
                dirty=True,
                dirty_content_id=None,
                provenance_source="unverified-env",
                code_verified=None,
            )
        elif sidecar_rec.git_sha != claimed_sha:
            reason = "env sha does not match sidecar sha"
            _warn_withheld(str(root_dir), reason)
            return GitState(
                hash="unknown",
                branch="unknown",
                dirty=True,
                dirty_content_id=None,
                provenance_source="unverified-env",
                code_verified=False,
            )
        else:
            manifest_dict = sidecar_rec.tree_manifest

    # Parse the manifest
    manifest = TreeManifest.from_dict(manifest_dict) if manifest_dict is not None else None

    if manifest is None:
        reason = "no tree manifest (schema v1 sidecar)" if not manifest_dict else "unparseable tree manifest"
        _warn_withheld(str(root_dir), reason)
        return GitState(
            hash="unknown",
            branch="unknown",
            dirty=True,
            dirty_content_id=None,
            provenance_source=("unverified-sidecar" if prov_source == "myxcel-sidecar" else "unverified-env"),
            code_verified=None,
        )

    # Check that manifest.commit == claimed_sha
    if manifest.commit != claimed_sha:
        reason = "tree manifest commit does not match git_sha"
        _warn_withheld(str(root_dir), reason)
        return GitState(
            hash="unknown",
            branch="unknown",
            dirty=True,
            dirty_content_id=None,
            provenance_source=("unverified-sidecar" if prov_source == "myxcel-sidecar" else "unverified-env"),
            code_verified=False,
        )

    # Check that cwd is inside root_dir (D3 condition 3)
    try:
        cwd_resolved = cwd.resolve()
        root_resolved = root_dir.resolve()
        if not cwd_resolved.is_relative_to(root_resolved):
            reason = "cwd is not inside sidecar directory"
            _warn_withheld(str(root_dir), reason)
            return GitState(
                hash="unknown",
                branch="unknown",
                dirty=True,
                dirty_content_id=None,
                provenance_source=("unverified-sidecar" if prov_source == "myxcel-sidecar" else "unverified-env"),
                code_verified=False,
            )
    except (ValueError, OSError):
        reason = "cwd path resolution failed"
        _warn_withheld(str(root_dir), reason)
        return GitState(
            hash="unknown",
            branch="unknown",
            dirty=True,
            dirty_content_id=None,
            provenance_source=("unverified-sidecar" if prov_source == "myxcel-sidecar" else "unverified-env"),
            code_verified=False,
        )

    # Verify the tree
    v = verify_tree(root_dir, manifest, cwd=cwd, dirty_content_id=prov.get("dirty_content_id"))

    if not v.verified:
        mismatches = len(v.mismatched)
        missing = len(v.missing)
        extras = len(v.extra_untracked_under_declared_dirs)
        reason = f"{mismatches} mismatched, {missing} missing, {extras} extra"
        if v.error:
            reason += f"; {v.error}"
        _warn_withheld(str(root_dir), reason)
        return GitState(
            hash="unknown",
            branch="unknown",
            dirty=True,
            dirty_content_id=None,
            provenance_source=("unverified-sidecar" if prov_source == "myxcel-sidecar" else "unverified-env"),
            code_verified=False,
            verification=v,
        )

    # All checks passed: surface the sha
    # For env channels: dirty = (env says dirty) or (sidecar says dirty) or (manifest doesn't match commit)
    # For sidecar channels: dirty = (record says dirty) or (manifest doesn't match commit)
    if prov_source == "myxcel-env" and sidecar_rec_for_env is not None:
        # 3-way clean check: both env and sidecar must say clean
        sidecar_says_clean = _record_says_clean(sidecar_rec_for_env.git_dirty)
        dirty = (not record_says_clean) or (not sidecar_says_clean) or (not manifest.matches_commit)
        # Use sidecar's dirty_content_id for env channel
        dirty_content_id = sidecar_rec_for_env.dirty_content_id
    else:
        # Sidecar channel
        dirty = (not record_says_clean) or (not manifest.matches_commit)
        dirty_content_id = prov.get("dirty_content_id")

    return GitState(
        hash=claimed_sha,
        branch=git_branch,
        dirty=dirty,
        dirty_content_id=dirty_content_id,
        provenance_source=prov_source,
        code_verified=True,
        verification=v,
    )


def capture_git_state(cwd: Path | None = None) -> GitState:
    """Capture git provenance from multiple channels with defined precedence.

    D6 precedence (per praxia debt #1802):
    1. Check env and sidecar channels; if neither present, capture live git state
       directly (via telemetry.git_state) or fall back to _unknown()
    2. If a channel exists and a real repo exists at the same root, use the real repo
    3. If a channel exists and live checkout is a linked worktree of the channel's repo, use live
    4. Otherwise use the channel (with verification per debt #2060)

    Never raises (C6).
    """
    try:
        cwd = cwd if cwd is not None else Path.cwd()
        cwd_path = Path(cwd)
        cwd_str = str(cwd)

        env_prov = _env_channel(cwd_str)
        if env_prov is not None:
            prov = env_prov
            prov_source = "myxcel-env"
        else:
            prov = _sidecar_channel(cwd_str)
            prov_source = "myxcel-sidecar"

        if prov is None:
            live = _capture_live_git_state(cwd)
            if live.provenance_source != "git":
                return _unknown()
            return GitState(
                hash=live.hash, branch=live.branch, dirty=live.dirty,
                dirty_content_id=live.dirty_content_id, provenance_source="git",
                code_verified=True,
            )

        live = _capture_live_git_state(cwd)
        if live.provenance_source == "git" and live.toplevel is not None:
            if _same_root(live.toplevel, prov.get("root") or ""):
                return GitState(
                    hash=live.hash, branch=live.branch, dirty=live.dirty,
                    dirty_content_id=live.dirty_content_id, provenance_source="git",
                    code_verified=True,
                )
            # Also use live git if the current directory is a linked worktree
            # of the repository described by the channel (same .git admin directory)
            if _is_worktree_of(cwd_str, prov.get("root") or ""):
                return GitState(
                    hash=live.hash, branch=live.branch, dirty=live.dirty,
                    dirty_content_id=live.dirty_content_id, provenance_source="git",
                    code_verified=True,
                )

        # Use the channel with verification
        return _gate(prov, prov_source, cwd_path)
    except Exception:
        return _unknown()
