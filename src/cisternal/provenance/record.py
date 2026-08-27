"""Versioned git-provenance record: schema, (de)serialization, and local state storage.

`ProvenanceRecord` is the schema shared by every consumer in the Praxia tool
family that needs to know "what code produced this" -- originally designed
and shipped in myxcel (see myxcel's
`.praxia/docs/specs/260820_bathos-git-provenance-sidecar-spec.md`) as the
handoff between a push-time capture (myxcel, this record's writer) and a
run-time reader with no live `.git` to inspect (bathos, via `channels.py` in
this package). Moved here so writer and reader share one schema instead of
two independently-maintained copies of the same contract -- the myxcel spec's
own pre-mortem flagged silent schema drift between the two as the most likely
long-term failure mode of the split-implementation version.

`ProvenanceRecord` is deliberately mutable (unlike most of cisternal's other
dataclasses): `resolve_submit_provenance`-style callers use
`dataclasses.replace()` to derive a submit-time record from a push-time one
while only changing `capture_stage`/`sync_state`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

PROVENANCE_FILENAME = ".myxcel_provenance.json"

_VALID_PROVENANCE_STATUSES = frozenset({"git", "nogit", "unavailable"})


@dataclass
class ProvenanceRecord:
    """Schema v1 provenance record, used identically by sidecar JSON and env vars."""

    schema_version: int
    provenance_status: Literal["git", "nogit", "unavailable"]
    git_sha: str | None
    git_branch: str | None
    git_dirty: bool | None
    dirty_content_id: str | None
    capture_stage: Literal["push", "submit"]
    sync_state: Literal["verified", "drifted", "unverified"]
    computed_at: str  # RFC 3339 UTC
    provenance_root: str  # absolute remote root
    remote: str  # myxcel profile name
    project: str
    worktree: str | None = None
    # Left to the caller to populate (e.g. `importlib.metadata.version("myxcel")`
    # in myxcel's writer path) rather than defaulted here -- this module is
    # shared by bathos/naurmalade too, neither of which can assume "myxcel"
    # is installed to compute a package-specific default.
    myxcel_version: str = ""


def to_json_bytes(record: ProvenanceRecord) -> bytes:
    """Serialize record to JSON with sorted keys and trailing newline."""
    record_dict = asdict(record)
    json_str = json.dumps(record_dict, sort_keys=True, separators=(",", ":"))
    return (json_str + "\n").encode("utf-8")


def _format_env_value(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "1" if val else "0"
    return str(val)


def to_env(record: ProvenanceRecord) -> dict[str, str]:
    """Flatten record to MYXCEL_* environment variables.

    Empty string denotes JSON null; booleans become "1" or "0". Variable
    names are kept exactly as myxcel originally defined them (not renamed to
    a generic prefix) since bathos's channel reader and every job env this
    ends up in already depend on this exact vocabulary.
    """
    return {
        "MYXCEL_PROVENANCE_SCHEMA": str(record.schema_version),
        "MYXCEL_PROVENANCE_STATUS": record.provenance_status,
        "MYXCEL_GIT_SHA": _format_env_value(record.git_sha),
        "MYXCEL_GIT_BRANCH": _format_env_value(record.git_branch),
        "MYXCEL_GIT_DIRTY": _format_env_value(record.git_dirty),
        "MYXCEL_GIT_DIRTY_CONTENT_ID": _format_env_value(record.dirty_content_id),
        "MYXCEL_PROVENANCE_STAGE": record.capture_stage,
        "MYXCEL_PROVENANCE_SYNC_STATE": record.sync_state,
        "MYXCEL_PROVENANCE_COMPUTED_AT": record.computed_at,
        "MYXCEL_PROVENANCE_ROOT": record.provenance_root,
        # Debugging aid only, not consumed by capture_git_state's precedence logic --
        # a remote (posix) path, so joined with "/" rather than os.path.join.
        "MYXCEL_PROVENANCE_FILE": f"{record.provenance_root.rstrip('/')}/{PROVENANCE_FILENAME}",
    }


def from_env(env: dict[str, str] | None = None) -> ProvenanceRecord | None:
    """Reconstruct a record from MYXCEL_* environment variables.

    Returns None if the schema-active sentinel (`MYXCEL_PROVENANCE_SCHEMA`) is
    absent, or if the record fails the same validity checks `read_state_record`
    applies (unrecognised `provenance_status`, non-integer `schema_version`).
    This is the channel-reading half that `bathos.channels._env_channel` used
    to hand-implement independently of myxcel's writer -- centralizing it here
    is what actually closes the schema-drift risk, not just moving the
    dataclass.
    """
    src = env if env is not None else os.environ
    if "MYXCEL_PROVENANCE_SCHEMA" not in src:
        return None

    try:
        schema_version = int(src["MYXCEL_PROVENANCE_SCHEMA"])
    except (KeyError, ValueError):
        return None

    status = src.get("MYXCEL_PROVENANCE_STATUS", "")
    if status not in _VALID_PROVENANCE_STATUSES:
        return None

    capture_stage = src.get("MYXCEL_PROVENANCE_STAGE", "push")
    if capture_stage not in ("push", "submit"):
        return None

    sync_state = src.get("MYXCEL_PROVENANCE_SYNC_STATE", "unverified")
    if sync_state not in ("verified", "drifted", "unverified"):
        return None

    def _opt(name: str) -> str | None:
        v = src.get(name, "")
        return v or None

    dirty_raw = src.get("MYXCEL_GIT_DIRTY", "")
    git_dirty: bool | None = {"1": True, "0": False, "": None}.get(dirty_raw)

    return ProvenanceRecord(
        schema_version=schema_version,
        # Runtime-validated against _VALID_PROVENANCE_STATUSES / the literal
        # tuples above -- cast rather than restructuring as if/elif chains,
        # since the validation already happened and a checker can't narrow
        # a `str` via frozenset/tuple membership on its own.
        provenance_status=cast(Literal["git", "nogit", "unavailable"], status),
        git_sha=_opt("MYXCEL_GIT_SHA"),
        git_branch=_opt("MYXCEL_GIT_BRANCH"),
        git_dirty=git_dirty,
        dirty_content_id=_opt("MYXCEL_GIT_DIRTY_CONTENT_ID"),
        capture_stage=cast(Literal["push", "submit"], capture_stage),
        sync_state=cast(Literal["verified", "drifted", "unverified"], sync_state),
        computed_at=src.get("MYXCEL_PROVENANCE_COMPUTED_AT", ""),
        provenance_root=src.get("MYXCEL_PROVENANCE_ROOT", ""),
        remote="",
        project="",
        worktree=None,
    )


def state_record_path(remote: str, project: str, worktree: str | None = None) -> Path:
    """Return the path to the local state record for this (remote, project[, worktree])."""
    base_dir = Path.home() / ".local" / "share" / "myxcel" / "provenance" / remote / project
    if worktree is not None:
        return base_dir / f"wt-{worktree}.json"
    return base_dir / "state.json"


def write_state_record(path: Path, record: ProvenanceRecord) -> None:
    """Write the record to path atomically via tmp-file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = to_json_bytes(record)
    tmp_path = path.with_suffix(".json.tmp")

    try:
        tmp_path.write_bytes(payload)
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_state_record(path: Path) -> ProvenanceRecord | None:
    """Parse the state record from path, returning None on parse failure.

    Tolerant of forward compatibility: accepts schema_version > current, but
    rejects if provenance_status is missing/unrecognized or schema_version is
    absent/non-integer.
    """
    if not path.exists():
        return None

    try:
        payload = path.read_bytes()
        data = json.loads(payload.decode("utf-8"))

        if "provenance_status" not in data:
            return None

        schema_version = data.get("schema_version")
        if not isinstance(schema_version, int):
            return None

        provenance_status = data.get("provenance_status")
        if provenance_status not in _VALID_PROVENANCE_STATUSES:
            return None

        return ProvenanceRecord(
            schema_version=schema_version,
            provenance_status=provenance_status,
            git_sha=data.get("git_sha"),
            git_branch=data.get("git_branch"),
            git_dirty=data.get("git_dirty"),
            dirty_content_id=data.get("dirty_content_id"),
            capture_stage=data.get("capture_stage", "push"),
            sync_state=data.get("sync_state", "verified"),
            computed_at=data.get("computed_at", ""),
            provenance_root=data.get("provenance_root", ""),
            remote=data.get("remote", ""),
            project=data.get("project", ""),
            worktree=data.get("worktree"),
            myxcel_version=data.get("myxcel_version", ""),
        )
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        return None
