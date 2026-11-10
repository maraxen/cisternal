"""Adversarial stress harness for NormalizedError and AdapterBase (Milestone M2).

Stress tests:
1. NormalizedError: slotted frozen immutability, hashability in sets/dict keys,
   dict access (__getitem__, get, __contains__) on valid and missing keys, .to_dict().
2. AdapterBase.normalize_error: nested dicts, ambiguous types, generator objects,
   circular dicts across all adapters.
3. AdapterBase.normalize_exception: custom exceptions, unusual __str__, ANSI colors,
   control characters, secret redaction boundaries.
"""

from dataclasses import FrozenInstanceError
from enum import Enum
import pytest
from typing import Any

from cisternal.adapters.base import (
    AdapterBase,
    BathosAdapter,
    ContemplexAdapter,
    MyxcelAdapter,
    NormalizedError,
    PassthroughAdapter,
    XpeririAdapter,
)


class ConcreteAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        return result

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        return {"error": str(exc)}


class DummyToolResult:
    def __init__(self, content: Any = "", is_error: bool = False) -> None:
        self.content = content
        self.is_error = is_error


class SampleEnum(Enum):
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"


# ============================================================================
# Section 1: NormalizedError Slotted Frozen Immutability & Dict Access
# ============================================================================


class TestNormalizedErrorImmutabilityAndAccess:
    """Stress test NormalizedError dataclass contracts."""

    def test_slotted_frozen_immutability(self) -> None:
        err = NormalizedError(
            is_error=True,
            error_code="ERR_CODE",
            error_message="message",
            resolution_hint="hint",
        )
        # Slotted verification
        assert not hasattr(err, "__dict__")
        assert err.__slots__ == (
            "is_error",
            "error_code",
            "error_message",
            "resolution_hint",
        )

        # Mutation of defined fields must fail
        with pytest.raises(FrozenInstanceError):
            err.is_error = False  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            err.error_code = "OTHER"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            err.error_message = "other message"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            err.resolution_hint = "other hint"  # type: ignore[misc]

        # Setting arbitrary new attribute must fail
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            err.extra_field = 123  # type: ignore[attr-defined]

        # Deleting attributes must fail
        with pytest.raises((FrozenInstanceError, AttributeError)):
            del err.error_code  # type: ignore[misc]

    def test_hashability_in_sets_and_dict_keys(self) -> None:
        err1 = NormalizedError(True, "CODE_A", "Message A", "Hint A")
        err2 = NormalizedError(True, "CODE_A", "Message A", "Hint A")
        err3 = NormalizedError(False, "CODE_B", "Message B")

        # Set deduplication
        s = {err1, err2, err3}
        assert len(s) == 2
        assert err1 in s
        assert err3 in s

        # Dict key usage
        d = {err1: "val1", err3: "val3"}
        assert d[err2] == "val1"
        assert len(d) == 2

    def test_to_dict_schema_adherence_and_boolean_negation(self) -> None:
        # Error instance: is_error=True -> ok=False
        err_true = NormalizedError(
            is_error=True,
            error_code="ERR_FAIL",
            error_message="Something failed",
            resolution_hint="Retry later",
        )
        d_true = err_true.to_dict()
        assert d_true == {
            "ok": False,
            "error_code": "ERR_FAIL",
            "message": "Something failed",
            "resolution_hint": "Retry later",
        }
        assert isinstance(d_true["ok"], bool)
        assert d_true["ok"] is False

        # Success instance: is_error=False -> ok=True
        err_false = NormalizedError(
            is_error=False,
            error_code="",
            error_message="",
            resolution_hint=None,
        )
        d_false = err_false.to_dict()
        assert d_false == {
            "ok": True,
            "error_code": "",
            "message": "",
            "resolution_hint": None,
        }
        assert isinstance(d_false["ok"], bool)
        assert d_false["ok"] is True

    def test_dict_access_valid_and_missing_keys(self) -> None:
        err = NormalizedError(
            is_error=True,
            error_code="CUSTOM_ERR",
            error_message="Custom error msg",
            resolution_hint="Fix configuration",
        )

        # 1. Valid keys according to to_dict schema
        assert err["ok"] is False
        assert err["error_code"] == "CUSTOM_ERR"
        assert err["message"] == "Custom error msg"
        assert err["resolution_hint"] == "Fix configuration"

        # 2. Missing keys must raise KeyError
        with pytest.raises(KeyError):
            _ = err["nonexistent_key"]

        with pytest.raises(KeyError):
            _ = err["code"]

        with pytest.raises(KeyError):
            _ = err["hint"]

        # 3. get() method
        assert err.get("ok") is False
        assert err.get("error_code") == "CUSTOM_ERR"
        assert err.get("message") == "Custom error msg"
        assert err.get("resolution_hint") == "Fix configuration"
        assert err.get("missing", "default_val") == "default_val"

        # 4. __contains__ (in operator)
        assert "ok" in err
        assert "error_code" in err
        assert "message" in err
        assert "resolution_hint" in err
        assert "missing" not in err

    def test_dict_access_is_error_key_behavior(self) -> None:
        """Empirical probe of err['is_error'] access.

        In NormalizedError, to_dict() returns {"ok": not self.is_error, ...}
        rather than {"is_error": self.is_error, ...}.
        Therefore, err['is_error'] raises KeyError.
        """
        err = NormalizedError(
            is_error=True,
            error_code="ERR",
            error_message="msg",
        )
        # Attribute access works
        assert err.is_error is True

        # Dict subscript access currently raises KeyError because to_dict() keys are ('ok', 'error_code', 'message', 'resolution_hint')
        with pytest.raises(KeyError):
            _ = err["is_error"]

        assert err.get("is_error") is None
        assert "is_error" not in err


# ============================================================================
# Section 2: AdapterBase.normalize_error Nested & Ambiguous Types
# ============================================================================


class TestNormalizeErrorNestedAndAmbiguous:
    """Stress test normalize_error against nested dicts, ambiguous types, circular dicts."""

    @pytest.fixture
    def adapters(self) -> list[tuple[str, AdapterBase]]:
        return [
            ("Base", ConcreteAdapter()),
            ("Bathos", BathosAdapter()),
            ("Contemplex", ContemplexAdapter()),
            ("Xperiri", XpeririAdapter()),
            ("Myxcel", MyxcelAdapter()),
            ("Passthrough", PassthroughAdapter()),
        ]

    def test_nested_dictionaries_not_treated_as_tool_errors(
        self, adapters: list[tuple[str, AdapterBase]]
    ) -> None:
        """Data rows containing error strings must NOT be treated as top-level errors."""
        nested_samples = [
            {"rows": [{"error": "fail"}]},
            {"data": {"is_error": True, "error_code": "FAIL"}},
            {"results": [{"status": "error", "message": "query failed"}]},
            {"payload": {"ok": False}},
            {"nested": {"nested2": {"code": "ERR", "error": "broken"}}},
        ]
        for name, adapter in adapters:
            for sample in nested_samples:
                res = adapter.normalize_error(sample)
                assert res.is_error is False, (
                    f"{name} treated nested error in {sample} as top-level error: {res}"
                )
                assert res.to_dict()["ok"] is True

    def test_ambiguous_primitive_types(
        self, adapters: list[tuple[str, AdapterBase]]
    ) -> None:
        """Primitive types (ints, booleans, floats, None, lists) must not cause errors or crash."""
        primitives = [
            0,
            1,
            -1,
            42,
            0.0,
            3.14,
            float("nan"),
            float("inf"),
            True,
            False,
            None,
            [],
            [1, 2, 3],
            [{"error": "fail"}],
            (),
            set(),
            b"binary data",
        ]
        for name, adapter in adapters:
            for prim in primitives:
                res = adapter.normalize_error(prim)
                assert res.is_error is False, (
                    f"{name} treated primitive {prim!r} as error: {res}"
                )
                assert res.to_dict()["ok"] is True

    def test_ambiguous_dictionary_structures(self) -> None:
        adapter = ConcreteAdapter()

        # Empty dict
        empty_res = adapter.normalize_error({})
        assert empty_res.is_error is False
        assert empty_res.to_dict()["ok"] is True

        # ok: None without error code -> success
        res_ok_none = adapter.normalize_error({"ok": None})
        assert res_ok_none.is_error is False

        # ok: None WITH error code -> treated as error
        res_ok_none_code = adapter.normalize_error(
            {"ok": None, "error_code": "TIMEOUT"}
        )
        assert res_ok_none_code.is_error is True
        assert res_ok_none_code.error_code == "TIMEOUT"

        # error_code: "" (empty string) without ok=False -> success
        res_empty_code = adapter.normalize_error({"error_code": ""})
        assert res_empty_code.is_error is False

        # ok: False with empty error code -> error with fallback UNKNOWN_ERROR
        res_ok_false_empty_code = adapter.normalize_error(
            {"ok": False, "error_code": ""}
        )
        assert res_ok_false_empty_code.is_error is True
        assert res_ok_false_empty_code.error_code == "UNKNOWN_ERROR"

        # Integer code
        res_int_code = adapter.normalize_error({"ok": False, "code": 503})
        assert res_int_code.is_error is True
        assert res_int_code.error_code == "503"

        # Enum code
        res_enum_code = adapter.normalize_error(
            {"ok": False, "code": SampleEnum.RESOURCE_EXHAUSTED}
        )
        assert res_enum_code.is_error is True
        assert res_enum_code.error_code == "RESOURCE_EXHAUSTED"

        # ok: True with error_code present -> ok: True overrides
        res_ok_true_with_code = adapter.normalize_error(
            {"ok": True, "error_code": "IGNORED_ERR"}
        )
        assert res_ok_true_with_code.is_error is False

    def test_generator_objects(self, adapters: list[tuple[str, AdapterBase]]) -> None:
        """Generator objects should not crash normalize_error or be exhausted."""
        for name, adapter in adapters:

            def make_gen():
                yield from range(5)

            gen = make_gen()
            res = adapter.normalize_error(gen)
            assert res.is_error is False
            # Verify generator was not consumed
            assert next(gen) == 0

    def test_circular_dictionaries_do_not_crash(
        self, adapters: list[tuple[str, AdapterBase]]
    ) -> None:
        """Circular dictionary structures must not cause infinite recursion."""
        circ: dict[str, Any] = {"status": "ok"}
        circ["self"] = circ

        circ_err: dict[str, Any] = {"ok": False, "message": "broken"}
        circ_err["self"] = circ_err

        for name, adapter in adapters:
            # Success circular dict
            res_ok = adapter.normalize_error(circ)
            assert res_ok.is_error is False

            # Error circular dict
            res_err = adapter.normalize_error(circ_err)
            assert res_err.is_error is True


# ============================================================================
# Section 3: Subclass Specific Normalization Edge Cases
# ============================================================================


class TestSubclassAdapterEdgeCases:
    """Stress test specific subclass overrides for Bathos, Contemplex, Xperiri, Myxcel, Passthrough."""

    def test_bathos_adapter_edge_cases(self) -> None:
        adapter = BathosAdapter()

        # Missing error_code falls back to INTERNAL
        res1 = adapter.normalize_error({"ok": False, "error": "query syntax error"})
        assert res1.is_error is True
        assert res1.error_code == "INTERNAL"
        assert res1.error_message == "query syntax error"

        # Bare error field without ok
        res2 = adapter.normalize_error({"error": "unhandled sqlite failure"})
        assert res2.is_error is True
        assert res2.error_code == "INTERNAL"

        # ok: True with error field is immune
        res3 = adapter.normalize_error({"ok": True, "error": "historical log error"})
        assert res3.is_error is False

    def test_contemplex_adapter_edge_cases(self) -> None:
        adapter = ContemplexAdapter()

        # Error type resolved
        res1 = adapter.normalize_error({"error_type": "SESSION_CORRUPT"})
        assert res1.is_error is True
        assert res1.error_code == "SESSION_CORRUPT"

        # Enum error_code
        res2 = adapter.normalize_error(
            {"ok": False, "error_code": SampleEnum.INVALID_ARGUMENT}
        )
        assert res2.is_error is True
        assert res2.error_code == "INVALID_ARGUMENT"

        # ok: True immunity
        res3 = adapter.normalize_error({"ok": True, "error_type": "SESSION_CORRUPT"})
        assert res3.is_error is False

    def test_xperiri_adapter_edge_cases(self) -> None:
        adapter = XpeririAdapter()

        # Malformed JSON strings must not crash
        assert adapter.normalize_error("").is_error is False
        assert adapter.normalize_error("   ").is_error is False
        assert adapter.normalize_error("{invalid json").is_error is False
        assert adapter.normalize_error("null").is_error is False
        assert adapter.normalize_error("123").is_error is False
        assert adapter.normalize_error("false").is_error is False
        assert adapter.normalize_error("[1, 2]").is_error is False

        # JSON error envelope
        res_json_err = adapter.normalize_error(
            '{"ok": false, "error": "xperiri engine failed"}'
        )
        assert res_json_err.is_error is True
        assert res_json_err.error_code == "INTERNAL"
        assert res_json_err.error_message == "xperiri engine failed"

    def test_myxcel_adapter_edge_cases(self) -> None:
        adapter = MyxcelAdapter()

        # Non-empty string error field
        res1 = adapter.normalize_error({"error": "SLURM node failed"})
        assert res1.is_error is True
        assert res1.error_code == "MYXCEL_ERROR"
        assert res1.error_message == "SLURM node failed"

        # Non-string error field ignored
        res2 = adapter.normalize_error({"error": 12345})
        assert res2.is_error is False

        # Empty error field ignored
        res3 = adapter.normalize_error({"error": ""})
        assert res3.is_error is False

        # None error field ignored
        res4 = adapter.normalize_error({"error": None})
        assert res4.is_error is False

        # ok: True immunity overrides error field
        res5 = adapter.normalize_error({"ok": True, "error": "SLURM node failed"})
        assert res5.is_error is False

    def test_passthrough_adapter_edge_cases(self) -> None:
        adapter = PassthroughAdapter()

        # FastMCP ToolResult duck-typing
        res1 = adapter.normalize_error(DummyToolResult("tool boom", is_error=True))
        assert res1.is_error is True
        assert res1.error_code == "TOOL_ERROR"
        assert res1.error_message == "tool boom"

        # ToolResult with content as complex object
        res2 = adapter.normalize_error(
            DummyToolResult([{"type": "text", "text": "error detail"}], is_error=True)
        )
        assert res2.is_error is True
        assert "error detail" in res2.error_message

        # ToolResult is_error=False
        res3 = adapter.normalize_error(DummyToolResult("success", is_error=False))
        assert res3.is_error is False

        # Never raises during normalize_error
        for val in [ValueError("x"), None, 42, {"ok": False}]:
            out = adapter.normalize_error(val)
            assert isinstance(out, NormalizedError)


# ============================================================================
# Section 4: AdapterBase.normalize_exception Custom Exceptions & Formatting
# ============================================================================


class TestNormalizeExceptionAdversarial:
    """Stress test normalize_exception with unusual __str__, ANSI codes, control chars."""

    @pytest.fixture
    def adapter(self) -> AdapterBase:
        return ConcreteAdapter()

    def test_base_exceptions_normalized(self, adapter: AdapterBase) -> None:
        """Standard and BaseException subclasses normalized with is_error=True."""
        exceptions = [
            ValueError("invalid argument"),
            KeyError("missing_key"),
            KeyboardInterrupt("cancelled by user"),
            SystemExit(2),
        ]
        for exc in exceptions:
            res = adapter.normalize_exception(exc)
            assert res.is_error is True
            assert res.error_code == type(exc).__name__
            assert str(exc) in res.error_message or repr(exc) in res.error_message
            assert res.resolution_hint is None
            assert res.to_dict()["ok"] is False

    def test_exceptions_with_unusual_str(self, adapter: AdapterBase) -> None:
        # Unicode and emojis
        res_uni = adapter.normalize_exception(Exception("Unicode: 💥 🚀 日本語 错误"))
        assert res_uni.error_message == "Unicode: 💥 🚀 日本語 错误"

        # Empty string
        res_empty = adapter.normalize_exception(Exception(""))
        assert res_empty.error_message == ""

        # Multiline string
        res_multi = adapter.normalize_exception(Exception("Line 1\nLine 2\nLine 3"))
        assert res_multi.error_message == "Line 1\nLine 2\nLine 3"

        # Multiple arguments
        res_args = adapter.normalize_exception(
            Exception("code", 404, {"detail": "lost"})
        )
        assert "404" in res_args.error_message

        # Dynamic exception class
        DynamicErr = type("DynamicClusterError", (Exception,), {})
        res_dyn = adapter.normalize_exception(DynamicErr("cluster dead"))
        assert res_dyn.error_code == "DynamicClusterError"
        assert res_dyn.error_message == "cluster dead"

    def test_exceptions_with_ansi_and_control_characters(
        self, adapter: AdapterBase
    ) -> None:
        # Embedded ANSI color codes
        ansi_msg = "\x1b[31;1mFatal:\x1b[0m \x1b[33mdisk full\x1b[0m"
        res_ansi = adapter.normalize_exception(RuntimeError(ansi_msg))
        assert res_ansi.error_message == ansi_msg
        assert res_ansi.error_code == "RuntimeError"

        # Control characters: null byte, bell, backspace, form feed, carriage return
        ctrl_msg = "Error:\x00null\x07bell\x08bs\x0cff\r\nline"
        res_ctrl = adapter.normalize_exception(ValueError(ctrl_msg))
        assert res_ctrl.error_message == ctrl_msg

        # Terminal title escape
        term_msg = "\x1b]0;TermTitle\x07Body error"
        res_term = adapter.normalize_exception(Exception(term_msg))
        assert res_term.error_message == term_msg

    def test_secret_redaction_in_exceptions(self, adapter: AdapterBase) -> None:
        # Plain Bearer token
        res_bearer = adapter.normalize_exception(
            Exception("Unauthorized: Bearer secret_token_value_12345")
        )
        assert "secret_token_value_12345" not in res_bearer.error_message
        assert "[REDACTED]" in res_bearer.error_message

        # Authorization: Bearer
        res_auth = adapter.normalize_exception(
            Exception("Header Authorization: Bearer sk-ant-secret-999")
        )
        assert "sk-ant-secret-999" not in res_auth.error_message
        assert "Authorization: [REDACTED]" in res_auth.error_message

        # Cookie
        res_cookie = adapter.normalize_exception(
            Exception("Cookie: session_id=secret_session_abc")
        )
        assert "secret_session_abc" not in res_cookie.error_message
        assert "Cookie: [REDACTED]" in res_cookie.error_message

    def test_broken_str_exception_behavior(self, adapter: AdapterBase) -> None:
        """An exception whose __str__ raises an exception propagates out of normalize_exception.

        Documents that normalize_exception calls str(exc) directly without a try/except fallback.
        """

        class ExplodingStrException(Exception):
            def __str__(self) -> str:
                raise RuntimeError("Exploding __str__")

        broken_exc = ExplodingStrException("message")
        with pytest.raises(RuntimeError, match="Exploding __str__"):
            adapter.normalize_exception(broken_exc)
