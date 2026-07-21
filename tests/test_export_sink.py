"""Tests for AC-M33b-2 — MemoryWriterSink capture and dry_run semantics."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cisternal.export.sink import MemoryWriterSink


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_memory_writer_sink_captures_files() -> None:
    """dry_run=False stores a copy of the input file dict in captured."""
    sink = MemoryWriterSink()
    files = {
        ".claude-plugin/plugin.json": '{"name":"test"}',
        "nested/out.txt": "hello",
    }
    out = Path("/ignored/by/memory/sink")

    result = sink.write(files, out, dry_run=False)

    assert sink.captured == files
    assert result.dry_run is False
    assert dict(result.files) == {
        ".claude-plugin/plugin.json": _sha256(files[".claude-plugin/plugin.json"]),
        "nested/out.txt": _sha256(files["nested/out.txt"]),
    }


def test_memory_writer_sink_dry_run_writes_nothing() -> None:
    """dry_run=True returns hashes but does not update captured."""
    sink = MemoryWriterSink()
    sink.captured = {"stale.txt": "old content"}
    files = {"a.txt": "new content"}
    out = Path("/ignored/by/memory/sink")

    result = sink.write(files, out, dry_run=True)

    assert sink.captured == {"stale.txt": "old content"}
    assert result.dry_run is True
    assert dict(result.files) == {"a.txt": _sha256("new content")}


def test_memory_writer_sink_ignores_out_path() -> None:
    """MemoryWriterSink never touches the filesystem regardless of out."""
    sink = MemoryWriterSink()
    files = {"only.txt": "data"}

    result = sink.write(files, Path("/nonexistent/root/that/must/not/be/created"))

    assert sink.captured == files
    assert result.dry_run is False
