"""MCP callable composition for the cisternal registration subsystem.

This module is responsible for taking a plain Python function (sync or async)
and producing the generated MCP-compatible callable that wraps it according to
the E2/E1 dispatch rules:

E2 (outer form):
    The generated callable is ALWAYS ``async def``.
    ``asyncio.iscoroutinefunction(generated) == True`` for both sync and async
    originals.

E1 (inner dispatch shim):
    - If the original is async: ``await fn(...)``
    - If the original is sync: ``fn(...)`` (direct call, no thread executor)

H1 (signature preservation):
    ``generated.__signature__`` is set EXPLICITLY to
    ``inspect.signature(original)`` because ``functools.update_wrapper`` does
    NOT copy ``__signature__``.  ``Annotated[]`` parameter metadata is
    preserved.  The return annotation is left untouched.

C5 (telemetry hard invariant):
    The generated callable MUST NOT call any telemetry methods
    (``adapter.emit_start``, ``emit_end``, ``emit_error``, ``shape_ok``,
    ``shape_error``, etc.).  All telemetry is owned by
    :class:`cisternal.adapters.v3_middleware.CisternalMiddleware`.

    The generated callable contains no references to adapters, middleware,
    telemetry, or any import that could trigger a telemetry *call*.  When
    ``recovery=`` is supplied (see R1 below), it DOES set a plain
    ``contextvars.ContextVar`` (``cisternal.telemetry.context._last_recovery_var``)
    as a cross-boundary signal for
    :class:`cisternal.adapters.v3_middleware.CisternalMiddleware` to read.
    Setting a contextvar is a signal, not a call to any adapter/telemetry
    method, so it does not violate the invariant above — see the companion
    recovery-telemetry-bridge spec (260805) for the full rationale.

R1 (recovery, optional):
    ``compose_mcp_callable(fn, recovery=(is_recoverable, recover))`` adds a
    transparent retry-once-after-recovery branch, exercised only when the
    first call to *fn* raises:

    - ``is_recoverable(exc)`` is invoked (off the event loop, via
      ``asyncio.to_thread``) to decide whether the failure is worth
      recovering from.  ``False`` -> the failure is final immediately (no
      ``recover()`` call).
    - ``True`` -> ``recover()`` is invoked (also via ``asyncio.to_thread``).
      If it raises, that exception is the final failure.  If it succeeds,
      *fn* is called exactly once more; any exception from that retry is
      final (no second retry — a per-invocation, non-shared guard: there is
      simply no loop, so a second attempt cannot happen).
    - Every final (non-recovered) failure is passed through
      ``getattr(exc, "to_result", None)``: if present, it is called and its
      return value is returned in place of the exception; if absent, the
      exception propagates exactly as it would with ``recovery=None``.
    - ``recovery=None`` (the default) makes the generated callable
      byte-identical to the no-recovery code path — a hard backward
      compatibility requirement for every other cisternal consumer.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from typing import Any, Callable, cast

from cisternal._typed_callable import NamedCallable, TaggedCallable
from cisternal.registration.shim import cli_dispatch, dispatch
from cisternal.telemetry.context import _last_recovery_var

RecoveryHooks = tuple[Callable[[BaseException], bool], Callable[[], None]]


def compose_mcp_callable(
    fn: Callable[..., Any],
    *,
    recovery: RecoveryHooks | None = None,
    tool_name: str | None = None,
) -> Callable[..., Any]:
    """Wrap *fn* in an MCP-compatible async callable.

    Applies E2 outer form (always async), E1 dispatch shim (await iff async),
    H1 signature copy (explicit ``__signature__``), and respects C5 (zero
    telemetry *calls* emitted by the generated callable).

    The generated callable is a pure passthrough: it calls through to the
    original via :func:`cisternal.registration.shim.dispatch` and does nothing
    else, UNLESS ``recovery=`` is supplied, in which case a failed call is
    retried once per R1's rules above.

    Args:
        fn: The original tool function (sync or async).
        recovery: Optional ``(is_recoverable, recover)`` pair (both
            synchronous callables — see R1 above).  ``None`` (default)
            preserves today's exact passthrough behaviour.
        tool_name: The name used to tag Spec B's recovery-telemetry
            contextvar payload (``payload["tool"]``).  Defaults to
            ``fn.__name__`` when omitted.  Callers that register the tool
            under an overridden name (``wire()``'s ``entry.name``, which can
            differ from ``fn.__name__``) should pass it explicitly so the
            telemetry ``tool`` field matches the name FastMCP actually
            dispatches on.

    Returns:
        A new ``async def`` callable whose ``__signature__`` matches *fn*.
        The generated callable has:

        - ``asyncio.iscoroutinefunction(generated) == True``  (E2)
        - ``generated.__signature__ == inspect.signature(fn)``  (H1)
        - ``generated.__wrapped__ == fn``  (traceability)
        - ``generated.__name__ == fn.__name__``  (via update_wrapper)
        - ``generated.__doc__ == fn.__doc__``  (via update_wrapper)
    """
    # Capture the original signature BEFORE wrapping so Annotated[] metadata
    # is preserved.  inspect.signature() follows __wrapped__ chains, so we
    # must capture it now.
    original_sig = inspect.signature(fn)
    name_for_telemetry = tool_name if tool_name is not None else getattr(
        fn, "__name__", "<unknown>"
    )

    # Define the generated MCP callable.  It is ALWAYS async (E2 outer form).
    # Inside, the E1 shim (dispatch) handles sync vs async originals.
    #
    # NOTE: We capture `fn` by closure.  There is no reference to any adapter,
    # middleware, or a telemetry *call* here.  C5 is satisfied (see R1 above
    # for the one, deliberate exception: a plain contextvar .set()).
    async def _mcp_callable(*args: Any, **kwargs: Any) -> Any:
        if recovery is None:
            # Byte-identical to the pre-recovery code path.
            return await dispatch(fn, *args, **kwargs)
        try:
            return await dispatch(fn, *args, **kwargs)
        except Exception as exc:
            return await _recover_async(
                fn, args, kwargs, exc, recovery, name_for_telemetry
            )

    # Step 1: apply functools.update_wrapper to copy __name__, __doc__,
    # __annotations__, __module__, __qualname__, and set __wrapped__.
    # update_wrapper does NOT set __signature__ — that comes in step 2.
    functools.update_wrapper(_mcp_callable, fn)

    # Step 2: explicitly set __signature__ to the original's signature (H1).
    # This is the ONLY way to preserve Annotated[] parameters and return
    # annotations for introspection by FastMCP and other tools.
    cast(TaggedCallable, _mcp_callable).__signature__ = original_sig

    return _mcp_callable


def _final_failure(exc: Exception) -> Any:
    """AC3: reverse a non-recovered failure via its duck-typed ``to_result()``,
    or let it propagate exactly as it does today for any other consumer that
    doesn't pass ``recovery=``.
    """
    to_result = getattr(exc, "to_result", None)
    if to_result is not None:
        return to_result()
    raise exc


def _set_recovery_context(
    tool_name: str, outcome: str, started_at: int, exc: Exception | None
) -> None:
    """Spec B AC1: set (never call anything on) the recovery-telemetry
    contextvar.  A plain ``ContextVar.set()`` is a signal, not a call to any
    adapter/telemetry method — see the C5 docstring note above.
    """
    duration_ms = (time.monotonic_ns() - started_at) / 1e6
    _last_recovery_var.set(
        {
            "tool": tool_name,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "exc": exc,
            "started_at": started_at,
        }
    )


async def _recover_async(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exc: Exception,
    recovery: RecoveryHooks,
    tool_name: str,
) -> Any:
    """AC5-AC12 (MCP/async leg): on a first-attempt failure, check
    ``is_recoverable``, call ``recover()`` if warranted, retry once, and
    reverse any non-recovered final failure via AC3's ``to_result()``
    duck-type.

    Sets Spec B's telemetry contextvar for exactly the two outcomes that
    constitute an actual recovery *attempt*: AC8 (recovered) and AC9/AC10
    (failed after ``recover()``/the retry).  AC11 (``is_recoverable`` returns
    ``False``) is not an attempt — ``recover()`` is never called — and does
    not touch the contextvar (matches Spec B AC1's `outcome` domain, which is
    derived only from AC8/AC9/AC10).
    """
    is_recoverable, recover = recovery

    # AC5/AC6, AC12: is_recoverable is synchronous; offload so the event loop
    # is never blocked by it.
    recoverable = await asyncio.to_thread(is_recoverable, exc)
    if not recoverable:
        # AC11 -> AC3, on the original exception. No recover() call, no
        # contextvar set (not an "attempt").
        return _final_failure(exc)

    started_at = time.monotonic_ns()
    try:
        # AC7, AC12: recover() is synchronous; offload.
        await asyncio.to_thread(recover)
    except Exception as recover_exc:
        # AC9 -> AC3, on recover()'s own exception.
        _set_recovery_context(tool_name, "failed", started_at, recover_exc)
        return _final_failure(recover_exc)

    try:
        # AC8/AC10: exactly one retry, via the same wrapped callable. No
        # shared/keyed state is needed — this is structurally a single retry
        # per invocation, in this call's own stack frame.
        result = await dispatch(fn, *args, **kwargs)
    except Exception as retry_exc:
        # AC10 -> AC3, on the retry's own exception (any exception type).
        _set_recovery_context(tool_name, "failed", started_at, retry_exc)
        return _final_failure(retry_exc)

    # AC8: retry succeeded — no error indication to the caller.
    _set_recovery_context(tool_name, "recovered", started_at, None)
    return result


def _recover_sync(call: Callable[[], Any], recovery: RecoveryHooks) -> Any:
    """AC5-AC12 (CLI/sync leg): synchronous counterpart to
    :func:`_recover_async`. ``is_recoverable``/``recover`` are invoked
    directly (no thread offload — the CLI path is already sync, AC12).

    Deliberately does NOT set the Spec B telemetry contextvar: the CLI path
    has no telemetry-owning object today (Spec B's Decision Log defers
    CLI-path telemetry — there is nothing analogous to
    ``CisternalMiddleware`` on this path yet). Recovery/retry still functions
    correctly here; only the telemetry signal is absent.
    """
    is_recoverable, recover = recovery
    try:
        return call()
    except Exception as exc:
        if not is_recoverable(exc):
            return _final_failure(exc)
        try:
            recover()
        except Exception as recover_exc:
            return _final_failure(recover_exc)
        try:
            return call()
        except Exception as retry_exc:
            return _final_failure(retry_exc)


def apply_recovery_sync(
    fn: NamedCallable,
    recovery: RecoveryHooks | None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """CLI-path entry point (AC13's CLI leg): dispatch *fn* synchronously via
    :func:`cisternal.registration.shim.cli_dispatch`, applying the same
    recovery policy as :func:`compose_mcp_callable` when *recovery* is not
    ``None``.  ``recovery=None`` calls ``cli_dispatch`` directly — the exact,
    unmodified pre-recovery CLI code path.
    """
    if recovery is None:
        return cli_dispatch(fn, *args, **kwargs)
    return _recover_sync(lambda: cli_dispatch(fn, *args, **kwargs), recovery)
