"""Security tests for FileWriterSink path traversal prevention."""

from __future__ import annotations

from pathlib import Path

from cisternal.export.sink import FileWriterSink


def test_file_writer_sink_blocks_path_traversal(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    outside_file = tmp_path / "outside.txt"

    malicious_files = {
        "valid.txt": "valid content",
        "../outside.txt": "malicious content",
        "nested/../../outside2.txt": "malicious content 2",
    }

    sink = FileWriterSink()
    sink.write(malicious_files, out_dir, dry_run=False)

    # Valid file was written
    assert (out_dir / "valid.txt").is_file()
    assert (out_dir / "valid.txt").read_text(encoding="utf-8") == "valid content"

    # Traversal files were blocked
    assert not outside_file.exists()
    assert not (tmp_path / "outside2.txt").exists()


def test_file_writer_sink_blocks_intra_root_traversal(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    files = {
        "skills/demo/SKILL.md": "# Demo",
        "skills/demo/../../escaped.txt": "evil",
        "/absolute/path.txt": "evil",
    }

    sink = FileWriterSink()
    sink.write(files, out_dir, dry_run=False)

    assert (out_dir / "skills" / "demo" / "SKILL.md").is_file()
    assert not (out_dir / "escaped.txt").exists()
    assert not Path("/absolute/path.txt").exists()


def test_file_writer_sink_never_raises_on_non_string_or_surrogates(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    files = {
        "none.txt": None,
        "number.txt": 12345,
        "surrogate.txt": "\ud800",
    }

    sink = FileWriterSink()
    # Must never raise
    sink.write(files, out_dir, dry_run=False)
    assert (out_dir / "none.txt").is_file()
    assert (out_dir / "number.txt").is_file()
    assert (out_dir / "surrogate.txt").is_file()

