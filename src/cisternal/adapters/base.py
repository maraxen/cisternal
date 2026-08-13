"""AdapterBase: Consumer-agnostic adapter protocol (spec §3.6, §5.4).

Each adapter owns the event-name set (ALLOWED_NAMES) and the response shape
for its consumer (shape_ok/shape_error). The MCP wrappers (CisternalMiddleware,
traced_tool) instantiate an adapter, delegate telemetry emission + shaping to it,
and never re-raise exceptions (CH-5).

(CH-9) Runtime name guard: emit_start/end/error check that the emitted name is
in self.ALLOWED_NAMES; on mismatch, calls _swallow_name_error (stderr warn + continue).
Tests monkeypatch _swallow_name_error to raise AssertionError instead.

emit_start/end/error guard their emit_event() call with a local try/except
(stderr warn + continue) so a telemetry failure can never break the caller
(all v2/v3 wrapper call sites can call these unguarded and still uphold
CH-5) -- defense in depth on top of emit_event's own never-raise contract.
This guard deliberately wraps only the emit_event() call, not the
ALLOWED_NAMES check/_swallow_name_error() above it, so the AC-NAMEFREEZE-4
test escape hatch (monkeypatching _swallow_name_error to raise) still
propagates normally.
"""

from abc import ABC, abstractmethod
import json
import re
import sys
from typing import Any

from cisternal import emit_event


# ---------------------------------------------------------------------------
# Defense-in-depth telemetry redaction (security review, 260805
# nlm-adapter-recovery-telemetry-bridge spec).
#
# emit_error() forwards str(exc) into whatever telemetry sink is configured
# (JSONL file, and optionally OTLP network egress via
# CISTERNAL_OTLP_ENDPOINT -- see telemetry/otlp_exporter.py). No confirmed
# live secret leak exists today, but at least one consumer wrapping a
# Google-auth-backed client embeds live session identifiers directly in
# request URLs (``f.sid=<value>``) and cookie-shaped auth tokens. A future
# exception type (in that consumer, or any other cisternal consumer) letting
# one of those raw values escape into str(exc) would otherwise be silently
# persisted/exported with nothing to catch it. This scrub runs once, here,
# so it applies uniformly regardless of which exporter is configured.
#
# Deliberately narrow: named, secret-shaped patterns only -- no generic
# high-entropy-token catch-all -- to avoid mangling ordinary error messages
# for cisternal's OTHER consumers (myxcel, xperiri, contemplex, bathos),
# whose exceptions have nothing to do with Google auth. A message with none
# of these patterns must pass through byte-identical.
# ---------------------------------------------------------------------------

_REDACTED = "[REDACTED]"

# Known Google auth cookie names (matches the consumer's own
# ESSENTIAL_COOKIES convention in notebooklm_tools/mcp/tools/_utils.py).
# Matched case-sensitively -- these are canonically upper/mixed-case; a
# case-insensitive match here would widen the blast radius for no benefit.
_GOOGLE_AUTH_COOKIE_NAMES = (
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
    "__Secure-OSID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "SAPISID",
    "APISID",
    "SIDCC",
    "HSID",
    "SSID",
    "OSID",
    "SID",
)

# Order within the alternation doesn't need to be longest-first: each
# alternative is anchored on a leading \b and a trailing literal "=", so
# e.g. "HSID=" can't spuriously match the "SID" alternative (no \b between
# H and S) and "SIDCC=" backtracks past the "SID" alternative (no "=" right
# after "SID") to match "SIDCC" instead.
_COOKIE_NAME_VALUE_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in _GOOGLE_AUTH_COOKIE_NAMES) + r")=([^;,\s\"']+)"
)

# `f.sid=<value>` / `sid=<value>` query-string session params (case-insensitive
# per the consumer's own URL construction, which lowercases these keys).
_SID_PARAM_RE = re.compile(r"\b(f\.sid|sid)=([^&\s\"'<>]+)", re.IGNORECASE)

# `Cookie: <...>` header values. Requires an "=" somewhere on the rest of
# the line so an unrelated message like "Cookie: header missing" (no "=")
# passes through unchanged rather than being over-redacted.
_COOKIE_HEADER_RE = re.compile(r"(?i)\bCookie:\s*(?=[^\r\n]*=)[^\r\n]+")

# `Authorization: Bearer <token>` -- redact the whole header value.
_AUTHORIZATION_BEARER_RE = re.compile(r"(?i)\bAuthorization:\s*Bearer\s+\S+")

# Bare `Bearer <token>` without an "Authorization:" prefix.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")


def _redact_secrets(text: str) -> str:
    """Scrub known secret-shaped substrings from *text* (defense in depth).

    Covers: Authorization/Bearer tokens, Cookie header values, named Google
    auth cookie NAME=value pairs, and sid/f.sid URL query params. Leaves
    the rest of the message intact for debuggability -- only the matched
    secret material is replaced with ``[REDACTED]``.

    A message containing none of these patterns is returned unchanged
    (byte-identical), by construction: each regex only fires on an actual
    pattern match, so no substitution occurs when nothing matches.

    Args:
        text: The candidate string (typically ``str(exc)``).

    Returns:
        The scrubbed string, safe to hand to a telemetry exporter.
    """
    if not text:
        return text
    redacted = _AUTHORIZATION_BEARER_RE.sub(f"Authorization: {_REDACTED}", text)
    redacted = _BEARER_RE.sub(_REDACTED, redacted)
    redacted = _COOKIE_HEADER_RE.sub(f"Cookie: {_REDACTED}", redacted)
    redacted = _COOKIE_NAME_VALUE_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", redacted)
    redacted = _SID_PARAM_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", redacted)
    return redacted


class AdapterBase(ABC):
    """Abstract base for MCP tool adapters (v3 middleware, v2 decorator, etc.).

    Each subclass defines:
    - ALLOWED_NAMES: frozenset[str] of event names this adapter may emit.
    - shape_ok(tool_name, result): Transform success response.
    - shape_error(tool_name, exc): Transform error response.
    """

    ALLOWED_NAMES: frozenset[str]

    def _safe_emit_event(self, name: str, **fields: Any) -> None:
        """Call emit_event(), guarding against it ever breaking the caller.

        emit_event() is documented never-raise; this is defense in depth in
        case that leaf contract is ever violated. Never call this to guard
        _swallow_name_error -- callers must check ALLOWED_NAMES and invoke
        _swallow_name_error() before calling this (see AC-NAMEFREEZE-4).
        """
        try:
            emit_event(name, **fields)
        except Exception as e:
            print(f"[cisternal] {name} emission failed: {e}", file=sys.stderr)

    def emit_start(self, tool_name: str, arg_keys: list[str], request_id: str) -> None:
        """Emit mcp.call_start event.

        Args:
            tool_name: Name of the tool being called.
            arg_keys: Sorted list of argument keys (spec §3.7, §3.8).
            request_id: Unique request ID for this invocation.
        """
        name = "mcp.call_start"
        if name not in self.ALLOWED_NAMES:
            self._swallow_name_error(name)
        self._safe_emit_event(name, tool=tool_name, arg_keys=arg_keys, request_id=request_id)

    def emit_end(self, tool_name: str, request_id: str, duration_ms: float) -> None:
        """Emit mcp.call_end event.

        Args:
            tool_name: Name of the tool that executed.
            request_id: The request ID from emit_start.
            duration_ms: Duration of execution in milliseconds.
        """
        name = "mcp.call_end"
        if name not in self.ALLOWED_NAMES:
            self._swallow_name_error(name)
        self._safe_emit_event(name, tool=tool_name, request_id=request_id, duration_ms=duration_ms)

    def emit_error(self, tool_name: str, request_id: str, exc: BaseException) -> None:
        """Emit mcp.tool_error event.

        ``exc_msg`` is passed through ``_redact_secrets`` before it reaches
        ``emit_event`` (and therefore any configured exporter -- JSONL and/or
        OTLP network egress) -- defense in depth against a future exception
        type letting a live secret (session id, auth cookie, bearer token)
        escape into ``str(exc)``. See module docstring above
        ``_redact_secrets`` for the full rationale.

        Args:
            tool_name: Name of the tool that raised.
            request_id: The request ID from emit_start.
            exc: The exception that was raised.
        """
        name = "mcp.tool_error"
        if name not in self.ALLOWED_NAMES:
            self._swallow_name_error(name)
        self._safe_emit_event(
            name,
            tool=tool_name,
            request_id=request_id,
            exc_type=type(exc).__name__,
            exc_msg=_redact_secrets(str(exc)),
        )

    @abstractmethod
    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape a successful tool result for the consumer.

        Args:
            tool_name: Name of the tool (for context).
            result: The result returned by the tool.

        Returns:
            Consumer-specific shaped response (dict, str, or other).
        """
        pass

    @abstractmethod
    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape an error response for the consumer (never re-raises).

        Args:
            tool_name: Name of the tool (for context).
            exc: The exception that was caught.
            **fields: Optional extra fields for the error envelope.

        Returns:
            Consumer-specific error shape (dict, str, or other).
        """
        pass

    def _swallow_name_error(self, name: str) -> None:
        """Handle illegal event name: log to stderr and return (warn-and-continue).

        Tests may monkeypatch this to raise AssertionError (AC-NAMEFREEZE-4).

        Args:
            name: The illegal event name.
        """
        print(f"[cisternal] ILLEGAL event name: {name!r}", file=sys.stderr)


class BathosAdapter(AdapterBase):
    """Adapter for bathos v3 middleware.

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: dict envelope with ok/error_code/error/resolution_hint.
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: merge dict results, add envelope fields.

        If result is a dict, spread it and add envelope.
        Otherwise, return minimal envelope.
        """
        if isinstance(result, dict):
            return {
                **result,
                "ok": True,
                "error_code": None,
                "error": None,
                "resolution_hint": None,
            }
        return {
            "ok": True,
            "error_code": None,
            "error": None,
            "resolution_hint": None,
        }

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: error envelope with error_code and message."""
        return {
            "ok": False,
            "error_code": "INTERNAL",
            "error": str(exc),
            "resolution_hint": "",
        }


class PassthroughAdapter(AdapterBase):
    """Adapter for a real FastMCP v3 server (bugfix, cisternal/mcp-middleware-fix).

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: pure passthrough. ``shape_ok`` returns whatever
    ``call_next`` produced completely unmodified -- critical against a real
    FastMCP server, where that value is a ``fastmcp.tools.tool.ToolResult``
    (never a ``dict``). Reshaping or discarding it -- as ``BathosAdapter``'s
    ``isinstance(result, dict)`` check does -- silently breaks every real
    tool call, since FastMCP's own mixins call ``.to_mcp_result()`` on
    whatever this adapter returns.

    Intended to be paired with ``CisternalMiddleware(reraise=True)``, so
    ``shape_error`` is never exercised in practice: the middleware re-raises
    the original exception itself before consulting the adapter. If used
    with ``reraise=False``, ``shape_error`` re-raises the original exception
    rather than trying to fabricate a dict-shaped error envelope that real
    FastMCP consumers wouldn't recognize as a ``ToolResult``.
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough, unmodified -- see class docstring."""
        return result

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: re-raise the original exception (no dict shape exists
        for a real FastMCP ``ToolResult`` error). Prefer
        ``CisternalMiddleware(reraise=True)``, which never calls this."""
        raise exc


class ContemplexAdapter(AdapterBase):
    """Adapter for contemplex v2 decorator (sync).

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: passthrough for success; err_envelope for error.
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough result unchanged."""
        return result

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: use contemplex err_envelope if available, else fallback.

        Tries to import contemplex.errors; if unavailable, returns basic dict.
        """
        try:
            from contemplex.errors import ErrorCode, err_envelope

            return err_envelope(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}")
        except ImportError:
            # Fallback if contemplex is not available
            return {"ok": False, "error_code": "INTERNAL", "error": str(exc)}


class XpeririAdapter(AdapterBase):
    """Adapter for xperiri v2 decorator (sync, JSON-string MCP returns).

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: JSON string for success and error (xperiri MCP tools return str).
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough str; serialize dict/other to JSON."""
        if isinstance(result, str):
            return result
        return json.dumps(result, sort_keys=True)

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: JSON string envelope matching xperiri error returns."""
        payload: dict[str, Any] = {"ok": False, "error": str(exc)}
        payload.update(fields)
        return json.dumps(payload, sort_keys=True)


class MyxcelAdapter(AdapterBase):
    """Adapter for myxcel v2 decorator (async MCP tools, dict returns).

    Event names (spec §4.2): mcp.call_start, mcp.call_end, mcp.tool_error.
    Response shape: dict passthrough; errors use {error, message} per myxcel.mcp_server._tool_error.
    """

    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough dict/list results (myxcel in-band errors included)."""
        if isinstance(result, (dict, list)):
            return result
        return {"result": result}

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: myxcel _tool_error envelope."""
        return {"error": type(exc).__name__, "message": str(exc)}
