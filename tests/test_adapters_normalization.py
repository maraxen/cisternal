"""Tests for adapter error normalization (spec §Pre-1, §C5).

Comprehensive verification of NormalizedError dataclass, AdapterBase defaults,
subclass overrides (BathosAdapter, ContemplexAdapter, XpeririAdapter, MyxcelAdapter,
PassthroughAdapter), and zero file I/O purity.
"""

from dataclasses import FrozenInstanceError
import os
import pathlib
from typing import Any

import pytest

from cisternal.adapters.base import (
    AdapterBase,
    BathosAdapter,
    ContemplexAdapter,
    MyxcelAdapter,
    NormalizedError,
    PassthroughAdapter,
    XpeririAdapter,
)


class ConcreteTestAdapter(AdapterBase):
    """Concrete adapter subclass for testing AdapterBase defaults."""

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        return result

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        return {"error": str(exc)}


class ClusterSchedulingTimeout(Exception):
    """Custom exception subclass for testing."""


class DummyToolResult:
    """Mock for FastMCP ToolResult object."""

    def __init__(self, content: str = "", is_error: bool = False) -> None:
        self.content = content
        self.is_error = is_error


class TestAdapterBaseNormalizeError:
    """Class 1: Tests for AdapterBase.normalize_error default implementation."""

    def test_base_normalize_error_success_explicit_ok_true(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {"ok": True, "data": {"items": [1, 2, 3]}, "summary": "done"}
        result = adapter.normalize_error(input_data)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True
        assert result.to_dict()["error_code"] == ""
        assert result.to_dict()["message"] == ""
        assert result.to_dict()["resolution_hint"] is None

    def test_base_normalize_error_success_empty_dict(self) -> None:
        adapter = ConcreteTestAdapter()
        result = adapter.normalize_error({})
        assert result.is_error is False
        assert result.to_dict()["ok"] is True
        assert result.to_dict()["error_code"] == ""

    def test_base_normalize_error_success_nested_error_field_ignored(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {
            "ok": True,
            "results": [{"id": 1, "error": "db timeout", "code": 500}],
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_base_normalize_error_explicit_ok_false_with_error_code(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {
            "ok": False,
            "error_code": "RESOURCE_EXHAUSTED",
            "message": "quota exceeded",
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_code == "RESOURCE_EXHAUSTED"
        assert result.error_message == "quota exceeded"
        d = result.to_dict()
        assert d["ok"] is False
        assert d["error_code"] == "RESOURCE_EXHAUSTED"
        assert d["message"] == "quota exceeded"

    def test_base_normalize_error_explicit_ok_false_with_error_string(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {"ok": False, "error": "connection reset by peer"}
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_message == "connection reset by peer"
        assert result.to_dict()["ok"] is False

    def test_base_normalize_error_is_error_true_flag(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {
            "is_error": True,
            "error_code": "AUTH_FAILED",
            "message": "token expired",
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_code == "AUTH_FAILED"
        assert result.error_message == "token expired"
        assert result.to_dict()["ok"] is False

    def test_base_normalize_error_top_level_error_code_without_ok(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {
            "error_code": "INVALID_ARGUMENT",
            "message": "param x must be positive",
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_code == "INVALID_ARGUMENT"
        assert result.error_message == "param x must be positive"
        assert result.to_dict()["ok"] is False

    def test_base_normalize_error_error_code_none_treated_as_success(self) -> None:
        adapter = ConcreteTestAdapter()
        input_data = {"ok": True, "error_code": None, "error": None}
        result = adapter.normalize_error(input_data)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_base_normalize_error_unknown_non_dict_objects(self) -> None:
        adapter = ConcreteTestAdapter()
        items = [None, 100, 3.14, [1, 2, 3], "arbitrary string", object()]
        for item in items:
            result = adapter.normalize_error(item)
            assert result.is_error is False
            assert result.to_dict()["ok"] is True

    def test_base_normalize_error_passes_through_normalized_error(self) -> None:
        adapter = ConcreteTestAdapter()
        original = NormalizedError(
            is_error=True,
            error_code="CUSTOM_ERR",
            error_message="custom msg",
            resolution_hint="retry",
        )
        result = adapter.normalize_error(original)
        assert result is original

    def test_base_normalize_error_delegates_exception(self) -> None:
        adapter = ConcreteTestAdapter()
        exc = ValueError("bad value")
        result = adapter.normalize_error(exc)
        assert result.is_error is True
        assert result.error_code == "ValueError"
        assert result.error_message == "bad value"


class TestAdapterBaseNormalizeException:
    """Class 2: Tests for AdapterBase.normalize_exception."""

    def test_base_normalize_exception_standard_builtins(self) -> None:
        adapter = ConcreteTestAdapter()
        exceptions = [
            ValueError("invalid value specified"),
            RuntimeError("subsystem crashed"),
            KeyError("missing_col"),
            FileNotFoundError("file.txt not found"),
        ]
        for exc in exceptions:
            result = adapter.normalize_exception(exc)
            assert result.is_error is True
            assert result.error_code == type(exc).__name__
            assert result.error_message == str(exc)
            d = result.to_dict()
            assert d["ok"] is False
            assert d["error_code"] == type(exc).__name__
            assert d["message"] == str(exc)

    def test_base_normalize_exception_custom_exception_subclass(self) -> None:
        adapter = ConcreteTestAdapter()
        exc = ClusterSchedulingTimeout("partition queue full")
        result = adapter.normalize_exception(exc)
        assert result.is_error is True
        assert result.error_code == "ClusterSchedulingTimeout"
        assert result.error_message == "partition queue full"
        assert result.to_dict()["ok"] is False

    def test_base_normalize_exception_empty_message(self) -> None:
        adapter = ConcreteTestAdapter()
        result = adapter.normalize_exception(RuntimeError())
        assert result.is_error is True
        assert result.error_code == "RuntimeError"
        assert result.error_message == ""

    def test_base_normalize_exception_base_exception_type(self) -> None:
        adapter = ConcreteTestAdapter()
        exc = KeyboardInterrupt("interrupted")
        result = adapter.normalize_exception(exc)
        assert result.is_error is True
        assert result.error_code == "KeyboardInterrupt"

    def test_base_normalize_exception_secret_redaction(self) -> None:
        adapter = ConcreteTestAdapter()
        exc = ValueError("Failed with Authorization: Bearer super_secret_token_123")
        result = adapter.normalize_exception(exc)
        assert result.is_error is True
        assert "super_secret_token_123" not in result.error_message
        assert "[REDACTED]" in result.error_message


class TestBathosAdapterNormalizeError:
    """Class 3: Tests for BathosAdapter.normalize_error."""

    def test_bathos_normalize_error_success_standard_envelope(self) -> None:
        adapter = BathosAdapter()
        input_data = {
            "ok": True,
            "error_code": None,
            "error": None,
            "resolution_hint": None,
            "rows": [{"id": 1}],
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_bathos_normalize_error_success_from_shape_ok(self) -> None:
        adapter = BathosAdapter()
        shaped = adapter.shape_ok("run_sql", {"count": 42})
        result = adapter.normalize_error(shaped)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_bathos_normalize_error_failure_from_shape_error(self) -> None:
        adapter = BathosAdapter()
        shaped = adapter.shape_error("run_sql", RuntimeError("sqlite locked"))
        result = adapter.normalize_error(shaped)
        assert result.is_error is True
        assert result.error_code == "INTERNAL"
        assert result.error_message == "sqlite locked"
        assert result.to_dict()["ok"] is False
        assert result.to_dict()["error_code"] == "INTERNAL"
        assert result.to_dict()["message"] == "sqlite locked"

    def test_bathos_normalize_error_failure_custom_error_code_and_hint(self) -> None:
        adapter = BathosAdapter()
        input_data = {
            "ok": False,
            "error_code": "BATHOS_RUN_NOT_FOUND",
            "error": "Run 260815_abc does not exist",
            "resolution_hint": "Check bth list for valid run IDs",
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_code == "BATHOS_RUN_NOT_FOUND"
        assert result.error_message == "Run 260815_abc does not exist"
        assert result.resolution_hint == "Check bth list for valid run IDs"
        assert result.to_dict()["resolution_hint"] == "Check bth list for valid run IDs"

    def test_bathos_normalize_error_failure_message_fallback(self) -> None:
        adapter = BathosAdapter()
        input_data = {
            "ok": False,
            "error_code": "GATE_FAILED",
            "message": "Union gate failed",
        }
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_code == "GATE_FAILED"
        assert result.error_message == "Union gate failed"

    def test_bathos_normalize_error_bare_error_dict(self) -> None:
        adapter = BathosAdapter()
        input_data = {"error": "relation runs does not exist"}
        result = adapter.normalize_error(input_data)
        assert result.is_error is True
        assert result.error_code == "INTERNAL"
        assert result.error_message == "relation runs does not exist"


class TestContemplexAdapterNormalizeError:
    """Class 4: Tests for ContemplexAdapter.normalize_error."""

    def test_contemplex_normalize_error_success_plain_string(self) -> None:
        adapter = ContemplexAdapter()
        input_str = "Session session-261109-123 finalized successfully"
        result = adapter.normalize_error(input_str)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_contemplex_normalize_error_success_dict(self) -> None:
        adapter = ContemplexAdapter()
        input_dict = {
            "ok": True,
            "session_id": "sess-42",
            "ideas": ["idea_1", "idea_2"],
        }
        result = adapter.normalize_error(input_dict)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_contemplex_normalize_error_fallback_from_shape_error(self) -> None:
        adapter = ContemplexAdapter()
        shaped = adapter.shape_error("brainstorm_reply", ValueError("state corrupt"))
        result = adapter.normalize_error(shaped)
        assert result.is_error is True
        assert result.error_code == "INTERNAL"
        assert "state corrupt" in result.error_message
        assert result.to_dict()["ok"] is False

    def test_contemplex_normalize_error_err_envelope_unpacking(self) -> None:
        adapter = ContemplexAdapter()
        envelope = {
            "ok": False,
            "error_code": "GATE_BLOCKED",
            "error_type": "GATE_BLOCKED",
            "message": "Cognitive forcing beat required before convergence",
            "resolution_hint": "Execute Phase 3 forcing beat before Phase 4",
        }
        result = adapter.normalize_error(envelope)
        assert result.is_error is True
        assert result.error_code == "GATE_BLOCKED"
        assert (
            result.error_message == "Cognitive forcing beat required before convergence"
        )
        assert result.resolution_hint == "Execute Phase 3 forcing beat before Phase 4"
        assert result.to_dict()["ok"] is False
        assert result.to_dict()["error_code"] == "GATE_BLOCKED"

    def test_contemplex_normalize_error_envelope_error_key_variant(self) -> None:
        adapter = ContemplexAdapter()
        envelope = {
            "ok": False,
            "error_code": "SESSION_NOT_FOUND",
            "error": "No session 'ctxp-xyz'",
        }
        result = adapter.normalize_error(envelope)
        assert result.is_error is True
        assert result.error_code == "SESSION_NOT_FOUND"
        assert result.error_message == "No session 'ctxp-xyz'"

    def test_contemplex_normalize_error_non_empty_error_code_without_ok(self) -> None:
        adapter = ContemplexAdapter()
        envelope = {
            "error_code": "PHASE_MISMATCH",
            "message": "Cannot finalize in Phase 2",
        }
        result = adapter.normalize_error(envelope)
        assert result.is_error is True
        assert result.error_code == "PHASE_MISMATCH"
        assert result.error_message == "Cannot finalize in Phase 2"
        assert result.to_dict()["ok"] is False


class TestXpeririAdapterNormalizeError:
    """Class 5: Tests for XpeririAdapter.normalize_error."""

    def test_xperiri_normalize_error_json_string_success_explicit_ok(self) -> None:
        adapter = XpeririAdapter()
        json_str = '{"ok": true, "result": "expert loaded", "expert_id": "exp_1"}'
        result = adapter.normalize_error(json_str)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_xperiri_normalize_error_json_string_success_payload(self) -> None:
        adapter = XpeririAdapter()
        json_str = '{"experts": ["exp_1", "exp_2"], "total": 2}'
        result = adapter.normalize_error(json_str)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_xperiri_normalize_error_json_string_from_shape_error(self) -> None:
        adapter = XpeririAdapter()
        shaped = adapter.shape_error(
            "expert_resolve", ValueError("expert not registered")
        )
        result = adapter.normalize_error(shaped)
        assert result.is_error is True
        assert result.error_message == "expert not registered"
        assert result.to_dict()["ok"] is False
        assert result.to_dict()["message"] == "expert not registered"

    def test_xperiri_normalize_error_json_string_with_error_code(self) -> None:
        adapter = XpeririAdapter()
        json_str = '{"ok": false, "error_code": "EXPERT_NOT_FOUND", "error": "expert xyz not found"}'
        result = adapter.normalize_error(json_str)
        assert result.is_error is True
        assert result.error_code == "EXPERT_NOT_FOUND"
        assert result.error_message == "expert xyz not found"
        assert result.to_dict()["ok"] is False

    def test_xperiri_normalize_error_dict_fallback_success_and_error(self) -> None:
        adapter = XpeririAdapter()
        input_a = {"ok": True, "experts": []}
        assert adapter.normalize_error(input_a).is_error is False

        input_b = {"ok": False, "error_code": "QUERY_TIMEOUT", "error": "timed out"}
        res_b = adapter.normalize_error(input_b)
        assert res_b.is_error is True
        assert res_b.error_code == "QUERY_TIMEOUT"
        assert res_b.to_dict()["ok"] is False

    def test_xperiri_normalize_error_invalid_json_string_graceful(self) -> None:
        adapter = XpeririAdapter()
        for invalid_input in ["Malformed raw response string not JSON", ""]:
            result = adapter.normalize_error(invalid_input)
            assert result.is_error is False


class TestMyxcelAdapterNormalizeError:
    """Class 6: Tests for MyxcelAdapter.normalize_error."""

    def test_myxcel_normalize_error_in_band_error_dict(self) -> None:
        adapter = MyxcelAdapter()
        input_dict = {"error": "FileNotFoundError", "message": "profile missing"}
        result = adapter.normalize_error(input_dict)
        assert result.is_error is True
        assert result.error_code == "MYXCEL_ERROR"
        assert result.error_message == "profile missing"
        assert result.to_dict()["ok"] is False
        assert result.to_dict()["error_code"] == "MYXCEL_ERROR"
        assert result.to_dict()["message"] == "profile missing"

    def test_myxcel_normalize_error_from_shape_error(self) -> None:
        adapter = MyxcelAdapter()
        shaped = adapter.shape_error(
            "mount_project", ConnectionError("SSH handshake timed out")
        )
        result = adapter.normalize_error(shaped)
        assert result.is_error is True
        assert result.error_code == "MYXCEL_ERROR"
        assert result.error_message == "SSH handshake timed out"
        assert result.to_dict()["ok"] is False

    def test_myxcel_normalize_error_in_band_error_with_explicit_ok_false(self) -> None:
        adapter = MyxcelAdapter()
        input_dict = {
            "ok": False,
            "error": "SlurmSubmitError",
            "message": "QoS ceiling exceeded",
        }
        result = adapter.normalize_error(input_dict)
        assert result.is_error is True
        assert result.error_code == "MYXCEL_ERROR"
        assert result.error_message == "QoS ceiling exceeded"

    def test_myxcel_normalize_error_success_standard_dict(self) -> None:
        adapter = MyxcelAdapter()
        input_dict = {"remote": "hpc", "project": "cisternal", "mounted": True}
        result = adapter.normalize_error(input_dict)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_myxcel_normalize_error_success_list_of_records(self) -> None:
        adapter = MyxcelAdapter()
        input_list = [
            {"remote": "hpc", "mounted": True},
            {"remote": "titanix", "mounted": False},
        ]
        result = adapter.normalize_error(input_list)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_myxcel_normalize_error_ok_true_with_error_string_not_an_error(
        self,
    ) -> None:
        adapter = MyxcelAdapter()
        input_dict = {"ok": True, "error": "none", "message": "operation completed"}
        result = adapter.normalize_error(input_dict)
        assert result.is_error is False
        assert result.to_dict()["ok"] is True

    def test_myxcel_normalize_error_empty_or_none_error_field_is_success(self) -> None:
        adapter = MyxcelAdapter()
        for item in [
            {"error": "", "message": "status ok"},
            {"error": None, "message": "status ok"},
        ]:
            result = adapter.normalize_error(item)
            assert result.is_error is False


class TestPassthroughAdapterNormalize:
    """Class 7: Tests for PassthroughAdapter.normalize_error and normalize_exception."""

    def test_passthrough_normalize_error_arbitrary_success_object(self) -> None:
        adapter = PassthroughAdapter()
        items = [{"result": "fastmcp content"}, DummyToolResult(content="text"), 42]
        for item in items:
            result = adapter.normalize_error(item)
            assert result.is_error is False
            assert result.to_dict()["ok"] is True

    def test_passthrough_normalize_error_dict_with_ok_false(self) -> None:
        adapter = PassthroughAdapter()
        input_dict = {
            "ok": False,
            "error_code": "FASTMCP_SERVER_ERROR",
            "message": "handler failed",
        }
        result = adapter.normalize_error(input_dict)
        assert result.is_error is True
        assert result.error_code == "FASTMCP_SERVER_ERROR"
        assert result.error_message == "handler failed"
        assert result.to_dict()["ok"] is False

    def test_passthrough_normalize_error_tool_result_is_error(self) -> None:
        adapter = PassthroughAdapter()
        mock_result = DummyToolResult(content="Tool crashed", is_error=True)
        result = adapter.normalize_error(mock_result)
        assert result.is_error is True
        assert result.error_code == "TOOL_ERROR"
        assert result.error_message == "Tool crashed"

    def test_passthrough_normalize_error_never_raises(self) -> None:
        adapter = PassthroughAdapter()
        samples = [
            {"ok": False, "error": "failed"},
            {"ok": True, "data": 1},
            ValueError("boom"),
            None,
            42,
        ]
        for sample in samples:
            res = adapter.normalize_error(sample)
            assert isinstance(res, NormalizedError)

    def test_passthrough_normalize_exception_standard_and_custom(self) -> None:
        adapter = PassthroughAdapter()
        exceptions = [
            ValueError("FastMCP tool parameter missing"),
            RuntimeError("FastMCP server socket closed"),
        ]
        for exc in exceptions:
            result = adapter.normalize_exception(exc)
            assert result.is_error is True
            assert result.error_code == type(exc).__name__
            assert result.error_message == str(exc)
            assert result.to_dict()["ok"] is False
            assert result.to_dict()["error_code"] == type(exc).__name__
            assert result.to_dict()["message"] == str(exc)


class TestZeroFileIOAndPureContract:
    """Class 8: Tests for zero file I/O, frozen immutability, schema invariants, and dict access."""

    def test_zero_file_io_guarantee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        io_calls: list[tuple[str, Any]] = []

        def fake_open(*args: Any, **kwargs: Any) -> Any:
            io_calls.append(("open", args))
            raise AssertionError(f"Unexpected filesystem open call: {args}")

        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setattr(pathlib.Path, "open", fake_open)
        monkeypatch.setattr(os, "open", fake_open)

        adapters = [
            ConcreteTestAdapter(),
            BathosAdapter(),
            ContemplexAdapter(),
            XpeririAdapter(),
            MyxcelAdapter(),
            PassthroughAdapter(),
        ]

        for adapter in adapters:
            # Exercise success path
            res_ok = adapter.normalize_error({"ok": True, "result": "good"})
            assert res_ok.is_error is False

            # Exercise error path
            res_err = adapter.normalize_error(
                {"ok": False, "error": "broken", "message": "broken"}
            )
            assert res_err.is_error is True

            # Exercise exception path
            res_exc = adapter.normalize_exception(RuntimeError("purity test"))
            assert res_exc.is_error is True

        assert len(io_calls) == 0

    def test_normalized_error_frozen_immutability(self) -> None:
        err = NormalizedError(is_error=True, error_code="ERR", error_message="msg")
        assert not hasattr(err, "__dict__")
        assert err.__slots__ == (
            "is_error",
            "error_code",
            "error_message",
            "resolution_hint",
        )

        with pytest.raises((FrozenInstanceError, AttributeError)):
            err.is_error = False  # type: ignore[misc]

        with pytest.raises((FrozenInstanceError, AttributeError)):
            err.error_code = "OTHER"  # type: ignore[misc]

        with pytest.raises((AttributeError, TypeError)):
            err.arbitrary_attr = "val"  # type: ignore[attr-defined]

    def test_normalized_error_equality_and_hashing(self) -> None:
        err1 = NormalizedError(True, "CODE_A", "Message A", "Hint A")
        err2 = NormalizedError(True, "CODE_A", "Message A", "Hint A")
        err3 = NormalizedError(False, "CODE_B", "Message B")

        assert err1 == err2
        assert err1 != err3
        assert hash(err1) == hash(err2)
        assert len({err1, err2, err3}) == 2

    def test_to_dict_schema_invariants(self) -> None:
        err = NormalizedError(
            is_error=True,
            error_code="E_CODE",
            error_message="E_MSG",
            resolution_hint="HINT",
        )
        d = err.to_dict()
        assert isinstance(d, dict)
        assert d["ok"] is False
        assert d["error_code"] == "E_CODE"
        assert d["message"] == "E_MSG"
        assert d["resolution_hint"] == "HINT"

        err_no_hint = NormalizedError(is_error=False, error_code="", error_message="")
        d_no_hint = err_no_hint.to_dict()
        assert d_no_hint["ok"] is True
        assert d_no_hint["error_code"] == ""
        assert d_no_hint["message"] == ""
        assert d_no_hint["resolution_hint"] is None

    def test_normalized_error_dict_access(self) -> None:
        err = NormalizedError(
            is_error=True,
            error_code="ERR_1",
            error_message="Something went wrong",
            resolution_hint="Try again",
        )
        # __getitem__
        assert err["ok"] is False
        assert err["error_code"] == "ERR_1"
        assert err["message"] == "Something went wrong"
        assert err["resolution_hint"] == "Try again"

        # get
        assert err.get("ok") is False
        assert err.get("nonexistent", "fallback") == "fallback"

        # __contains__
        assert "ok" in err
        assert "error_code" in err
        assert "message" in err
        assert "resolution_hint" in err
        assert "nonexistent" not in err
