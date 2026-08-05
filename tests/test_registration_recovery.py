"""Tests for the recovery/reversal mechanism added to
``cisternal.registration.compose``/``wired`` (spec
``260805_nlm-adapter-transparent-auto-reauth.md``, "Spec A") and its
telemetry contextvar bridge (spec
``260805_nlm-adapter-recovery-telemetry-bridge.md``, "Spec B" AC1).

Acceptance criteria covered (Spec A unless noted):
    AC3            — non-recovered failures reversed via duck-typed
                     ``to_result()``, or propagate unchanged when absent.
    AC5/AC11       — ``is_recoverable`` returning False is a cheap check;
                     ``recover()`` is never called; handled per AC3.
    AC6/AC7/AC8    — ``is_recoverable`` True -> ``recover()`` -> retry
                     succeeds -> caller gets the retried result, no error.
    AC9            — ``recover()`` itself raises -> final failure per AC3,
                     on ``recover()``'s own exception.
    AC10           — the retry is a local, one-shot guard: a second failure
                     (of ANY exception type) is final, per AC3, on the
                     retry's own exception.
    AC12           — ``is_recoverable``/``recover`` run via
                     ``asyncio.to_thread`` on the MCP/async path, and
                     directly (same thread) on the CLI/sync path.
    AC13           — ``wire(..., recovery=(...))`` applies the SAME policy
                     uniformly to both the composed MCP callable and the CLI
                     closure, for both a recovery-eligible ("non-excluded")
                     and a non-eligible ("excluded" -- raises an
                     untranslated exception ``is_recoverable`` rejects)
                     dummy tool.
    Spec B AC1     — the recovery-telemetry contextvar
                     (``cisternal.telemetry.context._last_recovery_var``) is
                     set with the documented payload shape for the
                     "recovered"/"failed" outcomes, and left untouched
                     (never set) for the AC11 "not an attempt" case; the
                     CLI/sync leg never sets it (Spec B's CLI-path telemetry
                     is deferred).
    Backward compat — ``recovery=None`` (the default) is byte-identical to
                     the pre-recovery code path on both transports.
"""

from __future__ import annotations

import asyncio
import io
import threading
from unittest.mock import patch

import fastmcp
import pytest
from cyclopts import App

from cisternal.registration.compose import apply_recovery_sync, compose_mcp_callable
from cisternal.registration.decorator import tool as cisternal_tool
from cisternal.registration.registry import clear_registry
from cisternal.registration.wired import wire
from cisternal.telemetry.context import _last_recovery_var


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_recovery_contextvar():
    """Reset the recovery-telemetry contextvar before/after every test so no
    state leaks across tests sharing this thread's context."""
    _last_recovery_var.set(None)
    yield
    _last_recovery_var.set(None)


class _Translated(Exception):
    """Stands in for nlm-praxia-adapter's ``_translate_errors``-manufactured
    exception: carries the original dict-shaped payload and exposes the
    duck-typed ``to_result()`` AC3 checks for."""

    def __init__(self, payload: dict) -> None:
        super().__init__(str(payload))
        self._payload = payload

    def to_result(self) -> dict:
        return self._payload


# ---------------------------------------------------------------------------
# Backward compatibility: recovery=None is byte-identical to today
# ---------------------------------------------------------------------------


class TestRecoveryNoneBackwardCompatible:
    @pytest.mark.asyncio
    async def test_mcp_path_recovery_none_propagates_unaffected(self):
        def always_fails(x: int) -> int:
            raise _Translated({"status": "error", "error": "would have been reversed"})

        generated = compose_mcp_callable(always_fails)  # recovery defaults to None

        with pytest.raises(_Translated):
            await generated(1)

        # No recovery attempt was even possible -> contextvar untouched.
        assert _last_recovery_var.get() is None

    def test_cli_path_recovery_none_propagates_unaffected(self):
        def always_fails(x: int) -> int:
            raise _Translated({"status": "error", "error": "would have been reversed"})

        with pytest.raises(_Translated):
            apply_recovery_sync(always_fails, None, 1)

        assert _last_recovery_var.get() is None


# ---------------------------------------------------------------------------
# AC7/AC8: recovered after one retry (MCP + CLI legs)
# ---------------------------------------------------------------------------


class TestRecoveredAfterRetry:
    @pytest.mark.asyncio
    async def test_mcp_path_recovers_and_sets_contextvar(self):
        calls: list[int] = []
        recover_calls: list[bool] = []

        def flaky(x: int) -> int:
            calls.append(x)
            if len(calls) == 1:
                raise _Translated({"status": "error", "error": "session expired"})
            return x * 2

        def is_recoverable(exc: BaseException) -> bool:
            return isinstance(exc, _Translated)

        def recover() -> None:
            recover_calls.append(True)

        generated = compose_mcp_callable(
            flaky, recovery=(is_recoverable, recover), tool_name="flaky_tool"
        )
        result = await generated(21)

        assert result == 42, "AC8: caller gets the retried result, no error indication"
        assert recover_calls == [True], "AC7: recover() called before the retry"
        assert len(calls) == 2, "exactly one retry, no more"

        payload = _last_recovery_var.get()
        assert payload is not None, "Spec B AC1: contextvar set for a real attempt"
        assert payload["tool"] == "flaky_tool"
        assert payload["outcome"] == "recovered"
        assert payload["exc"] is None
        assert payload["duration_ms"] >= 0
        assert isinstance(payload["started_at"], int)

    def test_cli_path_recovers_without_setting_contextvar(self):
        calls: list[int] = []
        recover_calls: list[bool] = []

        def flaky(x: int) -> int:
            calls.append(x)
            if len(calls) == 1:
                raise _Translated({"status": "error", "error": "session expired"})
            return x * 2

        def is_recoverable(exc: BaseException) -> bool:
            return isinstance(exc, _Translated)

        def recover() -> None:
            recover_calls.append(True)

        result = apply_recovery_sync(flaky, (is_recoverable, recover), 21)

        assert result == 42
        assert recover_calls == [True]
        assert len(calls) == 2
        # Spec B Decision Log: CLI-path telemetry is deferred -- no owning
        # object exists yet on this path, so the contextvar is never set here.
        assert _last_recovery_var.get() is None


# ---------------------------------------------------------------------------
# AC5/AC11: is_recoverable() == False -> AC3, recover() never called
# ---------------------------------------------------------------------------


class TestIsRecoverableFalse:
    @pytest.mark.asyncio
    async def test_mcp_path_to_result_used_recover_not_called(self):
        recover_calls: list[bool] = []

        def always_fails(x: int) -> int:
            raise _Translated({"status": "error", "error": "not found"})

        def is_recoverable(exc: BaseException) -> bool:
            return False  # AC5: e.g. business failure, not auth-shaped

        def recover() -> None:
            recover_calls.append(True)

        generated = compose_mcp_callable(
            always_fails, recovery=(is_recoverable, recover), tool_name="always_fails"
        )
        result = await generated(1)

        assert result == {"status": "error", "error": "not found"}
        assert recover_calls == [], "AC11: recover() must never be called"
        # AC11 is not a recovery "attempt" -- Spec B AC1's outcome domain is
        # only {recovered, failed}, derived from AC8/AC9/AC10.
        assert _last_recovery_var.get() is None

    @pytest.mark.asyncio
    async def test_mcp_path_propagates_when_no_to_result(self):
        def always_fails(x: int) -> int:
            raise ValueError("plain, untranslated failure")

        def is_recoverable(exc: BaseException) -> bool:
            return False

        def recover() -> None:
            raise AssertionError("recover() must not be called")

        generated = compose_mcp_callable(
            always_fails, recovery=(is_recoverable, recover), tool_name="always_fails"
        )

        with pytest.raises(ValueError, match="plain, untranslated failure"):
            await generated(1)

        assert _last_recovery_var.get() is None


# ---------------------------------------------------------------------------
# AC9: recover() itself raises -> final failure on recover()'s own exception
# ---------------------------------------------------------------------------


class TestRecoverRaises:
    @pytest.mark.asyncio
    async def test_mcp_path_recover_exception_is_final_failure(self):
        class _RecoverFailed(Exception):
            def to_result(self) -> dict:
                return {"status": "error", "error": "reauth itself failed"}

        def always_fails(x: int) -> int:
            raise _Translated({"status": "error", "error": "session expired"})

        def is_recoverable(exc: BaseException) -> bool:
            return isinstance(exc, _Translated)

        def recover() -> None:
            raise _RecoverFailed()

        generated = compose_mcp_callable(
            always_fails, recovery=(is_recoverable, recover), tool_name="always_fails"
        )
        result = await generated(1)

        assert result == {"status": "error", "error": "reauth itself failed"}

        payload = _last_recovery_var.get()
        assert payload["outcome"] == "failed"
        assert payload["tool"] == "always_fails"
        assert isinstance(payload["exc"], _RecoverFailed)


# ---------------------------------------------------------------------------
# AC10: retry fails again (any exception type) -> no second retry
# ---------------------------------------------------------------------------


class TestRetryFailsAgain:
    @pytest.mark.asyncio
    async def test_mcp_path_no_second_retry_any_exception_type(self):
        calls: list[int] = []
        recover_calls: list[bool] = []

        def flaky_then_broken(x: int) -> int:
            calls.append(x)
            if len(calls) == 1:
                raise _Translated({"status": "error", "error": "session expired"})
            # AC10: the retry fails with a DIFFERENT, non-recoverable-shaped
            # exception -- must still not trigger a second retry.
            raise RuntimeError("retry hit an unrelated bug")

        def is_recoverable(exc: BaseException) -> bool:
            return isinstance(exc, _Translated)

        def recover() -> None:
            recover_calls.append(True)

        generated = compose_mcp_callable(
            flaky_then_broken, recovery=(is_recoverable, recover), tool_name="flaky2"
        )

        with pytest.raises(RuntimeError, match="retry hit an unrelated bug"):
            await generated(1)

        assert len(calls) == 2, "exactly one retry attempt, no second"
        assert recover_calls == [True]

        payload = _last_recovery_var.get()
        assert payload["outcome"] == "failed"
        assert isinstance(payload["exc"], RuntimeError)


# ---------------------------------------------------------------------------
# AC12: is_recoverable/recover offloaded via asyncio.to_thread (MCP) vs.
# invoked directly on the caller's thread (CLI)
# ---------------------------------------------------------------------------


class TestAC12ThreadOffload:
    def test_mcp_path_offloads_to_a_worker_thread(self):
        caller_thread = threading.get_ident()
        observed: list[tuple[str, int]] = []

        class _Boom(Exception):
            def to_result(self) -> dict:
                return {"status": "error", "recovered": False}

        def always_fails(x: int) -> int:
            raise _Boom("boom")

        def is_recoverable(exc: BaseException) -> bool:
            observed.append(("is_recoverable", threading.get_ident()))
            return True

        def recover() -> None:
            observed.append(("recover", threading.get_ident()))

        generated = compose_mcp_callable(
            always_fails, recovery=(is_recoverable, recover), tool_name="always_fails"
        )

        result = asyncio.run(generated(1))

        assert result == {"status": "error", "recovered": False}
        assert observed, "is_recoverable/recover should have run"
        for label, tid in observed:
            assert tid != caller_thread, (
                f"AC12: {label} ran on the event-loop thread; expected an "
                f"asyncio.to_thread offload"
            )

    def test_cli_path_runs_on_caller_thread_no_offload(self):
        caller_thread = threading.get_ident()
        observed: list[int] = []

        class _Boom(Exception):
            def to_result(self) -> dict:
                return {"status": "error"}

        def always_fails(x: int) -> int:
            raise _Boom("boom")

        def is_recoverable(exc: BaseException) -> bool:
            observed.append(threading.get_ident())
            return True

        def recover() -> None:
            observed.append(threading.get_ident())

        result = apply_recovery_sync(always_fails, (is_recoverable, recover), 1)

        assert result == {"status": "error"}
        assert observed, "is_recoverable/recover should have run"
        assert all(tid == caller_thread for tid in observed), (
            "AC12: CLI leg must invoke is_recoverable/recover directly, no offload"
        )


# ---------------------------------------------------------------------------
# AC13: wire()'s recovery= threaded uniformly into MCP + CLI, for both a
# recovery-eligible ("non-excluded") and non-eligible ("excluded") dummy tool
# ---------------------------------------------------------------------------


class TestWireRecoveryUniformAcrossTransports:
    """Mirrors the Assumptions-table obligation: 'a new test exercising
    recovery and the to_result() reversal for both an excluded and
    non-excluded dummy tool.'  wire() takes no per-tool exclusion parameter
    (that's an adapter-side, registration-time decision, AC13) -- here,
    "excluded" is simulated by a tool whose function raises an exception
    is_recoverable correctly rejects (as an excluded tool's untranslated
    exception would be, in the real adapter).
    """

    @pytest.fixture(autouse=True)
    def _cleanup(self):
        clear_registry(name="wire_recovery_mcp_test")
        clear_registry(name="wire_recovery_cli_test")
        yield
        clear_registry(name="wire_recovery_mcp_test")
        clear_registry(name="wire_recovery_cli_test")

    @pytest.mark.asyncio
    async def test_mcp_transport_recovers_eligible_propagates_excluded(self):
        eligible_calls: list[int] = []

        @cisternal_tool(registry="wire_recovery_mcp_test", name="eligible_tool")
        def eligible_tool(x: int) -> int:
            eligible_calls.append(x)
            if len(eligible_calls) == 1:
                raise _Translated({"status": "error", "error": "session expired"})
            return x + 100

        @cisternal_tool(registry="wire_recovery_mcp_test", name="excluded_tool")
        def excluded_tool(x: int) -> int:
            raise ValueError("excluded tool always fails raw")

        def is_recoverable(exc: BaseException) -> bool:
            return isinstance(exc, _Translated)

        recover_calls: list[bool] = []

        def recover() -> None:
            recover_calls.append(True)

        server = fastmcp.FastMCP("test-wire-recovery-mcp")
        result = wire(
            server,
            registry="wire_recovery_mcp_test",
            recovery=(is_recoverable, recover),
        )
        assert set(result.mcp_tools) == {"eligible_tool", "excluded_tool"}

        mcp_result = await server.call_tool("eligible_tool", {"x": 1})
        assert mcp_result.structured_content == {"result": 101}
        assert recover_calls == [True]

        with pytest.raises(Exception, match="excluded tool always fails raw"):
            await server.call_tool("excluded_tool", {"x": 1})
        # recover() was not invoked a second time for the excluded tool.
        assert recover_calls == [True]

    def test_cli_transport_recovers_eligible_exits_nonzero_for_excluded(self):
        eligible_calls: list[int] = []

        @cisternal_tool(registry="wire_recovery_cli_test", name="eligible_cli_tool")
        def eligible_cli_tool(x: int) -> str:
            # Returns a str (not int/bool) -- cyclopts's default result_action
            # treats an int/bool return as its own sys.exit() code, which is
            # a pre-existing cyclopts convention orthogonal to what this test
            # is checking (recovery, not cyclopts's result-action mapping).
            eligible_calls.append(x)
            if len(eligible_calls) == 1:
                raise _Translated({"status": "error", "error": "session expired"})
            return f"ok:{x + 100}"

        @cisternal_tool(registry="wire_recovery_cli_test", name="excluded_cli_tool")
        def excluded_cli_tool(x: int) -> int:
            raise ValueError("excluded cli tool always fails raw")

        def is_recoverable(exc: BaseException) -> bool:
            return isinstance(exc, _Translated)

        recover_calls: list[bool] = []

        def recover() -> None:
            recover_calls.append(True)

        server = fastmcp.FastMCP("test-wire-recovery-cli")
        app = App()
        wire(
            server,
            app,
            registry="wire_recovery_cli_test",
            recovery=(is_recoverable, recover),
        )

        # Eligible tool: CLI call transparently recovers -- clean exit(0).
        try:
            app(["eligible-cli-tool", "--x", "1"], exit_on_error=False)
        except SystemExit as se:
            assert se.code == 0, (
                f"Expected a clean exit for a transparently-recovered CLI "
                f"call, got {se.code}"
            )
        assert recover_calls == [True]
        assert len(eligible_calls) == 2

        # Excluded tool: raw ValueError -> AC3 propagation, unaffected by
        # recovery= -- F1's existing stderr + non-zero exit contract.
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            with pytest.raises(SystemExit) as exc_info:
                app(["excluded-cli-tool", "--x", "1"], exit_on_error=False)
        assert exc_info.value.code != 0
        assert "excluded cli tool always fails raw" in stderr_capture.getvalue()
        assert recover_calls == [True], "recover() must not fire for the excluded tool"
