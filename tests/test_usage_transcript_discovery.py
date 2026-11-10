"""Tests for recursive transcript discovery across main sessions and subagents."""

from __future__ import annotations

from pathlib import Path

from cisternal.usage.transcript import discover_transcript_files


class TestDiscoverTranscriptFiles:
    """Test discovery of main session transcripts and nested subagent transcripts."""

    def test_discover_main_session_transcripts(self, tmp_path: Path) -> None:
        proj = tmp_path / "my-project"
        proj.mkdir()
        t1 = proj / "session-1.jsonl"
        t2 = proj / "session-2.jsonl"
        t1.write_text('{"type": "init"}\n', encoding="utf-8")
        t2.write_text('{"type": "init"}\n', encoding="utf-8")

        found = list(discover_transcript_files(tmp_path))
        assert len(found) == 2
        assert found == [("my-project", t1), ("my-project", t2)]

    def test_discover_nested_subagent_transcripts(self, tmp_path: Path) -> None:
        proj = tmp_path / "my-project"
        subagents_dir = proj / "session-parent" / "subagents"
        subagents_dir.mkdir(parents=True)
        sub1 = subagents_dir / "agent-1.jsonl"
        sub2 = subagents_dir / "agent-2.jsonl"
        sub1.write_text('{"type": "subagent"}\n', encoding="utf-8")
        sub2.write_text('{"type": "subagent"}\n', encoding="utf-8")

        found = list(discover_transcript_files(tmp_path))
        assert len(found) == 2
        assert found == [("my-project", sub1), ("my-project", sub2)]

    def test_multi_slug_mixed_hierarchy(self, tmp_path: Path) -> None:
        p1 = tmp_path / "slug-a"
        p1.mkdir()
        (p1 / "main.jsonl").write_text("{}\n", encoding="utf-8")
        (p1 / "sess1" / "subagents").mkdir(parents=True)
        (p1 / "sess1" / "subagents" / "sub.jsonl").write_text("{}\n", encoding="utf-8")

        p2 = tmp_path / "slug-b"
        p2.mkdir()
        (p2 / "main2.jsonl").write_text("{}\n", encoding="utf-8")

        found = list(discover_transcript_files(tmp_path))
        assert len(found) == 3
        slugs = [slug for slug, _ in found]
        assert slugs.count("slug-a") == 2
        assert slugs.count("slug-b") == 1

    def test_ignores_non_jsonl_files(self, tmp_path: Path) -> None:
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / "session.json").write_text("{}\n", encoding="utf-8")
        (proj / "notes.txt").write_text("hello\n", encoding="utf-8")
        (proj / ".DS_Store").write_bytes(b"\x00")
        valid = proj / "session.jsonl"
        valid.write_text("{}\n", encoding="utf-8")

        found = list(discover_transcript_files(tmp_path))
        assert found == [("my-project", valid)]

    def test_ignores_stray_directories(self, tmp_path: Path) -> None:
        proj = tmp_path / "my-project"
        stray = proj / "random_subfolder"
        stray.mkdir(parents=True)
        (stray / "stray.jsonl").write_text("{}\n", encoding="utf-8")

        found = list(discover_transcript_files(tmp_path))
        assert found == []

    def test_missing_or_empty_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        assert list(discover_transcript_files(missing)) == []

        empty = tmp_path / "empty_dir"
        empty.mkdir()
        assert list(discover_transcript_files(empty)) == []
