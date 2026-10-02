"""Wire entry point for the cisternal registration subsystem.

``cisternal.wire()`` is the main user-facing API for producing transport
registrations from a registry snapshot.

Behaviour (C6 — snapshot semantics):
    ``wire()`` takes a point-in-time snapshot of the named registry via
    :func:`cisternal.registration.registry._snapshot`.  Tools decorated with
    ``@cisternal.tool`` *after* ``wire()`` is called are NOT included in the
    wired server; they are invisible to it.

Error contract:
    If caller passes ``expected=["tool_a", "tool_b"]`` and any of those names
    are not present in the registry snapshot, ``wire()`` raises
    :class:`cisternal.registration.errors.CisternalWireError` with
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
    owned by :class:`cisternal.adapters.v3_middleware.CisternalMiddleware`.  The
    ``adapter`` parameter is accepted here for forward-compat but is
    intentionally NEVER used.
"""

from __future__ import annotations

import inspect
import logging
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, cast

from cisternal._typed_callable import TaggedCallable
from cisternal.registration.cli_contract import (
    CYCLOPTS_BUILTIN_FLAGS,
    # The group cache and its helpers live in cli_contract (spec 4, 5.6) and are
    # re-exported here: ``wired._CLI_SUBAPPS`` is the same dict object.
    _CLI_SUBAPPS,  # noqa: F401
    CliContract,
    _build_cli_callable,
    _get_or_create_subapp,
    _normalise_group_path,
    _probe_group_path,
    _resolve_cli_hints,
)
from cisternal.registration.compose import apply_recovery_sync, compose_mcp_callable
from cisternal.registration.errors import CisternalWireError
from cisternal.registration.registry import snapshot

if TYPE_CHECKING:
    pass

_log = logging.getLogger("cisternal.registration")

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
                       (empty if *app* was not supplied to ``wire()``). A
                       grouped command (``entry.cli_group`` set) is recorded
                       as the space-joined ``"<seg1> ... <segN> <cli_name>"``
                       (``"<group> <cli_name>"`` for a one-segment group).
    """

    registry_name: str
    mcp_tools: list[str] = field(default_factory=list)
    cli_commands: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CLI callable builder (hoisted out of wire()'s entry loop, T0b)
# ---------------------------------------------------------------------------


def _make_cli_cmd(
    original_fn: Any, cmd_name: str, *, recovery: Any, telemetry: bool
) -> Any:
    # Telemetry owner for the CLI path. The MCP path's silence is
    # deliberate — CisternalMiddleware owns it there, and emitting
    # in the composed callable too would double-count every tool
    # call. The CLI path had no such owner, so it emitted nothing
    # at all: identical work produced a full record through MCP and
    # silence through the CLI. `timed_command` is the CLI's
    # designated owner and already existed; wire() simply never
    # applied it.
    _dispatch = lambda *a, **k: apply_recovery_sync(  # noqa: E731
        original_fn, recovery, *a, **k
    )
    if telemetry and not getattr(original_fn, "_cisternal_timed", False):
        from cisternal.adapters.cli import timed_command

        # Deliberately INSIDE the F1 handler below, so telemetry
        # observes the original exception. Wrapping outside would
        # record every failure as exc_type="SystemExit", since F1
        # converts exceptions into sys.exit(1) before they escape.
        _dispatch = timed_command(cmd_name)(_dispatch)

    def _cli_cmd(*args: Any, **kwargs: Any) -> Any:
        # F1 CLI error contract: wrap exceptions into a clean exit.
        # AC13: the same `recovery` policy passed to wire() applies
        # here too, via apply_recovery_sync's AC12 sync leg (no
        # thread offload, no telemetry contextvar — see compose.py).
        try:
            return _dispatch(*args, **kwargs)
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
    cast(TaggedCallable, _cli_cmd).__signature__ = inspect.signature(original_fn)
    # A9: resolve the parameters' annotations against the tool module's own
    # globals (not wired.py's). cyclopts calls get_type_hints on this closure,
    # whose __globals__ are wired.py's, so raw string annotations from a
    # `from __future__ import annotations` module used to raise NameError.
    # __signature__ above is deliberately left unresolved and unchanged.
    _cli_cmd.__annotations__ = _resolve_cli_hints(original_fn, strict=False)
    return _cli_cmd


# ---------------------------------------------------------------------------
# wire-time pre-pass (spec 5.1)
# ---------------------------------------------------------------------------


@dataclass
class _CliPlan:
    """One entry's pre-built CLI registration, produced by :func:`_plan_cli`."""

    cli_cmd: Any
    cli_name: str
    group: tuple[str, ...]  # the normalised group path; () for a flat command
    command: str  # the joined path: ctx.command and WiredRegistry.cli_commands
    extra: dict[str, Any]  # ``help=`` / ``show=``, only when the contract sets them


def _check_contract_args(
    snapshot_view: Mapping[str, Any],
    cli_contract: CliContract | None,
    cli_contracts: Mapping[str, CliContract] | None,
    registry: str,
) -> None:
    """Stage 1 of the pre-pass: the checks that run even when ``app is None``."""
    if cli_contract is not None and not isinstance(cli_contract, CliContract):
        raise TypeError(
            f"cisternal.wire(): cli_contract must be a CliContract or None, "
            f"got {cli_contract!r}"
        )
    # A decorator-supplied contract is checked at registration, but an entry can
    # also reach the registry without going through register().
    for entry in snapshot_view.values():
        if entry.cli_contract is not None and not isinstance(
            entry.cli_contract, CliContract
        ):
            raise TypeError(
                f"cisternal.wire(): tool {entry.name!r}: cli_contract must be a "
                f"CliContract, got {entry.cli_contract!r}"
            )
    if not cli_contracts:
        return
    by_name = {entry.name: entry for entry in snapshot_view.values()}
    for key, contract in cli_contracts.items():
        if not isinstance(contract, CliContract):
            raise TypeError(
                f"cisternal.wire(): cli_contracts[{key!r}] must be a CliContract, "
                f"got {contract!r}"
            )
        if key not in by_name:
            raise CisternalWireError(
                message=(
                    f"cisternal.wire(): cli_contracts names {key!r}, which is not a "
                    f"tool of registry {registry!r}"
                )
            )
        if by_name[key].cli_contract is not None:
            raise CisternalWireError(
                message=(
                    f"cisternal.wire(): tool {key!r} has both a decorator "
                    "cli_contract and a cli_contracts entry; use one"
                )
            )


def _effective_contract(
    entry: Any,
    cli_contract: CliContract | None,
    cli_contracts: Mapping[str, CliContract] | None,
) -> CliContract | None:
    """T.merged_over(W) when the tool has a contract, else W (spec 5.1)."""
    tool_contract = entry.cli_contract
    if tool_contract is None and cli_contracts:
        tool_contract = cli_contracts.get(entry.name)
    if tool_contract is None:
        return cli_contract
    try:
        return tool_contract.merged_over(cli_contract)
    except ValueError as exc:
        raise CisternalWireError(message=f"tool {entry.name!r}: {exc}") from exc


def _where(level: tuple[str, ...]) -> str:
    return f"group {' '.join(level)!r}" if level else "the root"


def _plan_name(
    planned: dict[tuple[str, ...], dict[str, str]],
    level: tuple[str, ...],
    name: str,
    kind: str,
) -> None:
    """Record *name* as planned at *level*; raise if it clashes with an earlier plan."""
    kinds = planned.setdefault(level, {})
    previous = kinds.get(name)
    if previous is None:
        kinds[name] = kind
    elif not (previous == "group" and kind == "group"):
        raise CisternalWireError(
            message=(
                f"cisternal.wire(): CLI name {name!r} is planned twice at "
                f"{_where(level)} (as a {previous} and as a {kind})"
            )
        )


def _resolved_default_parameter(*apps: Any) -> Any:
    """The ``default_parameter`` cyclopts applies below *apps* (root first, A28)."""
    chain = [
        p
        for p in (getattr(a, "default_parameter", None) for a in apps)
        if p is not None
    ]
    if not chain:
        return None
    from cyclopts import Parameter

    return Parameter.combine(*chain)


def _reserved_flags(
    apps: tuple[Any, ...], creates_leaf: bool
) -> frozenset[str]:
    """The long flags cyclopts reserves for the command's own App chain.

    Each App on the path (root first) contributes its ``help_flags`` and
    ``version_flags`` (a sub-App also answers to its parent's version flags, so
    the union is the safe over-approximation).  When ``wire()`` will create the
    leaf level itself, that fresh App carries cyclopts' defaults as well.
    """
    flags: set[str] = set(CYCLOPTS_BUILTIN_FLAGS) if creates_leaf else set()
    for a in apps:
        for attr in ("help_flags", "version_flags"):
            value = getattr(a, attr, None) or ()
            for flag in (value,) if isinstance(value, str) else value:
                if isinstance(flag, str) and flag.startswith("--"):
                    flags.add(flag)
    return frozenset(flags)


def _entry_group_path(entry: Any) -> tuple[str, ...]:
    """The entry's normalised ``cli_group`` path; ``()`` for a flat command."""
    if entry.cli_group is None:
        return ()
    try:
        return _normalise_group_path(entry.cli_group)
    except CisternalWireError as exc:
        raise CisternalWireError(
            message=f"cisternal.wire(): tool {entry.name!r}: {exc}"
        ) from exc


def _normalise_group_helps(
    cli_group_help: Mapping[Any, str] | None,
    paths: list[tuple[str, ...]],
) -> dict[tuple[str, ...], str]:
    """Normalise ``cli_group_help`` keys and check each is a prefix of an entry path.

    A tuple ``k`` is a prefix of ``p`` when ``p[:len(k)] == k`` (spec 5.1).
    """
    helps: dict[tuple[str, ...], str] = {}
    for key, text in (cli_group_help or {}).items():
        if not isinstance(text, str):
            raise TypeError(
                f"cisternal.wire(): cli_group_help[{key!r}] must be a str, got {text!r}"
            )
        segments = _normalise_group_path(key)
        if not any(path[: len(segments)] == segments for path in paths):
            raise CisternalWireError(
                message=(
                    f"cisternal.wire(): cli_group_help names {' '.join(segments)!r}, "
                    "which is not a prefix of any tool's cli_group"
                )
            )
        helps[segments] = text
    return helps


def _plan_cli(
    app: Any,
    snapshot_view: Mapping[str, Any],
    cli_contract: CliContract | None,
    cli_contracts: Mapping[str, CliContract] | None,
    helps: Mapping[tuple[str, ...], str],
    recovery: Any,
    cli_telemetry: bool,
) -> dict[str, _CliPlan]:
    """Stage 2 of the pre-pass (``app is not None``): build every CLI callable.

    For each entry, in order: resolve the effective contract; normalise its
    group path; check the planned and already-present names; probe the group
    path read-only with :func:`_probe_group_path` (a rejection or a help
    conflict raises here); compute the ``default_parameter`` of every existing
    App on the path (A28); build the callable. It mounts nothing and writes no
    cache entry, so any :class:`CisternalWireError` leaves *app* untouched.
    """
    planned: dict[tuple[str, ...], dict[str, str]] = {}
    plans: dict[str, _CliPlan] = {}
    for entry in snapshot_view.values():
        effective = _effective_contract(entry, cli_contract, cli_contracts)
        cli_name = entry.cli_name or entry.name
        group_path = _entry_group_path(entry)

        # Planned names: each group segment at its parent level, the leaf at
        # the group's level.
        for i, segment in enumerate(group_path):
            _plan_name(planned, group_path[:i], segment, "group")
        _plan_name(planned, group_path, cli_name, "command")

        # Read-only probe: the Apps that already exist on the path (cached,
        # or adopted from a pre-mounted user App).
        existing = _probe_group_path(app, group_path, helps=helps) if group_path else []

        # A leaf already `in` an existing target level is a clash. A level
        # cisternal will create is empty and needs no check; a group segment
        # that already exists is not a clash (the probe adopted or rejected it).
        target: Any = None
        if not group_path:
            target = app
        elif len(existing) == len(group_path):
            target = existing[-1]
        if target is not None and cli_name in target:
            raise CisternalWireError(
                message=(
                    f"cisternal.wire(): tool {entry.name!r}: CLI name {cli_name!r} "
                    f"is already registered at {_where(group_path)}"
                )
            )

        extra: dict[str, Any] = {}
        if effective is not None:
            if effective.help is not None:
                extra["help"] = effective.help
            if effective.show is not None:
                extra["show"] = effective.show

        command = " ".join((*group_path, cli_name))
        cli_cmd = _build_cli_callable(
            entry.fn,
            tool_name=entry.name,
            command=command,
            contract=effective,
            recovery=recovery,
            telemetry=cli_telemetry,
            app_default_parameter=_resolved_default_parameter(app, *existing),
            reserved_flags=_reserved_flags(
                (app, *existing), creates_leaf=len(existing) != len(group_path)
            ),
        )
        plans[entry.name] = _CliPlan(
            cli_cmd=cli_cmd,
            cli_name=cli_name,
            group=group_path,
            command=command,
            extra=extra,
        )
    return plans


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
    recovery: tuple[Callable[[BaseException], bool], Callable[[], None]] | None = None,
    cli_telemetry: bool = True,
    cli_contract: CliContract | None = None,
    cli_contracts: Mapping[str, CliContract] | None = None,
    cli_group_help: Mapping[str | tuple[str, ...], str] | None = None,
) -> WiredRegistry:
    """Snapshot the named registry and register each tool on *server* (and *app*).

    For when to use this instead of a hand-written CLI/MCP pair, the rules for
    tool bodies, and tested ``CliContract`` recipes (exit codes, ``--json``,
    prompts, groups, composites), see ``docs/guides/wire-onboarding.md``.

    Steps:
        1. Take a point-in-time snapshot of *registry* via
           :func:`~cisternal.registration.registry._snapshot`.
        2. For each entry in the snapshot: produce an MCP callable via
           :func:`~cisternal.registration.compose.compose_mcp_callable`, wrap it
           in a ``fastmcp.tools.Tool`` explicitly named ``entry.name`` (AC-M2-15
           -- this is NOT always the same as the callable's ``__name__``), and
           register it on *server* via ``server.add_tool(tool)``.
        3. If *app* is given: register a CLI command per entry, named
           ``entry.cli_name or entry.name``.  When ``entry.cli_group`` is
           set (a one-segment name, a whitespace-separated path such as
           ``"flow visuals"``, or a tuple of segments), the command nests
           under a cached sub-``cyclopts.App`` per level (created and mounted
           on *app* on first use, or adopted when a user ``App`` is already
           mounted there; spec 5.6); otherwise
           it registers flat on *app* directly (default, unchanged
           behavior). The CLI callable dispatches to the original function
           and, unless ``cli_telemetry=False``, is instrumented with
           :func:`~cisternal.adapters.cli.timed_command`. Every CLI callable
           is built, and every name and contract checked, in a pre-pass that
           runs before the first ``add_tool`` / ``app.command`` call, so a
           :class:`CisternalWireError` raised there leaves *server* and *app*
           untouched (spec 5.1).
        4. Validate *expected* names (AC-M2-9 / AC-M2-10).
        5. Return a :class:`WiredRegistry` instance (TBD-M2-5).

    HARD INVARIANT (C5 / AC-M2-6) — MCP PATH ONLY:
        The composed **MCP** callable MUST NOT call any adapter method or emit
        any telemetry.  Telemetry on that path is owned by
        :class:`~cisternal.adapters.v3_middleware.CisternalMiddleware`, and a
        callable that emitted as well would double-count every tool call
        whenever the middleware is installed.  The *adapter* parameter is
        accepted for forward-compat and is intentionally never used.
        (*recovery*'s hooks are supplied by the caller, not owned by cisternal,
        and the only cisternal-side side effect of a recovery attempt is a
        plain ``ContextVar.set()`` — a signal, not a telemetry call; see
        ``compose.py``'s module docstring, R1.)

    WHY THE CLI PATH IS DIFFERENT (and why it changed):
        That invariant was previously applied to the CLI closure too, by
        analogy.  The analogy does not hold: there is no CLI middleware, so
        nothing owned CLI telemetry and the path emitted **nothing at all**.
        The same tool invoked the same way produced a complete record through
        MCP and silence through the CLI — a telemetry surface that under-reports
        by construction, and does so most for the surface a human is most
        likely to be driving.

        The CLI's designated owner is ``timed_command`` (spec §4.2, AC-CLI-1),
        which already existed; ``wire()`` simply never applied it.  It now
        does, emitting ``cli.cmd_start`` / ``cli.cmd_end`` per command.  A
        function a consumer already decorated by hand is detected via
        ``_cisternal_timed`` and is not wrapped twice.  Pass
        ``cli_telemetry=False`` to restore the previous silence.

    Args:
        server:    A ``fastmcp.FastMCP`` instance (or any object with an
                   ``add_tool`` method).  Registered MCP callables are added
                   here.
        app:       Optional ``cyclopts.App``.  When supplied, a CLI command is
                   registered for each tool entry.  With no contract (see
                   *cli_contract*, *cli_contracts* and ``@tool(cli_contract=...)``)
                   the CLI callable is a passthrough to the original function:
                   the result goes back to cyclopts' ``result_action`` and an
                   ``Exception`` prints ``Error (<Type>): <msg>`` and exits 1.
                   With a contract it also applies the contract's exit-code map,
                   success formatter, CLI-only options and ``prepare`` hook, and
                   forwards ``help``/``show`` to ``app.command``.  The MCP callable
                   never sees any of it.
        adapter:   Accepted but NEVER used (C5 / AC-M2-6).  Pass ``None``
                   (default).  Passing a non-None value is silently ignored.
        registry:  Which named registry partition to snapshot.  Defaults to
                   ``"default"``.
        expected:  Optional list of tool names that must be present in the
                   snapshot.  Controls validation behaviour together with
                   *validate*.
        validate:  When ``True`` (default) and *expected* names are missing:
                   raise :class:`CisternalWireError`.  When ``False``: log a
                   WARNING to ``cisternal.registration`` and continue.
        cli_telemetry:
                   When ``True`` (default), each registered CLI command is
                   instrumented with ``timed_command`` so the CLI path emits
                   ``cli.cmd_start`` / ``cli.cmd_end`` like the MCP path emits
                   its middleware events.  ``False`` restores the pre-change
                   behaviour of emitting nothing on the CLI.  Has no effect on
                   the MCP path, whose C5 invariant is unchanged.
        recovery:  Optional ``(is_recoverable, recover)`` pair of synchronous
                   callables (spec 260805_nlm-adapter-transparent-auto-reauth,
                   AC7-AC13).  When supplied, it is threaded uniformly into
                   every entry's composed MCP callable AND its CLI closure
                   (AC13) — there is no separate exclusion parameter at this
                   level; exclusion is entirely the caller's registration-time
                   decision (only pass a tool's own function through this
                   registry partition if it should be recovery-eligible).
                   ``None`` (default) preserves today's exact behaviour for
                   every other cisternal consumer.

        cli_contract:
                   Optional :class:`~cisternal.registration.cli_contract.CliContract`
                   applied to every CLI command of this call (W, the default).
                   A per-tool contract refines it field by field
                   (``T.merged_over(W)``, spec 5.1). ``None`` (default, and the
                   case when no tool has a contract either) keeps the legacy
                   CLI closure unchanged. Inert with ``app=None``.
        cli_contracts:
                   Optional ``{tool_name: CliContract}`` applied at tool (T)
                   precedence, for tools you cannot decorate. A key that names
                   no tool of *registry*, or a tool that also has a decorator
                   ``cli_contract``, raises :class:`CisternalWireError` (also
                   when ``app is None``).
        cli_group_help:
                   Optional ``{group_path: help_text}``. Keys are normalised to
                   segment tuples (``"flow visuals"`` == ``("flow",
                   "visuals")``), so ``{"flow": "Flow ops", "flow visuals":
                   "Visual ops"}`` gives each level its own help. Every key
                   must be a prefix of some tool's ``cli_group`` path, else
                   :class:`CisternalWireError`. Help is applied to levels
                   cisternal creates, and to cisternal-created levels that have
                   no help yet; a cisternal-created level that already has a
                   different help raises :class:`CisternalWireError`. A
                   pre-mounted user ``App`` that ``wire()`` adopts as a group
                   is left untouched, help included (spec 5.6). Inert with
                   ``app=None``.

    Returns:
        A :class:`WiredRegistry` recording which tools were wired.

    Raises:
        CisternalWireError: If *expected* names are absent from the snapshot
            and ``validate=True``; or, before anything is registered, if
            ``cli_contracts`` has an unknown key or a tool with two contracts,
            a W/T option name is duplicated, a CLI callable cannot be built
            (unresolvable parameter annotation, option collision), two CLI
            names clash at one level or with a name already on *app*, a
            ``cli_group`` path is malformed or names a function command (not a
            group), or a ``cli_group_help`` key is unknown or conflicts with a
            help already applied.
        TypeError: If *cli_contract*, a ``cli_contracts`` value or a tool's
            decorator ``cli_contract`` is not a :class:`CliContract` (the
            decorator form is also rejected when the tool is registered, and
            with ``app=None``), or a ``cli_group_help`` value is not a ``str``.
    """
    # C6: snapshot at wire-time; post-wire decorations are excluded.
    snapshot_view = snapshot(registry)

    # Validation: check expected names against the snapshot (AC-M2-9 / AC-M2-10).
    if expected is not None:
        missing = [n for n in expected if n not in snapshot_view]
        if missing:
            if validate:
                raise CisternalWireError(missing=missing)
            else:
                _log.warning(
                    "cisternal.wire(): expected tools not found in registry %r: %s",
                    registry,
                    missing,
                )

    _check_contract_args(snapshot_view, cli_contract, cli_contracts, registry)

    # Wire-time pre-pass (spec 5.1): everything that can raise a
    # CisternalWireError runs here, before the first add_tool/app.command call,
    # so a failure leaves both `server` and `app` untouched.
    cli_plans: dict[str, _CliPlan] = {}
    cli_group_helps: dict[tuple[str, ...], str] = {}
    if app is not None:
        cli_group_helps = _normalise_group_helps(
            cli_group_help, [_entry_group_path(e) for e in snapshot_view.values()]
        )
        cli_plans = _plan_cli(
            app,
            snapshot_view,
            cli_contract,
            cli_contracts,
            cli_group_helps,
            recovery,
            cli_telemetry,
        )

    mcp_tool_names: list[str] = []
    cli_command_names: list[str] = []

    for entry in snapshot_view.values():
        # Generate the async MCP callable (E2/E1/H1 guarantees from compose).
        # entry.name (not entry.fn.__name__) both names the FastMCP tool
        # (AC-M2-15, below) and is what compose_mcp_callable tags Spec B's
        # recovery-telemetry payload with, so the two stay in agreement.
        mcp_callable = compose_mcp_callable(
            entry.fn, recovery=recovery, tool_name=entry.name
        )

        # server=None means "skip the MCP surface", mirroring app=None below
        # (issue #18) -- not an error, and the fastmcp import + Tool
        # construction shouldn't run at all for a CLI-only wiring.
        if server is not None:
            # Explicitly name the registered Tool as entry.name (AC-M2-15). A
            # bare callable falls back to FastMCP's own name inference, which
            # reads mcp_callable.__name__ (== entry.fn.__name__ via compose's
            # functools.update_wrapper) -- NOT entry.name. Whenever a
            # consumer's wrapper function name differs from the name=
            # override passed to @cisternal.tool, that fallback silently
            # exposes the wrong tool name.
            from fastmcp.tools import Tool

            fastmcp_tool = Tool.from_function(mcp_callable, name=entry.name)
            server.add_tool(fastmcp_tool)
            mcp_tool_names.append(entry.name)

        # Register CLI command if app is supplied.
        # F1 dual error contract (CLI path):
        #   - The CLI callable wraps exceptions into a clean CLI failure:
        #     it writes a concise message to stderr and calls sys.exit(1).
        #   - It does NOT emit telemetry (C5 / AC-M2-6).
        #   - The MCP callable (above) is an unmodified passthrough — MCP
        #     exceptions propagate to FastMCP/CisternalMiddleware, which is
        #     M1's responsibility.
        # The callable was built (and every check run) in the pre-pass.
        if app is not None:
            plan = cli_plans[entry.name]
            if plan.group:
                target_app = _get_or_create_subapp(
                    app, plan.group, helps=cli_group_helps
                )
                target_app.command(name=plan.cli_name, **plan.extra)(plan.cli_cmd)
            else:
                app.command(name=plan.cli_name, **plan.extra)(plan.cli_cmd)
            cli_command_names.append(plan.command)

    return WiredRegistry(
        registry_name=registry,
        mcp_tools=mcp_tool_names,
        cli_commands=cli_command_names,
    )
