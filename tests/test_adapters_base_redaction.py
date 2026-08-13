"""Defense-in-depth telemetry redaction tests (security review of the
260805 nlm-adapter-recovery-telemetry-bridge spec).

``AdapterBase.emit_error`` forwards ``str(exc)`` into whatever telemetry
sink is configured (JSONL, and optionally OTLP network egress via
``CISTERNAL_OTLP_ENDPOINT``). These tests cover the ``_redact_secrets``
scrub applied to ``exc_msg`` before it reaches ``emit_event`` -- both as a
pure-function unit test and end-to-end through ``emit_error`` +
``ShadowExporter``, so a regression that re-inlines ``str(exc)`` directly
into ``_safe_emit_event`` (bypassing the scrub) would be caught.
"""

from __future__ import annotations

import time

import pytest

import cisternal
from cisternal.adapters.base import BathosAdapter, _redact_secrets
from cisternal.telemetry.exporter import ShadowExporter
from cisternal.telemetry.pipeline import shutdown_pipeline


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def _wait_for_tool_error(shadow: ShadowExporter, request_id: str, timeout: float = 1.0):
    """Poll for the mcp.tool_error record matching *request_id*.

    Filters by name+request_id rather than assuming the record of interest
    is shadow.records[-1] -- a lingering heartbeat thread from a prior
    test's pipeline can otherwise interleave a 'heartbeat' record into this
    test's fresh ShadowExporter and produce an order-dependent flake.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for record in shadow.records:
            if record.name == "mcp.tool_error" and record.fields.get("request_id") == request_id:
                return record
        time.sleep(0.01)
    raise AssertionError(f"mcp.tool_error record for request_id={request_id!r} never arrived")


# ---------------------------------------------------------------------------
# Unit tests: _redact_secrets is a pure function, no pipeline needed.
# ---------------------------------------------------------------------------


class TestRedactSecretsUnit:
    def test_sid_query_param_redacted(self) -> None:
        msg = "GET https://notebooklm.google.com/api?f.sid=abc123xyz&foo=bar failed"
        redacted = _redact_secrets(msg)
        assert "abc123xyz" not in redacted
        assert "f.sid=[REDACTED]" in redacted
        # Unrelated param survives untouched.
        assert "foo=bar" in redacted

    def test_bare_sid_query_param_redacted(self) -> None:
        msg = "request to /x?sid=deadbeef1234 timed out"
        redacted = _redact_secrets(msg)
        assert "deadbeef1234" not in redacted
        assert "sid=[REDACTED]" in redacted

    def test_cookie_header_redacted(self) -> None:
        msg = "upstream 403: Cookie: SID=fakevalue123; HSID=another"
        redacted = _redact_secrets(msg)
        assert "fakevalue123" not in redacted
        assert "another" not in redacted
        assert "Cookie: [REDACTED]" in redacted

    def test_cookie_header_without_equals_not_mangled(self) -> None:
        msg = "response missing Cookie: header entirely"
        assert _redact_secrets(msg) == msg

    def test_named_google_auth_cookie_pair_redacted(self) -> None:
        msg = "auth failed, __Secure-1PSID=some.opaque.value123 rejected"
        redacted = _redact_secrets(msg)
        assert "some.opaque.value123" not in redacted
        assert "__Secure-1PSID=[REDACTED]" in redacted

    def test_apisid_not_confused_with_sapisid(self) -> None:
        # SAPISID must be redacted as SAPISID=..., not partially matched as
        # a bogus "APISID=" starting mid-token.
        msg = "SAPISID=abc123; APISID=def456"
        redacted = _redact_secrets(msg)
        assert redacted == "SAPISID=[REDACTED]; APISID=[REDACTED]"

    def test_sidcc_not_truncated_to_sid(self) -> None:
        msg = "SIDCC=longtokenvalue"
        redacted = _redact_secrets(msg)
        assert redacted == "SIDCC=[REDACTED]"

    def test_authorization_bearer_header_redacted(self) -> None:
        msg = "call failed: Authorization: Bearer ya29.abcDEF-123_token"
        redacted = _redact_secrets(msg)
        assert "ya29.abcDEF-123_token" not in redacted
        assert "Authorization: [REDACTED]" in redacted

    def test_bare_bearer_token_redacted(self) -> None:
        msg = "rejected token, Bearer ya29.abcDEF-123_token was invalid"
        redacted = _redact_secrets(msg)
        assert "ya29.abcDEF-123_token" not in redacted
        assert "[REDACTED]" in redacted

    def test_plain_message_passes_through_byte_identical(self) -> None:
        msg = "file not found"
        assert _redact_secrets(msg) == msg
        assert _redact_secrets(msg) is not None

    def test_ordinary_exception_messages_pass_through_unchanged(self) -> None:
        for msg in [
            "file not found",
            "connection refused: myxcel.internal:9443",
            "ValueError: invalid literal for int() with base 10: 'abc'",
            "profile 'staging' not found in ~/.myxcel/profiles.toml",
            "bathos sidecar validation failed: temp_std out of range",
        ]:
            assert _redact_secrets(msg) == msg

    def test_empty_string_passthrough(self) -> None:
        assert _redact_secrets("") == ""


# ---------------------------------------------------------------------------
# Integration: emit_error -> _safe_emit_event -> pipeline -> exporter.
# Confirms the scrub is applied at the emission call site, uniformly for
# whatever exporter(s) are configured (ShadowExporter here stands in for
# JSONL/OTLP -- both receive the same already-redacted Record.fields).
# ---------------------------------------------------------------------------


class TestEmitErrorRedactsExcMsg:
    def test_emit_error_redacts_sid_before_reaching_exporter(self) -> None:
        shadow = ShadowExporter()
        cisternal.init(exporters=[shadow], heartbeat_interval=30.0)

        adapter = BathosAdapter()
        exc = ValueError("auth request failed: f.sid=abc123xyz&extra=1")
        adapter.emit_error("some_tool", "req-1", exc)

        record = _wait_for_tool_error(shadow, "req-1")
        assert "abc123xyz" not in record.fields["exc_msg"]
        assert "f.sid=[REDACTED]" in record.fields["exc_msg"]

    def test_emit_error_redacts_cookie_header_before_reaching_exporter(self) -> None:
        shadow = ShadowExporter()
        cisternal.init(exporters=[shadow], heartbeat_interval=30.0)

        adapter = BathosAdapter()
        exc = RuntimeError("upstream error: Cookie: SID=fakevalue123; HSID=another")
        adapter.emit_error("some_tool", "req-2", exc)

        record = _wait_for_tool_error(shadow, "req-2")
        assert "fakevalue123" not in record.fields["exc_msg"]
        assert "another" not in record.fields["exc_msg"]
        assert "Cookie: [REDACTED]" in record.fields["exc_msg"]

    def test_emit_error_passes_through_plain_message_byte_identical(self) -> None:
        shadow = ShadowExporter()
        cisternal.init(exporters=[shadow], heartbeat_interval=30.0)

        adapter = BathosAdapter()
        exc = FileNotFoundError("file not found")
        adapter.emit_error("some_tool", "req-3", exc)

        record = _wait_for_tool_error(shadow, "req-3")
        assert record.fields["exc_msg"] == "file not found"
