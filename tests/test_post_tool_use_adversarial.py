"""Adversarial Stress Testing for PostToolUse hook and error envelope classification (Spec §C5).

Milestone M5 Challenger 1 test suite covering:
1. Malformed payloads: non-JSON content, empty strings, missing fields, truncated JSON text.
2. Non-mcp calls: verify Bash, CustomTool, etc. write nothing to ledger even if error output contains "Error: ...".
3. Nested error structures: verify SQL results with error column in rows (and top-level ok: true) do NOT write to ledger.
4. Each adapter fixture: verify all 10 fixtures produce exactly expected outcomes.
5. Atomic append and concurrency: verify multi-process concurrent writes to <sessions_dir>/<session_id>/errors.jsonl are valid JSON lines.
6. Record length and file size limits: 4096-byte line truncation and 1 MiB file limit.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path
import time
from typing import Any

import pytest

from cisternal.usage.hooks import (
    classify_mcp_error,
    handle_post_tool_use,
)
from cisternal.usage.paths import (
    MAX_FILE_SIZE_BYTES,
    MAX_RECORD_LINE_BYTES,
    atomic_append_jsonl,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hooks" / "post_tool_use"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


# =========================================================================
# 1. Malformed Payloads Stress Testing
# =========================================================================


class TestMalformedPayloads:
    """Stress-test handle_post_tool_use and classify_mcp_error against malformed inputs."""

    @pytest.mark.parametrize(
        "bad_payload",
        [
            "",
            "   ",
            "not-json",
            "{broken json",
            "{'single_quotes': 1}",
            "None",
            "123",
            "[1, 2, 3]",
        ],
    )
    def test_malformed_string_payloads_fail_open(
        self, tmp_path: Path, bad_payload: str
    ) -> None:
        """Non-JSON string payloads must return False and create no ledger."""
        sessions_dir = tmp_path / "sessions"
        res = handle_post_tool_use(bad_payload, sessions_dir=sessions_dir)
        assert res is False
        assert not sessions_dir.exists()

    @pytest.mark.parametrize(
        "bad_obj",
        [
            None,
            42,
            3.14,
            True,
            False,
            [],
            [{"tool_name": "mcp__bathos__run_sql"}],
        ],
    )
    def test_non_dict_payload_objects_fail_open(
        self, tmp_path: Path, bad_obj: Any
    ) -> None:
        """Non-dict payloads must return False."""
        sessions_dir = tmp_path / "sessions"
        res = handle_post_tool_use(bad_obj, sessions_dir=sessions_dir)
        assert res is False
        assert not sessions_dir.exists()

    @pytest.mark.parametrize(
        "missing_fields_payload",
        [
            {},  # empty dict
            {"tool_name": "mcp__bathos__run_sql"},  # missing session_id
            {"session_id": "", "tool_name": "mcp__bathos__run_sql"},  # empty session_id
            {
                "session_id": "   ",
                "tool_name": "mcp__bathos__run_sql",
            },  # whitespace session_id
            {"session_id": "s1"},  # missing tool_name
            {"session_id": "s1", "tool_name": ""},  # empty tool_name
            {
                "session_id": "s1",
                "tool_name": "bathos__run_sql",
            },  # missing mcp__ prefix
        ],
    )
    def test_missing_required_fields_fail_open(
        self, tmp_path: Path, missing_fields_payload: dict[str, Any]
    ) -> None:
        """Payloads missing required fields must return False without logging."""
        sessions_dir = tmp_path / "sessions"
        res = handle_post_tool_use(missing_fields_payload, sessions_dir=sessions_dir)
        assert res is False
        assert not sessions_dir.exists()

    @pytest.mark.parametrize(
        "broken_response",
        [
            None,
            "",
            "   ",
            "not a json response",
            '{"ok": false',  # truncated json
            '{"error": "syntax error"',  # truncated json
            '{"rows": [1, 2, ',  # truncated array
            42,
            3.14,
            True,
            False,
            [],
            [1, 2, 3],
            {"content": None},
            {"content": []},
            {"content": [{"type": "image"}]},  # no text key
            {"content": "not a list"},
            {"content": [123]},  # list with non-dict
            {"text": None},
            {"text": '{"ok": false'},  # truncated inner text
            {"text": ""},
        ],
    )
    def test_malformed_and_truncated_tool_responses(
        self, tmp_path: Path, broken_response: Any
    ) -> None:
        """classify_mcp_error and handle_post_tool_use handle malformed tool_response gracefully."""
        is_err, code, msg = classify_mcp_error(
            "bathos/run_sql", broken_response, is_protocol_error=False
        )
        assert is_err is False
        assert code is None
        assert msg is None

        sessions_dir = tmp_path / "sessions"
        payload = {
            "session_id": "sess_malformed_01",
            "tool_name": "mcp__bathos__run_sql",
            "tool_response": broken_response,
        }
        res = handle_post_tool_use(payload, sessions_dir=sessions_dir)
        assert res is False
        assert not (sessions_dir / "sess_malformed_01" / "errors.jsonl").exists()

    def test_protocol_error_with_malformed_response_still_captures(
        self, tmp_path: Path
    ) -> None:
        """When is_protocol_error=True, classify_mcp_error extracts whatever message it can."""
        is_err, code, msg = classify_mcp_error(
            "bathos/run_sql", None, is_protocol_error=True
        )
        assert is_err is True
        assert code == "PROTOCOL_ERROR"
        assert msg == "Protocol error"

        is_err, code, msg = classify_mcp_error(
            "bathos/run_sql", 12345, is_protocol_error=True
        )
        assert is_err is True
        assert code == "PROTOCOL_ERROR"
        assert msg == "12345"

        is_err, code, msg = classify_mcp_error(
            "bathos/run_sql", {"random_key": "val"}, is_protocol_error=True
        )
        assert is_err is True
        assert code == "PROTOCOL_ERROR"
        assert "random_key" in msg


# =========================================================================
# 2. Non-MCP Tool Calls Stress Testing
# =========================================================================


class TestNonMcpCalls:
    """Verify non-mcp calls (Bash, CustomTool, Read, Edit, etc.) never write to ledger."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "Bash",
            "bash",
            "CustomTool",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "mcp",
            "mcp_",
            "mcp_tool",
            "plugin_bathos_bathos__run_sql",  # missing leading mcp__
            "_mcp__bathos__run_sql",
        ],
    )
    def test_non_mcp_calls_never_logged_even_with_explicit_errors(
        self, tmp_path: Path, tool_name: str
    ) -> None:
        """Even with explicit protocol error flags and error text, non-mcp tools are ignored."""
        sessions_dir = tmp_path / "sessions"
        session_id = f"sess_non_mcp_{tool_name}"

        payloads = [
            # Case A: CLI error text
            {
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_response": {
                    "content": [{"type": "text", "text": "Error: command not found"}],
                    "is_error": True,
                },
            },
            # Case B: Top-level is_error
            {
                "session_id": session_id,
                "tool_name": tool_name,
                "is_error": True,
                "tool_response": "Fatal: syntax error",
            },
            # Case C: PostToolUseFailure event
            {
                "session_id": session_id,
                "tool_name": tool_name,
                "hook_event_name": "PostToolUseFailure",
                "tool_response": {"text": "Process crashed: exit 127"},
            },
            # Case D: JSON error envelope
            {
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_response": {"ok": False, "error": "failed"},
            },
        ]

        for p in payloads:
            res = handle_post_tool_use(p, sessions_dir=sessions_dir)
            assert res is False, f"Expected False for tool_name='{tool_name}', got True"

        # Assert no errors.jsonl was created
        ledger = sessions_dir / session_id / "errors.jsonl"
        assert not ledger.exists()


# =========================================================================
# 3. Nested Error Structures Stress Testing
# =========================================================================


class TestNestedErrorStructures:
    """Verify nested error columns, fields, and objects when top-level ok is true are NOT errors."""

    @pytest.mark.parametrize(
        ("server", "canonical_key", "response_body"),
        [
            (
                "bathos",
                "bathos/run_sql",
                {
                    "ok": True,
                    "rows": [
                        {
                            "id": 1,
                            "status": "FAILED",
                            "error": "Disk I/O error",
                            "error_code": 500,
                        },
                        {
                            "id": 2,
                            "status": "ERROR",
                            "error": "Timeout",
                            "error_code": 504,
                        },
                    ],
                    "columns": ["id", "status", "error", "error_code"],
                },
            ),
            (
                "xperiri",
                "xperiri/run_experiment",
                {
                    "ok": True,
                    "experiment": {
                        "id": "exp_101",
                        "error_tolerance": 0.05,
                        "last_error": "Previous run failed with OOM",
                        "error_log": ["err1", "err2"],
                    },
                },
            ),
            (
                "contemplex",
                "contemplex/brainstorm_reply",
                {
                    "ok": True,
                    "session_id": "ctxp_01",
                    "error_code": None,
                    "critique": {
                        "error_analysis": "System handled past errors well",
                        "error_code": "NOT_AN_ERROR",
                    },
                },
            ),
            (
                "myxcel",
                "myxcel/job_status",
                {
                    "ok": True,
                    "job_id": 12345,
                    "error": "JobFailed",  # but ok is True!
                    "message": "SLURM state is FAILED",
                },
            ),
            (
                "default_server",
                "generic/custom_tool",
                {
                    "ok": True,
                    "data": {"nested": {"ok": False, "error": "sub-component failed"}},
                },
            ),
        ],
    )
    def test_nested_error_structures_never_classified_as_error(
        self,
        tmp_path: Path,
        server: str,
        canonical_key: str,
        response_body: dict[str, Any],
    ) -> None:
        """Top-level ok=true responses containing error keys in data are NOT errors."""
        sessions_dir = tmp_path / "sessions"
        session_id = f"sess_nested_{server}"

        # 1. Test direct classify_mcp_error
        is_err, code, msg = classify_mcp_error(
            canonical_key, response_body, is_protocol_error=False
        )
        assert is_err is False
        assert code is None
        assert msg is None

        # 2. Test wrapped in content array
        wrapped_response = {
            "content": [{"type": "text", "text": json.dumps(response_body)}],
            "is_error": False,
        }
        is_err, code, msg = classify_mcp_error(
            canonical_key, wrapped_response, is_protocol_error=False
        )
        assert is_err is False

        # 3. Test handle_post_tool_use
        payload = {
            "session_id": session_id,
            "tool_name": f"mcp__{server}__{canonical_key.split('/')[-1]}",
            "tool_response": wrapped_response,
        }
        res = handle_post_tool_use(payload, sessions_dir=sessions_dir)
        assert res is False
        assert not (sessions_dir / session_id / "errors.jsonl").exists()


# =========================================================================
# 4. Adapter Fixture Verification (All 10 Fixtures)
# =========================================================================


class TestAdapterFixturesCompleteness:
    """Verify all 10 adapter fixtures + 2 controls produce exactly expected outcomes."""

    FIXTURE_EXPECTATIONS = {
        # Success fixtures: is_error=False, ledger written=False
        "bathos_success.json": (False, None, None),
        "contemplex_success.json": (False, None, None),
        "xperiri_success.json": (False, None, None),
        "myxcel_success.json": (False, None, None),
        "passthrough_success.json": (False, None, None),
        # Control fixtures:
        "control_bash_error.json": (False, None, None),
        "control_nested_error_success.json": (False, None, None),
        # Error fixtures: is_error=True, ledger written=True, (tool, code)
        "bathos_error.json": (True, "bathos/run_sql", "SQLITE_ERROR"),
        "contemplex_error.json": (True, "contemplex/brainstorm_reply", "GATE_BLOCKED"),
        "xperiri_error.json": (True, "xperiri/run_experiment", "INVALID_CONFIG"),
        "myxcel_error.json": (True, "myxcel/job_status", "JobNotFoundError"),
        "passthrough_error.json": (True, "passthrough/echo", "PROTOCOL_ERROR"),
    }

    def test_all_10_fixtures_exist_on_disk(self) -> None:
        """Ensure all required fixtures exist in tests/fixtures/hooks/post_tool_use/."""
        for fixture_name in self.FIXTURE_EXPECTATIONS:
            fixture_file = _FIXTURES_DIR / fixture_name
            assert fixture_file.is_file(), f"Missing fixture file: {fixture_file}"

    @pytest.mark.parametrize("fixture_name", list(FIXTURE_EXPECTATIONS.keys()))
    def test_each_fixture_produces_exact_expected_outcome(
        self, tmp_path: Path, fixture_name: str
    ) -> None:
        expected_err, expected_tool, expected_code = self.FIXTURE_EXPECTATIONS[
            fixture_name
        ]
        payload = _load_fixture(fixture_name)
        session_id = payload["session_id"]
        sessions_dir = tmp_path / "sessions"

        families = {
            "bathos_query": ("bathos/run_sql",),
            "contemplex_brainstorm": ("contemplex/brainstorm_reply",),
            "myxcel_slurm": ("myxcel/job_status",),
        }

        result = handle_post_tool_use(
            payload, sessions_dir=sessions_dir, families=families
        )
        assert result == expected_err, (
            f"Fixture {fixture_name} expected {expected_err}, got {result}"
        )

        ledger_path = sessions_dir / session_id / "errors.jsonl"
        if not expected_err:
            assert not ledger_path.exists(), (
                f"Fixture {fixture_name} should NOT write to ledger"
            )
        else:
            assert ledger_path.is_file(), f"Fixture {fixture_name} MUST write to ledger"
            lines = [
                line.strip()
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["session_id"] == session_id
            assert record["tool"] == expected_tool
            assert record["error_code"] == expected_code
            assert record["source"] == "post_tool_use"
            assert "timestamp" in record
            assert "message" in record


# =========================================================================
# 5. Concurrency & Atomic Append Stress Testing
# =========================================================================


def _worker_append(
    file_path_str: str, worker_id: int, count: int, delay_s: float
) -> int:
    """Worker function executed in separate process to append records concurrently."""
    path = Path(file_path_str)
    successes = 0
    for i in range(count):
        rec = {
            "timestamp": "2026-11-10T00:00:00Z",
            "session_id": f"sess_worker_{worker_id}",
            "tool": f"bathos/tool_{worker_id}",
            "family": "bathos_query",
            "seq": i,
            "worker_id": worker_id,
            "message": f"Worker {worker_id} message iteration {i}",
        }
        if atomic_append_jsonl(path, rec):
            successes += 1
        if delay_s > 0:
            time.sleep(delay_s)
    return successes


class TestAtomicAppendAndConcurrency:
    """Empirical verification of POSIX atomic append under multi-process concurrency."""

    def test_concurrent_multiprocess_appends_preserve_json_lines(
        self, tmp_path: Path
    ) -> None:
        """Spawn 10 processes, each appending 50 records concurrently to one errors.jsonl file."""
        ledger_path = tmp_path / "concurrent" / "errors.jsonl"
        num_workers = 10
        records_per_worker = 50
        expected_total = num_workers * records_per_worker

        ctx = mp.get_context("spawn")
        pool = ctx.Pool(processes=num_workers)
        try:
            tasks = [
                pool.apply_async(
                    _worker_append,
                    (str(ledger_path), worker_id, records_per_worker, 0.001),
                )
                for worker_id in range(num_workers)
            ]
            results = [t.get(timeout=30) for t in tasks]
        finally:
            pool.close()
            pool.join()

        assert sum(results) == expected_total

        # Verify the ledger file
        assert ledger_path.is_file()
        raw_lines = ledger_path.read_text(encoding="utf-8").splitlines()
        non_empty_lines = [line.strip() for line in raw_lines if line.strip()]

        # 1. Total line count must match exactly
        assert len(non_empty_lines) == expected_total

        # 2. Every single line must parse as valid JSON
        per_worker_counts: dict[int, int] = {}
        for idx, line in enumerate(non_empty_lines):
            try:
                doc = json.loads(line)
            except Exception as exc:
                pytest.fail(
                    f"Line {idx} corrupted during concurrent append: {exc}\nLine content: {line[:200]}"
                )
            assert isinstance(doc, dict)
            w_id = doc.get("worker_id")
            assert isinstance(w_id, int)
            per_worker_counts[w_id] = per_worker_counts.get(w_id, 0) + 1

        # 3. Each worker must have exactly records_per_worker lines
        for w_id in range(num_workers):
            assert per_worker_counts.get(w_id) == records_per_worker

    def test_line_truncation_enforces_4096_bytes_and_valid_json(
        self, tmp_path: Path
    ) -> None:
        """A record with a huge message string must be truncated <= 4096 bytes and remain valid JSON."""
        ledger_path = tmp_path / "truncated" / "errors.jsonl"
        huge_message = "A" * 10000
        rec = {
            "timestamp": "2026-11-10T00:00:00Z",
            "session_id": "sess_huge_01",
            "tool": "bathos/run_sql",
            "family": "bathos_query",
            "message": huge_message,
        }

        ok = atomic_append_jsonl(ledger_path, rec)
        assert ok is True

        content = ledger_path.read_bytes()
        assert len(content) <= MAX_RECORD_LINE_BYTES
        assert content.endswith(b"\n")

        line = content.decode("utf-8").strip()
        parsed = json.loads(line)
        assert parsed["session_id"] == "sess_huge_01"
        assert "[TRUNCATED]" in parsed["message"]

    def test_file_size_cap_1mib_fails_open(self, tmp_path: Path) -> None:
        """When ledger file size reaches 1 MiB (1_048_576 bytes), subsequent writes fail open."""
        ledger_path = tmp_path / "oversize" / "errors.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # Pre-seed file to exactly 1 MiB
        filler = b"X" * (MAX_FILE_SIZE_BYTES)
        ledger_path.write_bytes(filler)

        rec = {
            "timestamp": "2026-11-10T00:00:00Z",
            "session_id": "sess_over_01",
            "tool": "bathos/run_sql",
            "message": "should not be appended",
        }

        # atomic_append_jsonl must return False without crashing
        appended = atomic_append_jsonl(ledger_path, rec)
        assert appended is False

        # File size must not have increased
        assert ledger_path.stat().st_size == MAX_FILE_SIZE_BYTES


# =========================================================================
# 6. Server-Specific Envelope Edge Cases
# =========================================================================


class TestServerEnvelopeEdgeCases:
    """Adversarially probe boundary conditions of server envelope classification rules."""

    def test_contemplex_error_code_with_ok_true_is_not_error(self) -> None:
        """contemplex: top-level ok is False or (error_code and ok is not True).

        If ok is True, error_code present MUST NOT trigger an error.
        """
        resp = {"ok": True, "error_code": "WARN_NON_FATAL", "message": "Notice"}
        is_err, code, msg = classify_mcp_error("contemplex/reply", resp)
        assert is_err is False

    def test_contemplex_error_code_with_missing_ok_is_error(self) -> None:
        """contemplex: if ok is missing (None) and error_code is present -> is error."""
        resp = {"error_code": "GATE_BLOCKED", "message": "Blocked"}
        is_err, code, msg = classify_mcp_error("contemplex/reply", resp)
        assert is_err is True
        assert code == "GATE_BLOCKED"

    def test_contemplex_ok_false_without_error_code_is_error(self) -> None:
        """contemplex: ok is False without error_code is still an error."""
        resp = {"ok": False, "message": "Failed generic"}
        is_err, code, msg = classify_mcp_error("contemplex/reply", resp)
        assert is_err is True
        assert code == "error"
        assert msg == "Failed generic"

    def test_myxcel_error_with_ok_true_is_not_error(self) -> None:
        """myxcel: if ok is True, error string must not trigger error."""
        resp = {"ok": True, "error": "JobCompletedWithErrors", "message": "Exit code 1"}
        is_err, code, msg = classify_mcp_error("myxcel/status", resp)
        assert is_err is False

    def test_myxcel_error_with_empty_error_string_is_not_error(self) -> None:
        """myxcel: if error is empty string, not an error."""
        resp = {"error": "", "message": "All good"}
        is_err, code, msg = classify_mcp_error("myxcel/status", resp)
        assert is_err is False

    def test_myxcel_error_with_non_string_error_is_not_error(self) -> None:
        """myxcel: error must be a string."""
        resp = {"error": 404, "message": "Not found"}
        is_err, code, msg = classify_mcp_error("myxcel/status", resp)
        assert is_err is False

    def test_bathos_missing_ok_is_not_error(self) -> None:
        """bathos: ok must be explicitly False; missing ok is not an error."""
        resp = {"result": 42, "status": "ok"}
        is_err, code, msg = classify_mcp_error("bathos/run_sql", resp)
        assert is_err is False

    def test_default_server_ok_false_is_error(self) -> None:
        """default servers: ok is False -> error."""
        resp = {"ok": False, "error_code": "CUSTOM_ERR", "message": "Custom message"}
        is_err, code, msg = classify_mcp_error("unregistered_srv/do_thing", resp)
        assert is_err is True
        assert code == "CUSTOM_ERR"
        assert msg == "Custom message"
