"""Schema and (de)serialization tests for cisternal.provenance.record."""

from __future__ import annotations

import json

from cisternal.provenance.record import (
    ProvenanceRecord,
    from_env,
    read_state_record,
    to_env,
    to_json_bytes,
    write_state_record,
)

_BASE_KWARGS = dict(
    schema_version=1,
    provenance_status="git",
    git_sha="a" * 40,
    git_branch="main",
    git_dirty=False,
    dirty_content_id=None,
    capture_stage="push",
    sync_state="verified",
    computed_at="2026-08-27T00:00:00Z",
    provenance_root="/remote/proj",
    remote="engaging",
    project="proj",
)


def test_json_key_set_is_exactly_schema_v1():
    record = ProvenanceRecord(**_BASE_KWARGS)
    payload = json.loads(to_json_bytes(record).decode())
    assert set(payload.keys()) == {
        "schema_version", "provenance_status", "git_sha", "git_branch", "git_dirty",
        "dirty_content_id", "capture_stage", "sync_state", "computed_at",
        "provenance_root", "remote", "project", "worktree", "myxcel_version",
    }


def test_to_json_bytes_sorted_keys_and_trailing_newline():
    record = ProvenanceRecord(**_BASE_KWARGS)
    raw = to_json_bytes(record)
    assert raw.endswith(b"\n")
    text = raw.decode()
    keys = list(json.loads(text).keys())
    assert keys == sorted(keys)


def test_to_env_names_and_null_mapping():
    record = ProvenanceRecord(**{**_BASE_KWARGS, "git_dirty": None, "dirty_content_id": None})
    env = to_env(record)
    assert env["MYXCEL_GIT_SHA"] == "a" * 40
    assert env["MYXCEL_GIT_DIRTY"] == ""
    assert env["MYXCEL_GIT_DIRTY_CONTENT_ID"] == ""
    assert env["MYXCEL_PROVENANCE_SCHEMA"] == "1"


def test_to_env_bool_true_false():
    dirty_true = to_env(ProvenanceRecord(**{**_BASE_KWARGS, "git_dirty": True}))
    dirty_false = to_env(ProvenanceRecord(**{**_BASE_KWARGS, "git_dirty": False}))
    assert dirty_true["MYXCEL_GIT_DIRTY"] == "1"
    assert dirty_false["MYXCEL_GIT_DIRTY"] == "0"


def test_from_env_roundtrip():
    record = ProvenanceRecord(**{**_BASE_KWARGS, "git_dirty": True, "dirty_content_id": "tree:" + "b" * 40})
    env = to_env(record)
    recovered = from_env(env)
    assert recovered is not None
    assert recovered.git_sha == record.git_sha
    assert recovered.git_dirty is True
    assert recovered.dirty_content_id == record.dirty_content_id
    assert recovered.provenance_status == "git"


def test_from_env_absent_schema_returns_none():
    assert from_env({}) is None


def test_from_env_unrecognized_status_returns_none():
    env = to_env(ProvenanceRecord(**_BASE_KWARGS))
    env["MYXCEL_PROVENANCE_STATUS"] = "bogus"
    assert from_env(env) is None


def test_write_and_read_state_record_roundtrip(tmp_path):
    record = ProvenanceRecord(**{**_BASE_KWARGS, "worktree": "wt-123"})
    path = tmp_path / "state.json"
    write_state_record(path, record)
    recovered = read_state_record(path)
    assert recovered is not None
    assert recovered.git_sha == record.git_sha
    assert recovered.worktree == "wt-123"


def test_read_state_record_missing_file_returns_none(tmp_path):
    assert read_state_record(tmp_path / "nope.json") is None


def test_read_state_record_rejects_missing_provenance_status(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 1}))
    assert read_state_record(path) is None


def test_read_state_record_rejects_non_int_schema_version(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": "1", "provenance_status": "git"}))
    assert read_state_record(path) is None


def test_read_state_record_accepts_future_schema_version(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 99, "provenance_status": "git", "git_sha": "x"}))
    recovered = read_state_record(path)
    assert recovered is not None
    assert recovered.schema_version == 99
    assert recovered.git_sha == "x"


def test_write_state_record_is_atomic_no_tmp_file_left(tmp_path):
    record = ProvenanceRecord(**_BASE_KWARGS)
    path = tmp_path / "nested" / "state.json"
    write_state_record(path, record)
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()


def test_v1_record_without_tree_manifest_omits_key_for_compatibility():
    """v1 record (tree_manifest=None) serializes without a "tree_manifest" key."""
    record = ProvenanceRecord(**{**_BASE_KWARGS, "tree_manifest": None})
    payload = to_json_bytes(record)
    data = json.loads(payload.decode())
    assert "tree_manifest" not in data
    # Ensure it still has all the expected v1 keys
    assert "schema_version" in data
    assert "provenance_status" in data


def test_v2_round_trip_with_tree_manifest(tmp_path):
    """v2 record with tree_manifest can round-trip through write/read."""
    from cisternal.provenance.record import MAX_KNOWN_SCHEMA_VERSION

    manifest_dict = {"manifest_version": 1, "files": {}}
    record = ProvenanceRecord(
        **{**_BASE_KWARGS, "schema_version": 2, "tree_manifest": manifest_dict}
    )
    path = tmp_path / "v2.json"
    write_state_record(path, record)
    recovered = read_state_record(path)

    assert recovered is not None
    assert recovered.schema_version == 2
    assert recovered.tree_manifest == manifest_dict
    assert recovered.tree_manifest is not None


def test_v2_record_with_tree_manifest_includes_key():
    """v2 record with tree_manifest includes the key in JSON."""
    manifest_dict = {"manifest_version": 1, "files": {}}
    record = ProvenanceRecord(
        **{**_BASE_KWARGS, "schema_version": 2, "tree_manifest": manifest_dict}
    )
    payload = to_json_bytes(record)
    data = json.loads(payload.decode())
    assert "tree_manifest" in data
    assert data["tree_manifest"] == manifest_dict


def test_to_env_v2_record_ignores_tree_manifest():
    """to_env(v2 record) has no MANIFEST keys and equals to_env(same without tree_manifest)."""
    manifest_dict = {"manifest_version": 1, "files": {}}
    v2_with_manifest = ProvenanceRecord(
        **{**_BASE_KWARGS, "schema_version": 2, "tree_manifest": manifest_dict}
    )
    v2_without_manifest = ProvenanceRecord(
        **{**_BASE_KWARGS, "schema_version": 2, "tree_manifest": None}
    )

    env_with = to_env(v2_with_manifest)
    env_without = to_env(v2_without_manifest)

    # No MANIFEST keys
    assert not any("MANIFEST" in k for k in env_with.keys())
    # Both should be equal (tree_manifest is not serialized to env)
    assert env_with == env_without


def test_read_state_record_ignores_bad_tree_manifest(tmp_path):
    """read_state_record with "tree_manifest": "garbage" -> record.tree_manifest is None."""
    data = {**_BASE_KWARGS, "schema_version": 2, "tree_manifest": "garbage"}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))

    recovered = read_state_record(path)
    assert recovered is not None
    assert recovered.tree_manifest is None


def test_read_sidecar_from_directory(tmp_path):
    """read_sidecar(directory) reads PROVENANCE_FILENAME from that directory."""
    from cisternal.provenance.record import read_sidecar, PROVENANCE_FILENAME

    record = ProvenanceRecord(**_BASE_KWARGS)
    record_path = tmp_path / PROVENANCE_FILENAME
    write_state_record(record_path, record)

    recovered = read_sidecar(tmp_path)
    assert recovered is not None
    assert recovered.git_sha == record.git_sha


def test_read_sidecar_from_file(tmp_path):
    """read_sidecar(file) reads from that file directly."""
    from cisternal.provenance.record import read_sidecar

    record = ProvenanceRecord(**_BASE_KWARGS)
    record_path = tmp_path / "custom.json"
    write_state_record(record_path, record)

    recovered = read_sidecar(record_path)
    assert recovered is not None
    assert recovered.git_sha == record.git_sha


def test_read_sidecar_missing_returns_none(tmp_path):
    """read_sidecar on missing file/dir returns None."""
    from cisternal.provenance.record import read_sidecar

    missing_dir = tmp_path / "nope"
    assert read_sidecar(missing_dir) is None

    missing_file = tmp_path / "nope.json"
    assert read_sidecar(missing_file) is None
