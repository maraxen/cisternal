"""Wire entry point for the cisterna registration subsystem.

``cisterna.wire()`` is the main user-facing API for producing transport
registrations from a registry snapshot.

Behaviour (C6 — snapshot semantics):
    ``wire()`` takes a point-in-time snapshot of the named registry via
    :func:`cisterna.registration.registry._snapshot`.  Tools decorated with
    ``@cisterna.tool`` *after* ``wire()`` is called are NOT included in the
    wired server; they are invisible to it.

Error contract:
    If caller passes ``expected=["tool_a", "tool_b"]`` and any of those names
    are not present in the registry snapshot, ``wire()`` raises
    :class:`cisterna.registration.errors.CisternaWireError` with
    ``missing=[<absent names>]`` (when ``validate=True``), or logs a WARNING
    and continues (when ``validate=False``).

Transport:
    The generated MCP callables are registered on the caller-supplied
    ``fastmcp.FastMCP`` server.  The CLI callables are registered on the
    caller-supplied ``cyclopts.App`` (if any).

HARD INVARIANT (C5 / AC-M2-6):
    ``wire()`` and the callables it registers MUST NOT call any adapter methods
    (``adapter.emit_start``, ``emit_end``, ``emit_error``, ``shape_ok``,
    ``shape_error``, etc.) or any other telemetry mechanism.  All telemetry is
    owned by :class:`cisterna.adapters.v3_middleware.CisternaMiddleware`.  The
    ``adapter`` parameter is accepted here for forward-compat but is
    intentionally NEVER used.
"""

from __future__ import annotations

import inspect
import logging
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cisterna.registration.compose import compose_mcp_callable
from cisterna.registration.errors import CisternaWireError
from cisterna.registration.registry import _snapshot

if TYPE_CHECKING:
    pass

_log = logging.getLogger("cisterna.registration")


# ---------------------------------------------------------------------------
# WiredRegistry — observable/testable return value (TBD-M2-5)
# ---------------------------------------------------------------------------


@dataclass
class WiredRegistry:
    """Introspection object returned by :func:`wire`.

    Attributes:
        registry_name: The registry partition that was snapshotted.
        mcp_tools:     Names of tools registered on the FastMCP server.
        cli_commands:  Names of CLI commands registered on the cyclopts App
                       (empty if *app* was not supplied to ``wire()``).
    """

    registry_name: str
    mcp_tools: list[str] = field(default_factory=list)
    cli_commands: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# wire()
# ---------------------------------------------------------------------------


def wire(
    server: Any,
    app: Any = None,
    *,
    adapter: Any = None,  # accepted but NEVER used — see C5/AC-M2-6 note above
    registry: str = "default",
    expected: list[str] | None = None,
    validate: bool = True,
) -> WiredRegistry:
    """Snapshot the named registry and register each tool on *server* (and *app*).

    Steps:
        1. Take a point-in-time snapshot of *registry* via
           :func:`~cisterna.registration.registry._snapshot`.
        2. For each entry in the snapshot: produce an MCP callable via
           :func:`~cisterna.registration.compose.compose_mcp_callable` and
           register it on *server* using ``server.add_tool(callable)``.
        3. If *app* is given: register a CLI command per entry via
           ``app.command(name=entry.name)(entry.fn)``.  The CLI callable is
           a PASSTHROUGH to the original function; it does NOT emit telemetry
           (C5 / AC-M2-6).
        4. Validate *expected* names (AC-M2-9 / AC-M2-10).
        5. Return a :class:`WiredRegistry` instance (TBD-M2-5).

    HARD INVARIANT (C5 / AC-M2-6):
        This function and the callables it registers MUST NOT call any adapter
        methods or emit any telemetry.  The *adapter* parameter is accepted for
        forward-compat and is intentionally never used.

    Args:
        server:    A ``fastmcp.FastMCP`` instance (or any object with an
                   ``add_tool`` method).  Registered MCP callables are added
                   here.
        app:       Optional ``cyclopts.App``.  When supplied, a CLI command is
                   registered for each tool entry.  The CLI callable is a pure
                   passthrough to the original function.
        adapter:   Accepted but NEVER used (C5 / AC-M2-6).  Pass ``None``
                   (default).  Passing a non-None value is silently ignored.
        registry:  Which named registry partition to snapshot.  Defaults to
                   ``"default"``.
        expected:  Optional list of tool names that must be present in the
                   snapshot.  Controls validation behaviour together with
                   *validate*.
        validate:  When ``True`` (default) and *expected* names are missing:
                   raise :class:`CisternaWireError`.  When ``False``: log a
                   WARNING to ``cisterna.registration`` and continue.

    Returns:
        A :class:`WiredRegistry` recording which tools were wired.

    Raises:
        CisternaWireError: If *expected* names are absent from the snapshot
            and ``validate=True``.
    """
    # C6: snapshot at wire-time; post-wire decorations are excluded.
    snapshot = _snapshot(registry)

    # Validation: check expected names against the snapshot (AC-M2-9 / AC-M2-10).
    if expected is not None:
        missing = [n for n in expected if n not in snapshot]
        if missing:
            if validate:
                raise CisternaWireError(missing=missing)
            else:
                _log.warning(
                    "cisterna.wire(): expected tools not found in registry %r: %s",
                    registry,
                    missing,
                )

    mcp_tool_names: list[str] = []
    cli_command_names: list[str] = []

    for entry in snapshot.values():
        # Generate the async MCP callable (E2/E1/H1 guarantees from compose).
        mcp_callable = compose_mcp_callable(entry.fn)

        # Register on the FastMCP server (same API used in test_registration_compose.py).
        server.add_tool(mcp_callable)
        mcp_tool_names.append(entry.name)

        # Register CLI command if app is supplied.
        # F1 dual error contract (CLI path):
        #   - The CLI callable wraps exceptions into a clean CLI failure:
        #     it writes a concise message to stderr and calls sys.exit(1).
        #   - It does NOT emit telemetry (C5 / AC-M2-6).
        #   - The MCP callable (above) is an unmodified passthrough — MCP
        #     exceptions propagate to FastMCP/CisternaMiddleware, which is
        #     M1's responsibility.
        if app is not None:
            # Capture entry.fn in the closure to avoid late-binding.
            _fn = entry.fn
            _name = entry.name

            def _make_cli_cmd(original_fn: Any) -> Any:
                def _cli_cmd(*args: Any, **kwargs: Any) -> Any:
                    # F1 CLI error contract: wrap exceptions into a clean exit.
                    # No telemetry emitted here (C5 / AC-M2-6).
                    from cisterna.registration.shim import cli_dispatch

                    try:
                        return cli_dispatch(original_fn, *args, **kwargs)
                    except SystemExit:
                        # Re-raise SystemExit unchanged (already a clean exit).
                        raise
                    except Exception as exc:
                        # F1: convert any other exception into a non-zero exit.
                        # Write a concise message to stderr (do NOT swallow).
                        print(
                            f"Error ({type(exc).__name__}): {exc}",
                            file=sys.stderr,
                        )
                        sys.exit(1)

                _cli_cmd.__name__ = original_fn.__name__
                _cli_cmd.__doc__ = original_fn.__doc__
                _cli_cmd.__signature__ = inspect.signature(original_fn)  # type: ignore[attr-defined]
                _cli_cmd.__annotations__ = dict(original_fn.__annotations__)
                return _cli_cmd

            cli_cmd = _make_cli_cmd(_fn)
            app.command(name=_name)(cli_cmd)
            cli_command_names.append(_name)

    return WiredRegistry(
        registry_name=registry,
        mcp_tools=mcp_tool_names,
        cli_commands=cli_command_names,
    )
