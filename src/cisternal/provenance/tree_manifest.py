"""Tree manifest writer and verifier for no-.git provenance.

Two independent problems, solved here:

1. **Build a content-addressed manifest of the files transferred in a push**,
   with their raw (no-filter) git blob IDs and modes. This is the writer path
   (myxcel, at push time), which enumerates the actual pushed files, computes
   their hashes, and embeds the manifest in the sidecar so the reader can
   verify it later.

2. **Verify that a manifest still matches the disk** on a no-.git host, with
   content/mode checks, ignore-aware extras detection, and a budget. This is
   the reader path (bathos, at run time), which takes a manifest from the
   sidecar and checks whether the code on disk has been modified, deleted, or
   contaminated.

Both paths use pure-Python git-blob-sha1 hashing (no binary dependency) and
never raise -- they degrade to a logged reason and a None/failed result. The
exception is verify_tree, which wraps all exceptions in the result rather than
propagating them.

Tree manifest format: MANIFEST_VERSION=1, HASH_ALGO="git-blob-sha1-nofilter".
Files are enumerated from a git ls-files or explicit paths, dropping symlinks
to nonexistent targets, and excluding .git and PROVENANCE_FILENAME by
construction.

Submodule gitlinks. A path that is a gitlink (mode 160000) in ``commit``'s tree is
recorded in ``files`` as ``("160000", <pinned commit sha>)`` -- exactly git's own tree
entry, so ``tree_id`` and ``matches_commit`` keep their meaning. The submodule's files are
never hashed into the manifest. The writer checks, at build time and locally, that the
submodule is initialised and its checked-out HEAD equals the pin; if it is not (or cannot
be read) the path goes to ``skipped`` as ``gitlink-uninitialized:<path>``,
``gitlink-mismatch:<path>`` or ``gitlink-unreadable:<path>`` and the manifest fails
closed. The reader has no ``.git`` to ask for the submodule's HEAD, so it checks the one
thing it can: the path is absent or an empty directory (nothing unhashed can run from
it). A directory that is not a gitlink in ``commit`` (a plain directory, an untracked
nested repo) or any directory when ``commit`` is None keeps the old ``gitlink:<path>``
skip. A manifest carrying a 160000 entry is rejected as unparseable by readers that
predate this support (their ``from_dict`` mode whitelist), so they withhold the SHA
rather than verify without the new check.

Pushed submodule content. When the submodule is initialised at the pin, the writer also
records ``submodules[<gitlink>] = {"tree": <pinned commit's tree sha>, "files": {relpath:
(mode, blob)}}`` taken from the pinned commit's tree, after checking the submodule working
tree equals it (a dirty or nested-gitlink submodule fails closed: ``gitlink-dirty:`` /
``gitlink-nested:``). ``files`` and ``tree_id`` still carry only the pin, so their meaning is
unchanged. The reader, on a copy with no ``.git``, then verifies a populated gitlink
directory by content against those entries: tampered files are ``mismatched``, absent ones
``missing``, anything else under it an extra. A populated gitlink with no ``submodules``
entry, and an absent or empty one, behave as before. Verified submodules are listed in
``TreeVerification.verified_submodules``. ``manifest_ok`` also requires each recorded
``files`` set to hash to its recorded ``tree``. Trust boundary: a reader without the
submodule's object database cannot turn the pin (a commit sha) into a tree sha, so
``submodules`` is trusted exactly as far as the sidecar that carries it, like every other
manifest entry; ``tree_id`` anchors only the pin. Every recorded submodule directory is scanned
for extras with no ignore rules (a ``.gitignore`` shipped in the submodule cannot hide files),
even when its path is top-level or absent from ``declared_dirs``. An empty recorded file list
vouches for nothing, so a populated directory with one is not accepted.

Verification budget. ``verify_tree(max_seconds=None)`` resolves the time budget by
``resolve_max_seconds``: explicit argument > ``CISTERNAL_PROVENANCE_MAX_SECONDS`` (empty or
``none`` = use the default) > ``[tool.cisternal.provenance] max_seconds`` in the nearest
``pyproject.toml`` above the verified root > ``[provenance] max_seconds`` in
``${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml`` > the default, which scales with the
manifest's file count. The deciding layer is reported in ``TreeVerification.budget_source``;
a malformed value yields ``verified=False`` with an explicit ``error`` and never a silent default.
"""

from __future__ import annotations

import hashlib
import logging
import os
import posixpath
import re
import stat
import subprocess
import tempfile
import time
import math
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, cast

from .capture import clean_git_env
from .record import PROVENANCE_FILENAME

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
HASH_ALGO = "git-blob-sha1-nofilter"
GITLINK_MODE = "160000"  # git's tree-entry mode for a submodule; the "blob" is the pinned commit sha
DEFAULT_MAX_BYTES = 4 * 1024**3
DEFAULT_MAX_SECONDS = 60.0  # floor of the default budget (see resolve_max_seconds)
DEFAULT_SECONDS_PER_FILE = 0.5  # default budget scales at this per-file rate (2 files/s; Engaging /orcd/pool measured ~8/s)
DEFAULT_MAX_SECONDS_CAP = 900.0  # ceiling of the *scaled default*; an explicit/configured value is never capped
MAX_SECONDS_ENV_VAR = "CISTERNAL_PROVENANCE_MAX_SECONDS"
BUILTIN_EXTRA_EXCLUDES = ("__pycache__/",)
# Bytecode inside __pycache__ is regenerated by the interpreter and a sourceless .pyc
# there is never imported, so it is always excludable even if not in .gitignore.
# Deliberately NOT "*.pyc": a sourceless legacy-location src/pkg/mod.pyc IS importable
# (SourcelessFileLoader), so it must still be reported as an extra.

# bathos writes `<script>.bth.<run-uuid>.bth.lock.toml` next to the script on every tracked run. On a no-.git host that
# directory is a declared dir, so without an exemption each run would un-verify the host for the next one (myxcel debt 2296
# class). It is a TOML data file the run itself writes -- it cannot be imported or executed -- so exactly this basename shape
# is exempt from the EXTRAS check, and only while untracked (a manifest that lists it verifies it by content like any file).
# Deliberately narrow: the uuid is required and lowercase, and the tail is exactly `.bth.lock.toml`, so an importable
# `....bth.lock.py`, a truncated uuid or a bare `x.bth.lock.toml` is still reported as an extra.
_BATHOS_LOCK_MANIFEST_RE = re.compile(
    r"^.+\.bth\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.bth\.lock\.toml$"
)


def is_bathos_lock_manifest(relpath: str) -> bool:
    """True iff ``relpath``'s basename is exactly bathos's run-lock shape ``<stem>.bth.<uuid>.bth.lock.toml``."""
    # fullmatch, not match: `$` also matches before a trailing "\n" (git -z and os.walk both return such names), which would exempt a name
    # that is not exactly the lock shape.
    return _BATHOS_LOCK_MANIFEST_RE.fullmatch(posixpath.basename(relpath)) is not None


def blob_id(data: bytes) -> str:
    """Compute git blob SHA-1 of raw bytes (no filters).

    Git blob format: b"blob %d\0" + data, where %d is the byte length.
    Returns 40-character hex string (lowercase).
    """
    blob_header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(blob_header + data).hexdigest()


def tree_id(files: Mapping[str, tuple[str, str]]) -> str:
    """Compute git tree OID from a mapping of path -> (mode, blob_hex).

    Paths must be POSIX-relative and sorted in git order (by UTF-8 bytes,
    with directories sorted as name + "/").

    A git tree object is: b"tree %d\0" + concat of entries, where each entry is:
    b"<mode> <name>\0" + bytes.fromhex(blob_hex), and mode is one of
    "100644" (regular), "100755" (exec), "120000" (symlink), "160000" (submodule
    gitlink; the "blob" is the pinned commit sha), or "40000" (dir).

    This function builds a multi-level tree structure, hashing each level
    bottom-up.
    """
    if not files:
        # Empty tree
        return hashlib.sha1(b"tree 0\0").hexdigest()

    root = _TreeNode()
    for path, (mode, blob_hex) in files.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            if part in node.files:
                logger.warning("tree_id: path conflict (file and directory): %s", path)
                return ""
            node = node.dirs.setdefault(part, _TreeNode())
        if parts[-1] in node.dirs:
            logger.warning("tree_id: path conflict (file and directory): %s", path)
            return ""
        node.files[parts[-1]] = (mode, blob_hex)

    return root.oid()


class _TreeNode:
    """One directory level while building a git tree object bottom-up."""

    __slots__ = ("dirs", "files")

    def __init__(self) -> None:
        self.dirs: dict[str, _TreeNode] = {}
        self.files: dict[str, tuple[str, str]] = {}

    def oid(self) -> str:
        # git orders entries by name bytes, with a directory compared as name + "/".
        entries: list[tuple[bytes, bytes, str]] = [
            (name.encode("utf-8"), b"40000", sub.oid()) for name, sub in self.dirs.items()
        ]
        entries += [
            (name.encode("utf-8"), mode.encode("utf-8"), blob) for name, (mode, blob) in self.files.items()
        ]
        entries.sort(key=lambda e: e[0] + (b"/" if e[1] == b"40000" else b""))
        content = b"".join(mode + b" " + name + b"\0" + bytes.fromhex(sha) for name, mode, sha in entries)
        return hashlib.sha1(b"tree %d\0" % len(content) + content).hexdigest()


@dataclass(frozen=True)
class TreeManifest:
    """Content-addressed manifest of files transferred in a push.

    manifest_version: 1
    hash_algo: "git-blob-sha1-nofilter"
    commit: The git commit SHA when captured, or None if unavailable.
    tree_id: Git tree OID computed from files.
    declared_dirs: Directories scanned for extras during verification.
    matches_commit: True iff every manifest file is tracked in commit
                    and its raw blob equals commit's blob (matches_commit per D1).
    extra_excludes: Ignore patterns from .git/info/exclude, core.excludesFile, etc.
    files: Mapping of posix_relpath -> (mode, blob_hex). A submodule gitlink is
           ("160000", <pinned commit sha>); see the module docstring.
    skipped: Paths that were encountered but could not be covered, as
             "<reason>:<path>" (non-utf8, unreadable, gitlink:, gitlink-uninitialized:,
             gitlink-mismatch:, gitlink-unreadable:, gitlink-dirty:, gitlink-nested:). Any entry
             makes verify_tree fail closed.
    submodules: Mapping of gitlink path -> (tree sha of the pinned commit, {relpath: (mode, blob)})
                for initialised submodules, so a pushed copy verifies by content. Optional; absent
                from the serialised form when empty. Not part of ``tree_id``.
    """

    manifest_version: int
    hash_algo: str
    commit: str | None
    tree_id: str
    declared_dirs: tuple[str, ...]
    matches_commit: bool
    extra_excludes: tuple[str, ...]
    files: dict[str, tuple[str, str]]
    skipped: tuple[str, ...] = ()
    submodules: dict[str, tuple[str, dict[str, tuple[str, str]]]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return JSON-ready dict (lists not tuples, files as {path: [mode, blob]})."""
        out = {
            "manifest_version": self.manifest_version,
            "hash_algo": self.hash_algo,
            "commit": self.commit,
            "tree_id": self.tree_id,
            "declared_dirs": list(self.declared_dirs),
            "matches_commit": self.matches_commit,
            "extra_excludes": list(self.extra_excludes),
            "files": {path: list(entry) for path, entry in self.files.items()},
            "skipped": list(self.skipped),
        }
        if self.submodules:
            out["submodules"] = {
                path: {"tree": tree, "files": {rel: list(entry) for rel, entry in sub_files.items()}}
                for path, (tree, sub_files) in self.submodules.items()
            }
        return out

    @classmethod
    def from_dict(cls, d: object) -> TreeManifest | None:
        """Deserialize from dict. Returns None (never raises) if invalid."""
        if not isinstance(d, dict):
            return None
        d = cast(dict[str, Any], d)

        try:
            manifest_version = d.get("manifest_version")
            if manifest_version != MANIFEST_VERSION:
                return None

            hash_algo = d.get("hash_algo")
            if hash_algo != HASH_ALGO:
                return None

            commit = d.get("commit")
            tree_id = d.get("tree_id")
            declared_dirs = tuple(d.get("declared_dirs", []))
            matches_commit = d.get("matches_commit", False)
            extra_excludes = tuple(d.get("extra_excludes", []))
            skipped = tuple(d.get("skipped", []))

            # Strict validation: these are consumed as strings downstream (warnings, exclude files).
            if not all(isinstance(x, str) for x in (*declared_dirs, *extra_excludes, *skipped)):
                return None

            # Strict validation: matches_commit must be bool
            if not isinstance(matches_commit, bool):
                return None

            # Strict validation: tree_id is required; commit may be None. Both lowercase 40-hex.
            if not isinstance(tree_id, str) or not _is_valid_hex(tree_id, 40):
                return None
            if commit is not None:
                if not isinstance(commit, str) or not _is_valid_hex(commit, 40):
                    return None

            # Validate files: must be dict of path -> [mode, blob_hex]
            files_raw = d.get("files", {})
            if not isinstance(files_raw, dict):
                return None

            files: dict[str, tuple[str, str]] = {}
            for path, entry in files_raw.items():
                if not isinstance(path, str):
                    return None
                if not isinstance(entry, list) or len(entry) != 2:
                    return None
                mode, blob_hex = entry
                if not isinstance(mode, str) or mode not in ("100644", "100755", "120000", GITLINK_MODE):
                    return None
                if not isinstance(blob_hex, str) or not _is_valid_hex(blob_hex, 40):
                    return None
                files[path] = (mode, blob_hex)

            submodules = _parse_submodules(d.get("submodules", {}), files)
            if submodules is None:
                return None

            return cls(
                manifest_version=manifest_version,
                hash_algo=hash_algo,
                commit=commit,
                tree_id=tree_id,
                declared_dirs=declared_dirs,
                matches_commit=matches_commit,
                extra_excludes=extra_excludes,
                files=files,
                skipped=skipped,
                submodules=submodules,
            )
        except (KeyError, TypeError, ValueError):
            return None


def _safe_relpath(rel: object) -> bool:
    """True for a non-empty POSIX relative path with no empty, ``.`` or ``..`` component."""
    if not isinstance(rel, str) or not rel or "\0" in rel:
        return False
    return all(part not in ("", ".", "..", ".git") for part in rel.split("/"))


def _parse_submodules(
    raw: object, files: Mapping[str, tuple[str, str]]
) -> dict[str, tuple[str, dict[str, tuple[str, str]]]] | None:
    """Validate the serialised ``submodules`` table; None if malformed.

    Each key must be a gitlink entry of ``files``; each file entry is a regular/exec/symlink
    blob (a nested gitlink is never recorded) at a safe relative path.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {}
    for path, body in raw.items():
        if not isinstance(path, str) or files.get(path, ("", ""))[0] != GITLINK_MODE:
            return None
        if not isinstance(body, dict):
            return None
        tree, sub_raw = body.get("tree"), body.get("files")
        if not isinstance(tree, str) or not _is_valid_hex(tree, 40) or not isinstance(sub_raw, dict):
            return None
        sub_files: dict[str, tuple[str, str]] = {}
        for rel, entry in sub_raw.items():
            if not _safe_relpath(rel) or not isinstance(entry, list) or len(entry) != 2:
                return None
            mode, blob_hex = entry
            if mode not in ("100644", "100755", "120000"):
                return None
            if not isinstance(blob_hex, str) or not _is_valid_hex(blob_hex, 40):
                return None
            sub_files[rel] = (mode, blob_hex)
        out[path] = (tree, sub_files)
    return out


def _is_valid_hex(s: str, length: int) -> bool:
    """Check if s is a valid lowercase hex string of given length."""
    if len(s) != length:
        return False
    # Must be lowercase hex
    if not all(c in "0123456789abcdef" for c in s):
        return False
    return True


@dataclass(frozen=True)
class TreeVerification:
    """Result of verifying a manifest against disk.

    verified: True iff manifest_ok and no mismatched/missing/extra files.
    n_files: Number of files in the manifest.
    n_match: Number of files that matched on disk (same blob and mode).
    mismatched: Paths with content differences (blob differs).
    missing: Paths not found on disk.
    extra_untracked_under_declared_dirs: Untracked files under declared dirs,
                                         not matched by extra_excludes.
    mode_changed: Paths with different mode (exec bit) but same blob.
    manifest_ok: manifest_version == MANIFEST_VERSION and hash_algo matches
                 and tree_id(recomputed) == manifest.tree_id.
    extras_ignore_aware: True if extras were detected using git ls-files
                         (respects .gitignore), False if fallback Python walk.
    tree_id: Recomputed tree_id from disk, or None if any missing.
    dirty_content_id_consistent: None if dirty_content_id arg was None;
                                 else True iff it matches "tree:" + tree_id.
    error: Set if an exception was caught or a constraint was violated.
    exempt_lock_manifests: Untracked bathos run-lock manifests (see
                           ``is_bathos_lock_manifest``) that were NOT counted as
                           extras. Reported so the exemption is auditable, never
                           silent. Empty on the early-error returns, where extras
                           were not fully scanned.
    verified_submodules: Gitlink paths whose populated directory was verified by content against
                         ``TreeManifest.submodules`` (so the pushed copy is accounted for, not
                         skipped). n_files / n_match then also count those submodule files.
    budget_seconds: The time budget actually applied (None only if it could not be resolved).
    budget_source: Which layer set it: ``arg``, ``env:<NAME>``, ``env:<NAME> (disabled -> default)``,
                   ``pyproject:<path>``, ``user-config:<path>`` or ``default (scaled: ...)``.
    """

    verified: bool
    n_files: int
    n_match: int
    mismatched: tuple[str, ...]
    missing: tuple[str, ...]
    extra_untracked_under_declared_dirs: tuple[str, ...]
    mode_changed: tuple[str, ...]
    manifest_ok: bool
    extras_ignore_aware: bool
    tree_id: str | None
    dirty_content_id_consistent: bool | None
    error: str | None
    exempt_lock_manifests: tuple[str, ...] = ()
    verified_submodules: tuple[str, ...] = ()
    budget_seconds: float | None = None
    budget_source: str | None = None


def _ls_commit_tree(root: Path, commit: str) -> dict[str, tuple[str, str]] | None:
    """`git ls-tree -r -z <commit>` as {path: (mode, oid)}, or None if it could not be read.

    Includes gitlinks (mode 160000, oid = the pinned submodule commit). Entries whose path is not
    UTF-8 are omitted, as `matches_commit` always did. Never raises.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-r", "-z", commit],
            capture_output=True,
            env=clean_git_env(),
            timeout=60.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug("build_tree_manifest: git ls-tree failed: %s", e)
        return None
    if result.returncode != 0:
        return None
    entries: dict[str, tuple[str, str]] = {}
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        # Format: "<mode> <type> <object>\t<file>"
        parts = item.split(b"\t", 1)
        if len(parts) != 2:
            continue
        tree_info = parts[0].split()
        if len(tree_info) < 3:
            continue
        try:
            entries[parts[1].decode("utf-8")] = (
                tree_info[0].decode("ascii"),
                tree_info[2].decode("utf-8", errors="replace"),
            )
        except UnicodeDecodeError:
            continue
    return entries


def _inspect_submodule(root: Path, rel: str, pin: str) -> str | None:
    """Check a submodule locally; return None if it is initialised with HEAD == ``pin``, else a skip reason.

    Reasons: ``gitlink-uninitialized`` (no ``.git`` of its own), ``gitlink-unreadable`` (git could
    not report its HEAD or toplevel), ``gitlink-mismatch`` (HEAD is not the pinned commit).
    The submodule's own ``.git`` and toplevel are required before reading HEAD: an uninitialised
    submodule is an empty directory inside the superproject, and ``git -C <it> rev-parse HEAD``
    would silently answer with the SUPERPROJECT's HEAD. Its working tree is not inspected: its
    files are not part of the manifest and a push does not transfer them. Never raises.
    """
    sub = root / rel
    if not os.path.lexists(sub / ".git"):
        return "gitlink-uninitialized"
    try:
        env = clean_git_env()
        top = subprocess.run(
            ["git", "-C", str(sub), "rev-parse", "--show-toplevel"],
            capture_output=True, env=env, timeout=10.0,
        )
        if top.returncode != 0:
            return "gitlink-unreadable"
        if os.path.realpath(top.stdout.decode("utf-8", errors="replace").strip()) != os.path.realpath(sub):
            return "gitlink-uninitialized"  # .git exists but git resolves to some other repo
        head = subprocess.run(
            ["git", "-C", str(sub), "rev-parse", "HEAD"],
            capture_output=True, env=env, timeout=10.0,
        )
        if head.returncode != 0:
            return "gitlink-unreadable"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug("build_tree_manifest: cannot inspect submodule %s: %s", sub, e)
        return "gitlink-unreadable"
    if head.stdout.decode("utf-8", errors="replace").strip() != pin:
        return "gitlink-mismatch"
    return None


def _collect_submodule(root: Path, rel: str, pin: str) -> tuple[str, dict[str, tuple[str, str]]] | str:
    """Record an initialised submodule (HEAD already checked == ``pin``) from the pinned commit's tree.

    Returns ``(tree sha, {relpath: (mode, blob)})`` or a skip reason: ``gitlink-nested`` (the
    submodule itself holds a gitlink, whose content is never hashed), ``gitlink-unreadable`` (the
    tree could not be listed, or does not hash to the pinned commit's tree, e.g. a non-UTF-8 name),
    ``gitlink-dirty`` (a tracked file's working-tree content or mode differs from the pin).
    Untracked files in the submodule are not inspected here: the reader reports them as extras.
    Never raises.
    """
    sub = root / rel
    tree = _ls_commit_tree(sub, pin)
    if tree is None:
        return "gitlink-unreadable"
    if any(mode == GITLINK_MODE for mode, _ in tree.values()):
        return "gitlink-nested"
    try:
        top = subprocess.run(
            ["git", "-C", str(sub), "rev-parse", f"{pin}^{{tree}}"],
            capture_output=True, env=clean_git_env(), timeout=10.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "gitlink-unreadable"
    tree_sha = top.stdout.decode("ascii", errors="replace").strip()
    if top.returncode != 0 or tree_id(tree) != tree_sha:
        return "gitlink-unreadable"
    for rel_file, (mode, blob_hex) in tree.items():
        path = sub / rel_file
        try:
            if os.path.islink(path):
                actual = ("120000", blob_id(os.fsencode(os.readlink(path))))
            else:
                st = os.stat(path)
                if not stat.S_ISREG(st.st_mode):
                    return "gitlink-dirty"
                hasher = hashlib.sha1(f"blob {st.st_size}\0".encode("utf-8"))
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hasher.update(chunk)
                actual = ("100755" if (st.st_mode & 0o111) else "100644", hasher.hexdigest())
        except OSError:
            return "gitlink-dirty"
        if actual != (mode, blob_hex):
            return "gitlink-dirty"
    return tree_sha, dict(tree)


def build_tree_manifest(
    root: Path,
    *,
    commit: str | None,
    paths: Iterable[str] | None = None,
    declared_dirs: Iterable[str] | None = None,
    extra_excludes: Iterable[str] | None = None,
) -> TreeManifest | None:
    """Build a tree manifest for the given root directory.

    root: Repository or project root (no .git required).
    commit: Git commit SHA (from rev-parse HEAD), or None.
    paths: Explicit list of files to manifest. If None, enumerate from
           git ls-files -z --cached --others --exclude-standard.
    declared_dirs: Directories to scan for extras verification. If None,
                   default to sorted top-level dirs from files that contain "/".
    extra_excludes: Ignore patterns to embed. If None, read from
                    .git/info/exclude and core.excludesFile, else empty.

    Never raises. Returns None with a logged warning on failure.
    """
    try:
        root = Path(root)

        # Enumerate files
        non_utf8: list[str] = []
        if paths is None:
            try:
                result = subprocess.run(
                    ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                    capture_output=True,
                    env=clean_git_env(),
                    timeout=60.0,
                )
                if result.returncode != 0:
                    logger.warning(
                        "build_tree_manifest: git ls-files failed for %s (exit %d): %s",
                        root, result.returncode, result.stderr.decode("utf-8", errors="replace").strip()[:200]
                    )
                    return None
                # Parse as bytes first, then decode each entry separately
                paths_bytes = result.stdout.split(b"\0")
                paths: list[str] = []
                for path_bytes in paths_bytes:
                    if not path_bytes:
                        continue
                    try:
                        paths.append(path_bytes.decode("utf-8"))
                    except UnicodeDecodeError:
                        # Recorded (not dropped): a non-UTF-8 skip fails verification.
                        non_utf8.append(f"non-utf8:{path_bytes!r}")
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
                logger.warning("build_tree_manifest: git ls-files failed for %s: %s", root, e)
                return None
        else:
            paths = list(paths)

        # Process files: hash them, validate paths, drop non-existent
        files: dict[str, tuple[str, str]] = {}
        skipped: list[str] = list(non_utf8)
        submodules: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {}

        # One ls-tree of `commit` answers both "which directories are submodule gitlinks (and at
        # what pin)" and, below, matches_commit. None (no commit, or unreadable) means no path is
        # known to be a gitlink, so every directory keeps the old fail-closed `gitlink:` skip.
        commit_tree = _ls_commit_tree(root, commit) if commit else None
        gitlink_pins: dict[str, str] = (
            {p: oid for p, (m, oid) in commit_tree.items() if m == GITLINK_MODE} if commit_tree else {}
        )

        for path_str in sorted(paths):
            if path_str == PROVENANCE_FILENAME or not path_str:
                continue

            # Validate UTF-8 for caller-supplied paths
            try:
                path_str.encode("utf-8")
            except UnicodeEncodeError:
                skipped.append(f"non-utf8:{path_str!r}")
                continue

            path = root / path_str
            posix_path = path_str.replace(os.sep, "/")

            try:
                # Check if path is a directory (gitlink or nested repo)
                if os.path.isdir(path) and not os.path.islink(path):
                    pin = gitlink_pins.get(posix_path.rstrip("/"))
                    if pin is None:
                        # Not a gitlink in `commit` (plain dir, untracked nested repo, or commit unknown).
                        skipped.append(f"gitlink:{posix_path}")
                        continue
                    # A submodule: record its pin only if the checked-out HEAD IS the pin.
                    gl = posix_path.rstrip("/")
                    reason = _inspect_submodule(root, gl, pin)
                    collected = _collect_submodule(root, gl, pin) if reason is None else reason
                    if isinstance(collected, str):
                        skipped.append(f"{collected}:{posix_path}")
                    else:
                        files[gl] = (GITLINK_MODE, pin)
                        submodules[gl] = collected
                    continue

                # Check if it's a symlink
                if os.path.islink(path):
                    try:
                        link_target_bytes = os.fsencode(os.readlink(path))
                        blob_hex = blob_id(link_target_bytes)
                        files[posix_path] = ("120000", blob_hex)
                    except (OSError, UnicodeDecodeError) as e:
                        logger.debug("build_tree_manifest: failed to read symlink %s: %s", path, e)
                        skipped.append(f"unreadable:{posix_path}")
                    continue

                # Regular file: stat first to check it's a regular file
                st = os.stat(path)
                if not stat.S_ISREG(st.st_mode):
                    logger.debug("build_tree_manifest: path is not a regular file: %s", path)
                    skipped.append(f"unreadable:{posix_path}")
                    continue

                # Read file and compute blob ID (with chunked hashing)
                blob_header = f"blob {st.st_size}\0".encode("utf-8")
                hasher = hashlib.sha1(blob_header)
                bytes_read = 0
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)  # 1 MiB chunks
                        if not chunk:
                            break
                        hasher.update(chunk)
                        bytes_read += len(chunk)

                # Verify we read the expected number of bytes
                if bytes_read != st.st_size:
                    logger.debug("build_tree_manifest: size mismatch for %s: expected %d, got %d", path, st.st_size, bytes_read)
                    skipped.append(f"unreadable:{posix_path}")
                    continue

                blob_hex = hasher.hexdigest()

                # Determine mode
                mode = "100755" if (st.st_mode & 0o111) else "100644"
                files[posix_path] = (mode, blob_hex)

            except (OSError, IOError) as e:
                logger.debug("build_tree_manifest: failed to process %s: %s", path, e)
                skipped.append(f"unreadable:{posix_path}")

        # Determine declared_dirs (default: top-level dirs from files)
        if declared_dirs is None:
            declared_set = set()
            for path_str in files.keys():
                if "/" in path_str:
                    declared_set.add(path_str.split("/")[0])
            declared_dirs_list = sorted(declared_set)
        else:
            declared_dirs_list = sorted(set(declared_dirs))
        # A recorded submodule directory is always scanned for extras, even a top-level one
        # (whose path has no "/" and so contributes no default declared dir) or one the caller omitted.
        declared_dirs_list = sorted({*declared_dirs_list, *submodules})

        # Determine extra_excludes (default: from git config)
        extra_excludes_list: list[str] = []
        if extra_excludes is None:
            try:
                # Try to read .git/info/exclude via git rev-parse --git-path
                result = subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
                    capture_output=True,
                    env=clean_git_env(),
                    timeout=10.0,
                )
                if result.returncode == 0:
                    exclude_relpath = result.stdout.decode("utf-8", errors="replace").strip()
                    # Result is relative to root
                    exclude_file = root / exclude_relpath
                    if exclude_file.exists():
                        with open(exclude_file, "r", encoding="utf-8", errors="replace") as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith("#"):
                                    extra_excludes_list.append(line)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
                logger.debug("build_tree_manifest: failed to read info/exclude: %s", e)

            # Try to read core.excludesFile
            try:
                result = subprocess.run(
                    ["git", "-C", str(root), "config", "core.excludesFile"],
                    capture_output=True,
                    env=clean_git_env(),
                    timeout=10.0,
                )
                if result.returncode == 0:
                    excludes_path_raw = result.stdout.decode("utf-8", errors="replace").strip()
                    if excludes_path_raw:
                        # expanduser handles ~ paths
                        excludes_path = os.path.expanduser(excludes_path_raw)
                        if os.path.isfile(excludes_path):
                            with open(excludes_path, "r", encoding="utf-8", errors="replace") as f:
                                for line in f:
                                    line = line.strip()
                                    if line and not line.startswith("#"):
                                        extra_excludes_list.append(line)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
                logger.debug("build_tree_manifest: failed to read core.excludesFile: %s", e)
        else:
            extra_excludes_list = list(extra_excludes)

        # Check for empty file set before computing tree_id
        if not files:
            logger.warning("build_tree_manifest: resulting file set is empty for %s", root)
            return None

        # Compute matches_commit
        matches_commit = False
        if commit_tree is not None:
            # True iff every manifest entry (gitlinks included, at their pin) equals commit's entry.
            matches_commit = all(
                path in commit_tree and commit_tree[path][1] == blob_hex
                for path, (_mode, blob_hex) in files.items()
            )

        # Compute tree_id
        computed_tree_id = tree_id(files)
        if computed_tree_id == "":
            logger.warning("build_tree_manifest: tree_id path conflict for %s", root)
            return None

        return TreeManifest(
            manifest_version=MANIFEST_VERSION,
            hash_algo=HASH_ALGO,
            commit=commit,
            tree_id=computed_tree_id,
            declared_dirs=tuple(declared_dirs_list),
            matches_commit=matches_commit,
            extra_excludes=tuple(extra_excludes_list),
            files=files,
            skipped=tuple(skipped),
            submodules=submodules,
        )

    except Exception as e:
        logger.warning("build_tree_manifest: unexpected error for %s: %s", root, e)
        return None


def _gitlink_path_is_empty(path: Path) -> bool:
    """True iff ``path`` is absent or an empty real directory (not a symlink, not a file). Never raises."""
    try:
        if not os.path.lexists(path):
            return True
        if os.path.islink(path) or not os.path.isdir(path):
            return False
        with os.scandir(path) as it:
            return next(it, None) is None
    except OSError:
        return False


class BudgetConfigError(ValueError):
    """A verification-budget setting is malformed. Never swallowed into a default."""


def _parse_budget(raw: object, where: str, *, allow_zero: bool = False) -> float:
    """``raw`` as a positive finite number of seconds, else BudgetConfigError naming ``where``.

    ``allow_zero`` admits 0 (an already-exhausted budget) for the explicit argument only.
    """
    if isinstance(raw, bool):
        raise BudgetConfigError(f"{where}: max_seconds must be a number, got {raw!r}")
    try:
        value = float(raw.strip()) if isinstance(raw, str) else float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        raise BudgetConfigError(f"{where}: max_seconds must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise BudgetConfigError(f"{where}: max_seconds must be a positive finite number, got {raw!r}")
    return value


def _budget_from_toml(path: Path, tables: tuple[str, ...], label: str) -> float | None:
    """``max_seconds`` from the nested ``tables`` of TOML file ``path`` (None if absent); malformed raises."""
    try:
        data: Any = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BudgetConfigError(f"malformed {label} {path}: {exc}") from exc
    node = data
    for i, key in enumerate(tables):
        node = node.get(key) if isinstance(node, dict) else None
        if node is None:
            return None
        if not isinstance(node, dict):
            raise BudgetConfigError(f"malformed {label} {path}: [{'.'.join(tables[: i + 1])}] must be a table")
    if not isinstance(node, dict):
        raise BudgetConfigError(f"malformed {label} {path}: [{'.'.join(tables)}] must be a table")
    if "max_seconds" not in node:
        return None
    return _parse_budget(node["max_seconds"], f"{label} {path} [{'.'.join(tables)}]")


def _nearest_pyproject(start: Path) -> Path | None:
    cur = start.resolve()
    for parent in (cur, *cur.parents):
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def resolve_max_seconds(
    root: Path, n_files: int, explicit: float | None = None, *, user_config_file: Path | None = None
) -> tuple[float, str]:
    """Resolve the verification time budget as ``(seconds, source)``.

    Precedence: ``explicit`` > env ``CISTERNAL_PROVENANCE_MAX_SECONDS`` (empty, whitespace or
    ``none`` means "use the default", and later layers are not consulted) >
    ``[tool.cisternal.provenance] max_seconds`` in the nearest ``pyproject.toml`` at or above
    ``root`` > ``[provenance] max_seconds`` in ``${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml``
    > the default: ``clamp(n_files * DEFAULT_SECONDS_PER_FILE, DEFAULT_MAX_SECONDS,
    DEFAULT_MAX_SECONDS_CAP)``. A configured value is used exactly (never scaled or capped).
    Raises BudgetConfigError on a malformed value or file, never falls back silently.
    """
    default = min(max(n_files * DEFAULT_SECONDS_PER_FILE, DEFAULT_MAX_SECONDS), DEFAULT_MAX_SECONDS_CAP)
    default_src = f"default (scaled: {n_files} files -> {default:g}s)"
    if explicit is not None:
        return _parse_budget(explicit, "max_seconds argument", allow_zero=True), "arg"
    raw_env = os.environ.get(MAX_SECONDS_ENV_VAR)
    if raw_env is not None:
        if not raw_env.strip() or raw_env.strip().lower() == "none":
            return default, f"env:{MAX_SECONDS_ENV_VAR} (disabled -> {default_src})"
        return _parse_budget(raw_env, f"env {MAX_SECONDS_ENV_VAR}"), f"env:{MAX_SECONDS_ENV_VAR}"
    pyproject = _nearest_pyproject(Path(root))
    if pyproject is not None:
        value = _budget_from_toml(pyproject, ("tool", "cisternal", "provenance"), "pyproject.toml")
        if value is not None:
            return value, f"pyproject:{pyproject}"
    if user_config_file is not None:
        user_cfg = Path(user_config_file)
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        user_cfg = (Path(xdg) if xdg else Path.home() / ".config") / "cisternal" / "config.toml"
    if user_cfg.is_file():
        value = _budget_from_toml(user_cfg, ("provenance",), "user config")
        if value is not None:
            return value, f"user-config:{user_cfg}"
    return default, default_src


def verify_tree(
    root: Path,
    manifest: TreeManifest,
    *,
    cwd: Path | None = None,
    dirty_content_id: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_seconds: float | None = None,
) -> TreeVerification:
    """Verify a tree manifest against disk (see ``_verify_tree_impl``).

    ``max_seconds=None`` resolves the budget via ``resolve_max_seconds`` (arg > env > pyproject >
    user config > default scaled by file count); the result reports it in ``budget_seconds`` /
    ``budget_source``. A malformed budget setting returns ``verified=False`` with an explicit
    ``error`` and no verification attempt. Never raises.
    """
    try:
        n_files = len(manifest.files) + sum(len(f) for _, f in manifest.submodules.values())
        seconds, source = resolve_max_seconds(Path(root), n_files, max_seconds)
    except Exception as exc:  # noqa: BLE001 - verify_tree never raises; BudgetConfigError is the expected case
        n_seen = len(manifest.files) if isinstance(manifest, TreeManifest) else 0
        kind = "malformed provenance budget" if isinstance(exc, BudgetConfigError) else type(exc).__name__
        return TreeVerification(
            verified=False, n_files=n_seen, n_match=0, mismatched=(), missing=(),
            extra_untracked_under_declared_dirs=(), mode_changed=(), manifest_ok=False,
            extras_ignore_aware=False, tree_id=None, dirty_content_id_consistent=None,
            error=f"{kind}: {exc}",
        )
    result = _verify_tree_impl(
        root, manifest, cwd=cwd, dirty_content_id=dirty_content_id, max_bytes=max_bytes, max_seconds=seconds
    )
    return replace(result, budget_seconds=seconds, budget_source=source)


def _verify_tree_impl(
    root: Path,
    manifest: TreeManifest,
    *,
    cwd: Path | None = None,
    dirty_content_id: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_seconds: float,
) -> TreeVerification:
    """Verify a tree manifest against disk.

    root: The directory to verify (the sidecar's directory).
    manifest: The manifest to verify against.
    cwd: Optional current working directory. If inside root and not under a
         declared dir, its direct files are scanned for extras.
    dirty_content_id: If provided and starts with "tree:", compare against
                      recomputed tree_id.
    max_bytes, max_seconds: Verification budget.

    Never raises. All exceptions are caught and result in verified=False
    with error set.
    """
    root = Path(root)

    try:
        # Step 0: Check for empty manifest
        if not manifest.files:
            return TreeVerification(
                verified=False,
                n_files=0,
                n_match=0,
                mismatched=(),
                missing=(),
                extra_untracked_under_declared_dirs=(),
                mode_changed=(),
                manifest_ok=False,
                extras_ignore_aware=False,
                tree_id=None,
                dirty_content_id_consistent=None,
                error="empty manifest",
            )

        # Step 1: Check manifest_ok
        manifest_ok = (
            manifest.manifest_version == MANIFEST_VERSION
            and manifest.hash_algo == HASH_ALGO
            and tree_id(manifest.files) == manifest.tree_id
            and all(tree_id(sub_files) == sub_tree for sub_tree, sub_files in manifest.submodules.values())
        )

        # Step 2: Verify each file in manifest
        start_time = time.monotonic()

        def _remaining() -> float:
            """Seconds left in max_seconds; the extras phase spends from the same budget."""
            left = max_seconds - (time.monotonic() - start_time)
            if left <= 0:
                raise subprocess.TimeoutExpired("verify_tree", max_seconds)
            return left

        # Work items (path, mode, blob, owner). A populated gitlink directory that the manifest
        # carries submodule files for is expanded into its files (owner = the gitlink path); every
        # other entry, including an absent/empty or undeclared gitlink, is checked as before.
        work: list[tuple[str, str, str, str | None]] = []
        expanded: list[str] = []
        for entry_path in sorted(manifest.files):
            entry_mode, entry_blob = manifest.files[entry_path]
            declared = manifest.submodules.get(entry_path) if entry_mode == GITLINK_MODE else None
            sub_dir = root / entry_path
            if (
                declared is not None
                and declared[1]  # an empty recorded file list vouches for nothing: treat as undeclared
                and not _gitlink_path_is_empty(sub_dir)
                and os.path.isdir(sub_dir)
                and not os.path.islink(sub_dir)
            ):
                expanded.append(entry_path)
                for rel_file in sorted(declared[1]):
                    sub_mode, sub_blob = declared[1][rel_file]
                    work.append((f"{entry_path}/{rel_file}", sub_mode, sub_blob, entry_path))
            else:
                work.append((entry_path, entry_mode, entry_blob, None))

        cumulative_bytes = 0
        n_files = len(work) + len(expanded)  # each expanded gitlink entry counts too, once all its files match
        n_match = 0
        mismatched: list[str] = []
        missing: list[str] = []
        mode_changed: list[str] = []

        recomputed_tree_dict: dict[str, tuple[str, str]] = {}

        for path_str, manifest_mode, manifest_blob, owner in work:
            # Check budget
            if cumulative_bytes > max_bytes:
                return TreeVerification(
                    verified=False,
                    n_files=n_files,
                    n_match=n_match,
                    mismatched=tuple(mismatched),
                    missing=tuple(missing),
                    extra_untracked_under_declared_dirs=(),
                    mode_changed=tuple(mode_changed),
                    manifest_ok=manifest_ok,
                    extras_ignore_aware=False,
                    tree_id=None,
                    dirty_content_id_consistent=None,
                    error=f"budget exceeded: {cumulative_bytes} bytes > {max_bytes}",
                )
            if time.monotonic() - start_time > max_seconds:
                return TreeVerification(
                    verified=False,
                    n_files=n_files,
                    n_match=n_match,
                    mismatched=tuple(mismatched),
                    missing=tuple(missing),
                    extra_untracked_under_declared_dirs=(),
                    mode_changed=tuple(mode_changed),
                    manifest_ok=manifest_ok,
                    extras_ignore_aware=False,
                    tree_id=None,
                    dirty_content_id_consistent=None,
                    error=f"budget exceeded: {time.monotonic() - start_time:.1f}s > {max_seconds}s",
                )

            path = root / path_str

            if manifest_mode == GITLINK_MODE:
                # A submodule pin. There is no .git here to ask for its HEAD (the writer checked
                # that), so verify what can be: nothing unhashed lives at this path. Absent or an
                # empty directory passes; a symlink, a file, or ANY directory content is code the
                # manifest cannot vouch for.
                if _gitlink_path_is_empty(path):
                    n_match += 1
                    recomputed_tree_dict[path_str] = (manifest_mode, manifest_blob)
                else:
                    mismatched.append(path_str)
                continue

            # Check if path exists
            if not os.path.lexists(path):
                missing.append(path_str)
                continue

            try:
                # Read and hash the file
                if os.path.islink(path):
                    link_target_bytes = os.fsencode(os.readlink(path))
                    actual_blob = blob_id(link_target_bytes)
                    actual_mode = "120000"
                else:
                    # Stat the file first to check it's a regular file
                    st = os.stat(path)
                    if not stat.S_ISREG(st.st_mode):
                        return TreeVerification(
                            verified=False,
                            n_files=n_files,
                            n_match=n_match,
                            mismatched=tuple(mismatched),
                            missing=tuple(missing),
                            extra_untracked_under_declared_dirs=(),
                            mode_changed=tuple(mode_changed),
                            manifest_ok=manifest_ok,
                            extras_ignore_aware=False,
                            tree_id=None,
                            dirty_content_id_consistent=None,
                            error=f"not a regular file: {path_str}",
                        )

                    # Hash file with streaming (chunks)
                    blob_header = f"blob {st.st_size}\0".encode("utf-8")
                    hasher = hashlib.sha1(blob_header)
                    bytes_read = 0
                    with open(path, "rb") as f:
                        while True:
                            chunk = f.read(1024 * 1024)  # 1 MiB chunks
                            if not chunk:
                                break
                            hasher.update(chunk)
                            bytes_read += len(chunk)

                    # Verify bytes read equals expected size
                    if bytes_read != st.st_size:
                        mismatched.append(path_str)
                        continue

                    actual_blob = hasher.hexdigest()
                    cumulative_bytes += st.st_size

                    actual_mode = "100755" if (st.st_mode & 0o111) else "100644"

                # Compare blob and mode
                # File-type change (mode 120000 vs 100644/100755) counts as mismatched, not mode_changed
                if actual_mode != manifest_mode:
                    # Different type (symlink vs regular or vice versa) → mismatched
                    if (actual_mode == "120000") != (manifest_mode == "120000"):
                        mismatched.append(path_str)
                    elif actual_blob != manifest_blob:
                        mismatched.append(path_str)
                    else:
                        # Same blob, different mode (exec bit) → mode_changed
                        mode_changed.append(path_str)
                        n_match += 1
                        if owner is None:
                            recomputed_tree_dict[path_str] = (actual_mode, actual_blob)
                elif actual_blob != manifest_blob:
                    mismatched.append(path_str)
                else:
                    n_match += 1
                    if owner is None:
                        recomputed_tree_dict[path_str] = (actual_mode, actual_blob)

            except (OSError, IOError, PermissionError) as e:
                return TreeVerification(
                    verified=False,
                    n_files=n_files,
                    n_match=n_match,
                    mismatched=tuple(mismatched),
                    missing=tuple(missing),
                    extra_untracked_under_declared_dirs=(),
                    mode_changed=tuple(mode_changed),
                    manifest_ok=manifest_ok,
                    extras_ignore_aware=False,
                    tree_id=None,
                    dirty_content_id_consistent=None,
                    error=f"PermissionError or OSError reading {path_str}: {e}",
                )

        # Budget re-check after the final file (the in-loop check runs before each file).
        over_bytes = cumulative_bytes > max_bytes
        elapsed = time.monotonic() - start_time
        if over_bytes or elapsed > max_seconds:
            return TreeVerification(
                verified=False,
                n_files=n_files,
                n_match=n_match,
                mismatched=tuple(mismatched),
                missing=tuple(missing),
                extra_untracked_under_declared_dirs=(),
                mode_changed=tuple(mode_changed),
                manifest_ok=manifest_ok,
                extras_ignore_aware=False,
                tree_id=None,
                dirty_content_id_consistent=None,
                error=(f"budget exceeded: {cumulative_bytes} bytes > {max_bytes}" if over_bytes
                       else f"budget exceeded: {elapsed:.1f}s > {max_seconds}s"),
            )

        # A submodule directory verified by content: every file matched, so the gitlink entry
        # itself is accounted for at its pin (and keeps the recomputed tree_id comparable).
        verified_submodules: list[str] = []
        for owner_path in expanded:
            prefix = owner_path + "/"
            if any(p.startswith(prefix) for p in (*mismatched, *missing)):
                continue
            verified_submodules.append(owner_path)
            n_match += 1
            recomputed_tree_dict[owner_path] = manifest.files[owner_path]

        # Paths the manifest accounts for: its files plus the submodule files it records.
        known_paths = set(manifest.files)
        for owner_path, (_sub_tree, sub_files) in manifest.submodules.items():
            known_paths.update(f"{owner_path}/{rel_file}" for rel_file in sub_files)

        # Step 3: Scan for extras
        # Resolve symlinks in root and cwd before relative_to
        root_resolved = root.resolve()
        cwd_resolved = Path(cwd).resolve() if cwd is not None else None

        scan_dirs_list: list[str] = sorted({*manifest.declared_dirs, *expanded})
        cwd_dir_to_scan: str | None = None

        if cwd_resolved is not None:
            try:
                cwd_rel = cwd_resolved.relative_to(root_resolved)
                if cwd_rel != Path("."):
                    cwd_rel_str = str(cwd_rel).replace(os.sep, "/")
                    # Check if cwd is under a declared dir
                    is_under_declared = any(
                        cwd_rel_str == d or cwd_rel_str.startswith(d + "/")
                        for d in manifest.declared_dirs
                    )
                    if not is_under_declared:
                        cwd_dir_to_scan = cwd_rel_str
            except ValueError:
                # cwd is not inside root
                return TreeVerification(
                    verified=False,
                    n_files=n_files,
                    n_match=n_match,
                    mismatched=tuple(mismatched),
                    missing=tuple(missing),
                    extra_untracked_under_declared_dirs=(),
                    mode_changed=tuple(mode_changed),
                    manifest_ok=manifest_ok,
                    extras_ignore_aware=False,
                    tree_id=None,
                    dirty_content_id_consistent=None,
                    error=f"cwd {cwd} is outside provenance root {root}",
                )

        # Use git to find extras (or fallback to Python walk)
        extras: list[str] = []
        exempt_locks: list[str] = []
        extras_ignore_aware = False

        def _record_extra(rel: str) -> None:
            """The one place an untracked file becomes an extra; bathos run-lock manifests are reported, not counted."""
            (exempt_locks if is_bathos_lock_manifest(rel) else extras).append(rel)

        # If there are no scan dirs and no cwd dir, skip extras scanning
        if not scan_dirs_list and cwd_dir_to_scan is None:
            extras = []
            extras_ignore_aware = True
        else:
            try:
                # Create a temporary empty git repo for running ls-files with custom excludes
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_git_dir = Path(tmpdir) / "x.git"
                    tmp_excludes = Path(tmpdir) / "excludes"

                    try:
                        # Hermetic git init --bare: clean env + no template dir
                        hermetic_env = clean_git_env() | {
                            "GIT_CONFIG_GLOBAL": os.devnull,
                            "GIT_CONFIG_NOSYSTEM": "1",
                        }
                        git_init_result = subprocess.run(
                            ["git", "init", "-q", "--bare", "--template=", str(tmp_git_dir)],
                            capture_output=True,
                            env=hermetic_env,
                            timeout=_remaining(),
                        )
                        if git_init_result.returncode != 0:
                            return TreeVerification(
                                verified=False,
                                n_files=n_files,
                                n_match=n_match,
                                mismatched=tuple(mismatched),
                                missing=tuple(missing),
                                extra_untracked_under_declared_dirs=(),
                                mode_changed=tuple(mode_changed),
                                manifest_ok=manifest_ok,
                                extras_ignore_aware=False,
                                tree_id=tree_id(recomputed_tree_dict) if not missing else None,
                                dirty_content_id_consistent=None,
                                error=f"git init --bare failed: {git_init_result.stderr.decode('utf-8', errors='replace').strip()[:100]}",
                            )

                        # Write extra_excludes and BUILTIN_EXTRA_EXCLUDES to temp file
                        with open(tmp_excludes, "w") as f:
                            # Write builtin excludes first
                            for pattern in BUILTIN_EXTRA_EXCLUDES:
                                f.write(pattern + "\n")
                            # Write manifest excludes
                            for pattern in manifest.extra_excludes:
                                f.write(pattern + "\n")
                            # Write gitlink exclusions
                            for skipped_entry in manifest.skipped:
                                # gitlink: and the gitlink-<reason>: kinds; each already fails closed via skipped.
                                if skipped_entry.startswith("gitlink") and ":" in skipped_entry:
                                    gitlink_path = skipped_entry.split(":", 1)[1].strip("/")  # drop prefix and slashes
                                    # Exclude the directory and everything under it
                                    f.write(f"/{gitlink_path}/\n")
                            # Pinned (160000) paths are deliberately NOT excluded here: the pattern would be an
                            # unescaped gitignore line, so a path with glob characters or a newline could hide
                            # unrelated extras, and these entries do not fail closed through `skipped`. Their
                            # emptiness is checked per entry above; content under one is reported, not hidden.

                        # Run git ls-files with custom excludes for declared dirs (recursive)
                        env = clean_git_env()
                        env["GIT_CONFIG_GLOBAL"] = os.devnull
                        env["GIT_CONFIG_NOSYSTEM"] = "1"

                        # Scan declared dirs recursively
                        if scan_dirs_list:
                            git_args = [
                                "git",
                                "-c", "safe.directory=*",
                                "-c", f"core.excludesFile={tmp_excludes}",
                                f"--git-dir={tmp_git_dir}",
                                f"--work-tree={root_resolved}",
                                "ls-files", "-z", "-o", "--exclude-standard",
                            ]
                            git_args.extend(["--"] + scan_dirs_list)

                            result = subprocess.run(
                                git_args,
                                capture_output=True,
                                env=env,
                                timeout=_remaining(),
                            )

                            if result.returncode == 0:
                                extras_ignore_aware = True
                                listed_files = result.stdout.decode("utf-8", errors="replace").split("\0")
                                for f in listed_files:
                                    if f and f != PROVENANCE_FILENAME and f not in known_paths:
                                        _record_extra(f)
                            else:
                                # git failed
                                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                                first_line = stderr.split("\n")[0][:100]
                                return TreeVerification(
                                    verified=False,
                                    n_files=n_files,
                                    n_match=n_match,
                                    mismatched=tuple(mismatched),
                                    missing=tuple(missing),
                                    extra_untracked_under_declared_dirs=tuple(extras),
                                    mode_changed=tuple(mode_changed),
                                    manifest_ok=manifest_ok,
                                    extras_ignore_aware=False,
                                    tree_id=tree_id(recomputed_tree_dict) if not missing else None,
                                    dirty_content_id_consistent=None,
                                    error=f"git ls-files failed: {first_line}",
                                )
                        else:
                            extras_ignore_aware = True

                        # Strict pass over every submodule directory verified by content: NO ignore
                        # rules, so a .gitignore the submodule itself ships (e.g. `*.so`, `*.pyc`)
                        # cannot hide unhashed files. Only interpreter bytecode under __pycache__
                        # (the BUILTIN exemption) and bathos run-lock manifests are exempt.
                        if expanded:
                            result_strict = subprocess.run(
                                [
                                    "git",
                                    "-c", "safe.directory=*",
                                    f"--git-dir={tmp_git_dir}",
                                    f"--work-tree={root_resolved}",
                                    "ls-files", "-z", "-o",
                                    "--", *expanded,
                                ],
                                capture_output=True,
                                env=env,
                                timeout=_remaining(),
                            )
                            if result_strict.returncode != 0:
                                first_line = result_strict.stderr.decode("utf-8", errors="replace").strip().split("\n")[0][:100]
                                return TreeVerification(
                                    verified=False,
                                    n_files=n_files,
                                    n_match=n_match,
                                    mismatched=tuple(mismatched),
                                    missing=tuple(missing),
                                    extra_untracked_under_declared_dirs=tuple(extras),
                                    mode_changed=tuple(mode_changed),
                                    manifest_ok=manifest_ok,
                                    extras_ignore_aware=False,
                                    tree_id=tree_id(recomputed_tree_dict) if not missing else None,
                                    dirty_content_id_consistent=None,
                                    error=f"git ls-files failed (submodule scan): {first_line}",
                                )
                            for f in result_strict.stdout.decode("utf-8", errors="replace").split("\0"):
                                if (
                                    f
                                    and f not in known_paths
                                    and f not in extras
                                    and "__pycache__" not in f.split("/")
                                ):
                                    _record_extra(f)

                        # Scan cwd dir non-recursively
                        if cwd_dir_to_scan is not None:
                            git_args_cwd = [
                                "git",
                                "-c", "safe.directory=*",
                                "-c", f"core.excludesFile={tmp_excludes}",
                                f"--git-dir={tmp_git_dir}",
                                f"--work-tree={root_resolved}",
                                "ls-files", "-z", "-o", "--exclude-standard",
                                "--", cwd_dir_to_scan,
                            ]

                            result_cwd = subprocess.run(
                                git_args_cwd,
                                capture_output=True,
                                env=env,
                                timeout=_remaining(),
                            )

                            if result_cwd.returncode == 0:
                                listed_files = result_cwd.stdout.decode("utf-8", errors="replace").split("\0")
                                for f in listed_files:
                                    if f and f != PROVENANCE_FILENAME and f not in known_paths:
                                        # Only add if it's a direct child (no "/" after the cwd prefix)
                                        relpath = f[len(cwd_dir_to_scan) + 1:] if f.startswith(cwd_dir_to_scan + "/") else ""
                                        if relpath and "/" not in relpath:
                                            _record_extra(f)
                            else:
                                # git failed on cwd; fail the verification
                                stderr = result_cwd.stderr.decode("utf-8", errors="replace").strip()
                                first_line = stderr.split("\n")[0][:100]
                                return TreeVerification(
                                    verified=False,
                                    n_files=n_files,
                                    n_match=n_match,
                                    mismatched=tuple(mismatched),
                                    missing=tuple(missing),
                                    extra_untracked_under_declared_dirs=tuple(extras),
                                    mode_changed=tuple(mode_changed),
                                    manifest_ok=manifest_ok,
                                    extras_ignore_aware=False,
                                    tree_id=tree_id(recomputed_tree_dict) if not missing else None,
                                    dirty_content_id_consistent=None,
                                    error=f"git ls-files failed: {first_line}",
                                )

                    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                        # git not found or timed out; check if it's a timeout during extras scan
                        if isinstance(e, subprocess.TimeoutExpired):
                            # Extras scan timed out
                            return TreeVerification(
                                verified=False,
                                n_files=n_files,
                                n_match=n_match,
                                mismatched=tuple(mismatched),
                                missing=tuple(missing),
                                extra_untracked_under_declared_dirs=(),
                                mode_changed=tuple(mode_changed),
                                manifest_ok=manifest_ok,
                                extras_ignore_aware=False,
                                tree_id=tree_id(recomputed_tree_dict) if not missing else None,
                                dirty_content_id_consistent=None,
                                error="budget exceeded: extras scan",
                            )
                        # git not found; fallback to Python walk
                        extras_ignore_aware = False
                        # Walk declared dirs recursively
                        for scan_dir in scan_dirs_list:
                            scan_path = root_resolved / scan_dir
                            if not scan_path.is_dir():
                                continue
                            for dirpath, dirnames, filenames in os.walk(scan_path):
                                _remaining()  # bounded by max_seconds; raises -> verified False
                                # Prune ignored directories (including BUILTIN_EXTRA_EXCLUDES)
                                dirnames[:] = [
                                    d for d in dirnames
                                    if d not in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ipynb_checkpoints"}
                                    and not d.endswith(".egg-info")
                                ]
                                for fname in filenames:
                                    full_path = Path(dirpath) / fname
                                    relpath = full_path.relative_to(root_resolved)
                                    relpath_str = str(relpath).replace(os.sep, "/")
                                    if relpath_str not in known_paths and relpath_str != PROVENANCE_FILENAME:
                                        _record_extra(relpath_str)
                        # Scan cwd dir non-recursively
                        if cwd_dir_to_scan is not None:
                            cwd_path = root_resolved / cwd_dir_to_scan
                            if cwd_path.is_dir():
                                for entry in os.scandir(cwd_path):
                                    if entry.is_file(follow_symlinks=False):
                                        relpath = Path(entry.path).relative_to(root_resolved)
                                        relpath_str = str(relpath).replace(os.sep, "/")
                                        if relpath_str not in known_paths and relpath_str != PROVENANCE_FILENAME:
                                            _record_extra(relpath_str)

            except Exception as e:
                # Any exception in extras scanning fails verification
                return TreeVerification(
                    verified=False,
                    n_files=n_files,
                    n_match=n_match,
                    mismatched=tuple(mismatched),
                    missing=tuple(missing),
                    extra_untracked_under_declared_dirs=tuple(extras),
                    mode_changed=tuple(mode_changed),
                    manifest_ok=manifest_ok,
                    extras_ignore_aware=False,
                    tree_id=tree_id(recomputed_tree_dict) if not missing else None,
                    dirty_content_id_consistent=None,
                    error=f"Error scanning for extras: {type(e).__name__}: {e}",
                )

        # Step 4: Recompute tree_id
        recomputed_tree_id = tree_id(recomputed_tree_dict) if not missing else None

        # Step 5: dirty_content_id consistency
        dirty_content_id_consistent: bool | None = None
        if dirty_content_id is not None:
            if dirty_content_id.startswith("tree:") and recomputed_tree_id is not None:
                expected_id = "tree:" + recomputed_tree_id
                dirty_content_id_consistent = (dirty_content_id == expected_id)
            # else: informational only, no verdict

        exempt_sorted = tuple(sorted(set(exempt_locks)))
        if exempt_sorted:
            # The names are on TreeVerification, which downstream provenance records do not carry; log them so the exemption is visible.
            logger.info(
                "verify_tree: %d bathos run-lock manifest(s) under %s exempted from the extras check: %s",
                len(exempt_sorted),
                root,
                ", ".join(exempt_sorted),
            )

        # Step 6: Determine verified
        verified = (
            manifest_ok
            and not mismatched
            and not missing
            and not extras
            and not manifest.skipped
        )

        return TreeVerification(
            verified=verified,
            n_files=n_files,
            n_match=n_match,
            mismatched=tuple(mismatched),
            missing=tuple(missing),
            extra_untracked_under_declared_dirs=tuple(extras),
            mode_changed=tuple(mode_changed),
            manifest_ok=manifest_ok,
            extras_ignore_aware=extras_ignore_aware,
            tree_id=recomputed_tree_id,
            dirty_content_id_consistent=dirty_content_id_consistent,
            error=None,
            exempt_lock_manifests=exempt_sorted,
            verified_submodules=tuple(verified_submodules),
        )

    except Exception as e:
        # Catch-all for any unexpected error
        return TreeVerification(
            verified=False,
            n_files=len(manifest.files),
            n_match=0,
            mismatched=(),
            missing=(),
            extra_untracked_under_declared_dirs=(),
            mode_changed=(),
            manifest_ok=False,
            extras_ignore_aware=False,
            tree_id=None,
            dirty_content_id_consistent=None,
            error=f"{type(e).__name__}: {e}",
        )
