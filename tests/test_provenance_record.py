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
