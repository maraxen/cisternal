"""Tests for AC-M3-7 — write_bundle dry_run and write semantics.

AC-M3-7: write_bundle(dry_run=True) writes nothing + returns per-file content_sha256;
          dry_run=False writes all; empty input safe.
"""

from __future__ import annotations

import hashlib

import pytest

from cisterna.export.write import write_bundle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    """SHA-256 hex digest of UTF-8 encoded text."""
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# AC-M3-7: dry_run=True — writes nothing; returns content_sha256
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path: pytest.TempPathFactory) -> None:
    """dry_run=True must not write any file to disk."""
    files = {
        ".claude-plugin/plugin.json": '{"name":"test"}',
        ".claude-plugin/provenance.json": '{"sha256":"abc"}',
    }
    result = write_bundle(files, tmp_path, dry_run=True)  # type: ignore[arg-type]

    # No file should exist.
    all_files = list(tmp_path.rglob("*"))  # type: ignore[union-attr]
    assert all_files == [], f"dry_run=True must write nothing; found: {all_files}"
    assert result.dry_run is True


def test_dry_run_returns_content_sha256_per_file(tmp_path: pytest.TempPathFactory) -> None:
    """dry_run=True returns WriteResult with per-file content_sha256."""
    content_a = '{"name":"myapp","version":"1.0.0"}'
    content_b = '{"sha256":"deadbeef"}'
    files = {
        ".claude-plugin/plugin.json": content_a,
        ".claude-plugin/cisterna-provenance.json": content_b,
    }
    result = write_bundle(files, tmp_path, dry_run=True)  # type: ignore[arg-type]

    result_dict = dict(result.files)
    assert result_dict[".claude-plugin/plugin.json"] == _sha256(content_a)
    assert result_dict[".claude-plugin/cisterna-provenance.json"] == _sha256(content_b)


def test_dry_run_content_sha256_distinct_from_payload_repr(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """content_sha256 is SHA-256(file_bytes), not SHA-256(repr(content)) (B2)."""
    content = "hello world\n"
    files = {"test.txt": content}
    result = write_bundle(files, tmp_path, dry_run=True)  # type: ignore[arg-type]

    expected = _sha256(content)
    result_dict = dict(result.files)
    assert result_dict["test.txt"] == expected


# ---------------------------------------------------------------------------
# AC-M3-7: dry_run=False — writes all files
# ---------------------------------------------------------------------------


def test_write_creates_files_on_disk(tmp_path: pytest.TempPathFactory) -> None:
    """dry_run=False writes each file to disk under out."""
    content_plugin = '{"name":"written","version":"0.1.0"}'
    content_sidecar = '{"sha256":"cafebabe"}'
    files = {
        ".claude-plugin/plugin.json": content_plugin,
        ".claude-plugin/cisterna-provenance.json": content_sidecar,
    }
    result = write_bundle(files, tmp_path, dry_run=False)  # type: ignore[arg-type]

    plugin_file = tmp_path / ".claude-plugin" / "plugin.json"  # type: ignore[operator]
    sidecar_file = tmp_path / ".claude-plugin" / "cisterna-provenance.json"  # type: ignore[operator]

    assert plugin_file.exists(), "plugin.json must be written to disk"
    assert sidecar_file.exists(), "cisterna-provenance.json must be written to disk"

    assert plugin_file.read_text(encoding="utf-8") == content_plugin
    assert sidecar_file.read_text(encoding="utf-8") == content_sidecar
    assert result.dry_run is False


def test_write_creates_parent_directories(tmp_path: pytest.TempPathFactory) -> None:
    """write_bundle must create intermediate parent directories (mkdir -p semantics)."""
    files = {
        "deep/nested/dir/output.json": '{"ok":true}',
    }
    write_bundle(files, tmp_path, dry_run=False)  # type: ignore[arg-type]

    out_file = tmp_path / "deep" / "nested" / "dir" / "output.json"  # type: ignore[operator]
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == '{"ok":true}'


def test_write_returns_content_sha256_for_written_files(tmp_path: pytest.TempPathFactory) -> None:
    """dry_run=False also returns WriteResult with correct content_sha256 per file."""
    content = '{"name":"hash_check"}'
    files = {"plugin.json": content}
    result = write_bundle(files, tmp_path, dry_run=False)  # type: ignore[arg-type]

    result_dict = dict(result.files)
    assert result_dict["plugin.json"] == _sha256(content)


# ---------------------------------------------------------------------------
# AC-M3-7: empty input is safe
# ---------------------------------------------------------------------------


def test_empty_files_dict_dry_run_safe(tmp_path: pytest.TempPathFactory) -> None:
    """Empty files dict with dry_run=True returns empty WriteResult without error."""
    result = write_bundle({}, tmp_path, dry_run=True)  # type: ignore[arg-type]

    assert result.files == ()
    assert result.dry_run is True


def test_empty_files_dict_write_safe(tmp_path: pytest.TempPathFactory) -> None:
    """Empty files dict with dry_run=False returns empty WriteResult without error."""
    result = write_bundle({}, tmp_path, dry_run=False)  # type: ignore[arg-type]

    all_files = list(tmp_path.rglob("*"))  # type: ignore[union-attr]
    assert all_files == [], f"No files should be written for empty input; found: {all_files}"
    assert result.files == ()
    assert result.dry_run is False


# ---------------------------------------------------------------------------
# WriteResult shape
# ---------------------------------------------------------------------------


def test_write_result_is_frozen_dataclass(tmp_path: pytest.TempPathFactory) -> None:
    """WriteResult must be a frozen dataclass (immutable)."""
    result = write_bundle({"a.txt": "hello"}, tmp_path, dry_run=True)  # type: ignore[arg-type]
    with pytest.raises((AttributeError, TypeError)):
        result.dry_run = False  # type: ignore[misc]


def test_write_result_files_is_tuple(tmp_path: pytest.TempPathFactory) -> None:
    """WriteResult.files must be a tuple (not list)."""
    result = write_bundle({"a.txt": "content"}, tmp_path, dry_run=True)  # type: ignore[arg-type]
    assert isinstance(result.files, tuple)


# ---------------------------------------------------------------------------
# never-raise: write_bundle must not raise on I/O failure (audit finding)
# ---------------------------------------------------------------------------


def test_write_bundle_never_raises_on_io_failure(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """write_bundle must not raise when write_text raises OSError.

    Monkeypatches pathlib.Path.write_text to raise OSError on every call.
    Asserts the function returns a WriteResult (no exception) and that a
    WARNING was emitted via the cisterna.export logger naming the failed path.
    content_sha256 is still included in the result (hash is content-based,
    independent of write success).
    """
    import logging
    import pathlib

    from cisterna.export.write import WriteResult

    def _raise_oserror(self: pathlib.Path, *args: object, **kwargs: object) -> None:  # noqa: ARG001
        raise OSError("injected permission denied")

    monkeypatch.setattr(pathlib.Path, "write_text", _raise_oserror)

    with caplog.at_level(logging.WARNING, logger="cisterna.export"):
        result = write_bundle({"a/b.txt": "x"}, tmp_path, dry_run=False)  # type: ignore[arg-type]

    # Must return a WriteResult — no exception propagated.
    assert isinstance(result, WriteResult)
    assert result.dry_run is False

    # content_sha256 is still computed regardless of write failure.
    assert len(result.files) == 1
    rel, sha = result.files[0]
    assert rel == "a/b.txt"
    assert sha == _sha256("x")

    # A WARNING must have been logged naming the failed path.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected at least one WARNING from cisterna.export"
    assert any("a/b.txt" in r.message or "b.txt" in r.message for r in warnings), (
        f"WARNING did not mention the failed path; got: {[r.message for r in warnings]}"
    )
