"""Tests for session-type stratification (main_interactive vs subagent_headless)."""

from __future__ import annotations

from pathlib import Path

from cisternal.usage.transcript import (
    TranscriptEvent,
    stratify_session_type,
    stream_transcript_events,
)


class TestStratifySessionType:
    """Test stratification based on file location and transcript records."""

    def test_subagent_by_path(self) -> None:
        p = Path("my-project/session_123/subagents/agent-1.jsonl")
        events = [{"type": "user", "message": "hello"}]
        assert stratify_session_type(events, p) == "subagent_headless"

    def test_subagent_by_is_sidechain_record(self) -> None:
        p = Path("my-project/session_123.jsonl")
        events = [
            {"type": "init"},
            {"type": "turn", "isSidechain": True},
        ]
        assert stratify_session_type(events, p) == "subagent_headless"

    def test_subagent_by_session_type_record(self) -> None:
        p = Path("my-project/session_123.jsonl")
        events = [
            {"type": "init"},
            {"session_type": "subagent"},
        ]
        assert stratify_session_type(events, p) == "subagent_headless"

    def test_main_interactive_default(self) -> None:
        p = Path("my-project/session_123.jsonl")
        events = [
            {"type": "init", "isSidechain": False},
            {"type": "user", "message": "do work"},
            {"type": "assistant", "message": "working"},
        ]
        assert stratify_session_type(events, p) == "main_interactive"

    def test_empty_events_main_path(self) -> None:
        p = Path("my-project/session_123.jsonl")
        assert stratify_session_type([], p) == "main_interactive"

    def test_empty_events_subagent_path(self) -> None:
        p = Path("my-project/session_123/subagents/agent-2.jsonl")
        assert stratify_session_type([], p) == "subagent_headless"

    def test_generator_iterable_accepted(self) -> None:
        p = Path("my-project/session_123.jsonl")

        def event_gen():
            yield {"type": "step1"}
            yield {"type": "step2", "isSidechain": True}
            yield {"type": "step3"}

        assert stratify_session_type(event_gen(), p) == "subagent_headless"

    def test_transcript_event_instances_accepted(self) -> None:
        p = Path("my-project/session_123.jsonl")
        events = [
            TranscriptEvent(
                event_type="init",
                timestamp="2026-11-10T00:00:00Z",
                payload={},
                raw_record={"type": "init", "isSidechain": False},
            ),
            TranscriptEvent(
                event_type="sidechain_turn",
                timestamp="2026-11-10T00:01:00Z",
                payload={},
                raw_record={"type": "sidechain_turn", "isSidechain": True},
            ),
        ]
        assert stratify_session_type(events, p) == "subagent_headless"

    def test_transcript_event_main_interactive(self) -> None:
        p = Path("my-project/session_123.jsonl")
        events = [
            TranscriptEvent(
                event_type="init",
                timestamp="2026-11-10T00:00:00Z",
                payload={},
                raw_record={"type": "init", "isSidechain": False},
            ),
            TranscriptEvent(
                event_type="turn",
                timestamp="2026-11-10T00:01:00Z",
                payload={},
                raw_record={"type": "turn", "isSidechain": False},
            ),
        ]
        assert stratify_session_type(events, p) == "main_interactive"

    def test_stream_transcript_events_direct_pass(self, tmp_path: Path) -> None:
        p = tmp_path / "sess.jsonl"
        p.write_text(
            '{"type": "init"}\n'
            '{"type": "subagent_turn", "session_type": "subagent"}\n',
            encoding="utf-8",
        )
        assert stratify_session_type(stream_transcript_events(p), p) == "subagent_headless"


class TestStreamTranscriptEvents:
    """Test resilience of stream_transcript_events against malformed transcripts."""

    def test_nonexistent_file_yields_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.jsonl"
        assert list(stream_transcript_events(p)) == []

    def test_empty_and_whitespace_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "whitespace.jsonl"
        p.write_text("\n\n   \n\t\n", encoding="utf-8")
        assert list(stream_transcript_events(p)) == []

    def test_malformed_json_and_non_dict_records(self, tmp_path: Path) -> None:
        p = tmp_path / "corrupt.jsonl"
        lines = [
            "",
            "   ",
            "{corrupt json syntax",
            '"just a string"',
            "42",
            "[1, 2, 3]",
            "true",
            "null",
            '{"type": "valid_event", "ts": "2026-11-10T00:00:00Z", "payload": {"k": "v"}}',
            "truncated { json",
            '{"event": "second_valid", "data": {"x": 1}}',
            "}",
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        events = list(stream_transcript_events(p))
        assert len(events) == 2
        assert events[0].event_type == "valid_event"
        assert events[0].timestamp == "2026-11-10T00:00:00Z"
        assert events[0].payload == {"k": "v"}

        assert events[1].event_type == "second_valid"
        assert events[1].payload == {"x": 1}
