"""CLI contract for ``wire()``: contract types and CLI-callable helpers.

Holds the public contract types (:class:`CliContext`, :class:`CliOption`,
:class:`CliContract`, :func:`json_option`, :func:`default_report`,
:func:`exit_code_attr`), the exception-to-exit-code resolver
(:func:`_resolve_exit`), the annotation resolution of the A9 fix
(:func:`_resolve_cli_hints`), the CLI callable builder
(:func:`_build_cli_callable`, with :func:`_rebind` and the long-flag collision
check) and the public :func:`cli_command` over it.

This module stays fastmcp-free and import-cycle-free (R10): its only
module-scope cisternal import is :mod:`cisternal.registration.errors`.
``cyclopts``, ``cisternal.adapters.cli``, ``cisternal.registration.compose``
and ``cisternal.registration.wired`` (which imports this module) are imported
inside the function that needs them.

Spec: ``.praxia/docs/specs/261001_wire-cli-contract.md`` (sections 4, 5.1-5.5).
"""

from __future__ import annotations

import inspect
import keyword
import logging
import re
import sys
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, TypeAlias

from cisternal.registration.errors import CisternalWireError

_log = logging.getLogger("cisternal.registration")

# The first parameter is Any, not Exception, so that handlers typed on a narrower
# exception (``(exc: SeamExplosionError, ctx)``) type-check.
ExitHandler = Callable[[Any, "CliContext"], "int | None"]
SuccessFormatter = Callable[[Any, "CliContext"], Any]
PrepareHook = Callable[["CliContext"], None]
ReportFn = Callable[[BaseException], None]
GroupPath: TypeAlias = str | tuple[str, ...]  # "flow visuals" == ("flow", "visuals")


@dataclass(frozen=True)
class CliOption:
    """A CLI-only keyword option injected into the CLI callable's signature.

    It is never passed to the tool function.  Its parsed value lands in
    ``ctx.options[name]``.  Its CLI flags are derived exactly like a tool
    parameter's (spec 5.4).

    Attributes:
        name:       Python identifier.
        annotation: A real type object (``bool``, ``Annotated[bool, Parameter(...)]``),
                    never a string or ``ForwardRef`` (R5): option annotations are
                    added after hint resolution, so a string would reach cyclopts
                    unresolved.
        default:    The option's default value.
        help:       Help text; the builder wraps the annotation as
                    ``Annotated[annotation, Parameter(help=help)]``.

    Raises:
        ValueError: ``name`` is not an identifier or is a keyword; or ``help`` is
            set while ``annotation`` is ``Annotated[...]`` carrying a cyclopts
            ``Parameter`` with its own ``help``.
        TypeError: ``annotation`` is a ``str`` or ``typing.ForwardRef``; or
            ``help`` is neither ``None`` nor a ``str``.
    """

    name: str
    annotation: Any
    default: Any = None
    help: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name.isidentifier()
            or keyword.iskeyword(self.name)
        ):
            raise ValueError(
                f"CliOption name must be a Python identifier that is not a keyword, "
                f"got {self.name!r}"
            )
        if isinstance(self.annotation, (str, typing.ForwardRef)):
            raise TypeError(
                f"CliOption {self.name!r}: annotation must be a real type object, "
                f"not {type(self.annotation).__name__} ({self.annotation!r})"
            )
        if self.help is None:
            return
        if not isinstance(self.help, str):
            raise TypeError(
                f"CliOption {self.name!r}: help must be a str or None, "
                f"got {type(self.help).__name__}"
            )
        if typing.get_origin(self.annotation) is Annotated:
            from cyclopts import Parameter  # lazy: R10

            for meta in typing.get_args(self.annotation)[1:]:
                if isinstance(meta, Parameter) and meta.help is not None:
                    raise ValueError(
                        f"CliOption {self.name!r}: help= conflicts with the "
                        f"Parameter(help={meta.help!r}) already in its annotation"
                    )


def json_option(
    flag: str = "--json",
    *,
    name: str = "json_out",
    help: str = "Emit machine-readable JSON instead of formatted output.",
) -> CliOption:
    """The standard JSON flag.

    ``CliOption(name, Annotated[bool, Parameter(name=flag, negative="")], False,
    help=help)``: it claims only *flag*, with no ``--no-...`` negative.
    """
    from cyclopts import Parameter  # lazy: R10

    return CliOption(
        name, Annotated[bool, Parameter(name=flag, negative="")], False, help=help
    )


def default_report(exc: BaseException) -> None:
    """Write the exact F1 bytes to ``sys.stderr``: ``Error (<Type>): <exc>\\n``."""
    sys.stderr.write(f"Error ({type(exc).__name__}): {exc}\n")


def exit_code_attr(
    attr: str = "exit_code",
    *,
    default: int = 1,
    report: ReportFn = default_report,
) -> ExitHandler:
    """Return an exit handler that reports, then exits with ``exc.<attr>``.

    The handler calls ``report(exc)`` and returns ``getattr(exc, attr)``.  It
    covers int-valued attributes only: it falls back to *default* when the
    attribute is missing, is a ``bool``, is not an ``int`` (a ``str`` or
    ``StrEnum`` code included) or lies outside 1..255.  String or enum codes need
    a handler with a lookup table.  The handler never reads ``ctx``.

    If *report* raises, the exception propagates to ``_resolve_exit``'s
    handler-failure path (spec 5.3).

    Raises:
        TypeError: *report* is not callable, or *default* is not an ``int``.
        ValueError: *default* is outside 1..255.
    """
    if not callable(report):
        raise TypeError(f"exit_code_attr: report must be callable, got {report!r}")
    if not isinstance(default, int) or isinstance(default, bool):
        raise TypeError(f"exit_code_attr: default must be an int, got {default!r}")
    if not 1 <= default <= 255:
        raise ValueError(f"exit_code_attr: default must be in 1..255, got {default}")

    def _handler(exc: Any, ctx: CliContext) -> int:
        report(exc)
        code = getattr(exc, attr, None)
        if isinstance(code, int) and not isinstance(code, bool) and 1 <= code <= 255:
            return int(code)
        return default

    return _handler


@dataclass
class CliContext:
    """Per-invocation context handed to prepare, format_success and exit handlers.

    It is created empty before any parsing work, so exit handlers may receive a
    partially built ctx: ``arguments == {}`` (and ``options`` possibly partial)
    when the failure happened before or during binding.  It carries no App-level
    (global) option values (N8).

    Attributes:
        tool_name: ``entry.name`` (matches telemetry ``cmd`` and the MCP name).
        command:   CLI path as registered: ``"<seg1> ... <segN> <cli_name>"`` or
                   ``"<cli_name>"``.
        arguments: Tool args by name, defaults applied; ``prepare`` may mutate.
        options:   CLI-only option values, keyed by ``CliOption.name``.
    """

    tool_name: str
    command: str
    arguments: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CliContract:
    """How a wired command's CLI behaves: output, exit codes, options, help.

    Normalised and validated eagerly at construction (``options`` becomes a
    tuple, ``exit_codes`` a read-only copy).  Contracts are unhashable.

    Raises (at construction):
        TypeError: an ``exit_codes`` key is not an ``Exception`` subclass
            (``SystemExit`` and ``KeyboardInterrupt`` are rejected here); a value
            is a ``bool`` or neither an ``int`` nor callable; an option is not a
            :class:`CliOption`; ``help`` is not ``None``/``str``; ``show`` is not
            ``None``/``bool``.
        ValueError: an ``int`` exit code is outside 1..255 (0 included); two
            options share a name.
    """

    format_success: SuccessFormatter | None = None
    exit_codes: Mapping[type[Exception], int | ExitHandler] = field(
        default_factory=dict
    )
    options: Sequence[CliOption] = ()
    prepare: PrepareHook | None = None
    help: str | None = None  # --help text override; forwarded to app.command only when set
    show: bool | None = None  # visibility override; forwarded to app.command only when set

    __hash__ = None  # type: ignore[assignment]  # contracts are unhashable

    def __post_init__(self) -> None:
        options = tuple(self.options)
        exit_codes = dict(self.exit_codes)

        for key, value in exit_codes.items():
            if not (isinstance(key, type) and issubclass(key, Exception)):
                raise TypeError(
                    f"exit_codes keys must be Exception subclasses, got {key!r}"
                )
            if isinstance(value, bool):
                raise TypeError(
                    f"exit_codes[{key.__name__}] must be an int in 1..255 or a "
                    f"handler, got bool {value!r}"
                )
            if isinstance(value, int):
                if not 1 <= value <= 255:
                    raise ValueError(
                        f"exit_codes[{key.__name__}] must be in 1..255, got {value}"
                    )
            elif not callable(value):
                raise TypeError(
                    f"exit_codes[{key.__name__}] must be an int in 1..255 or a "
                    f"handler, got {value!r}"
                )

        seen: set[str] = set()
        for opt in options:
            if not isinstance(opt, CliOption):
                raise TypeError(f"options must be CliOption instances, got {opt!r}")
            if opt.name in seen:
                raise ValueError(f"duplicate CliOption name {opt.name!r}")
            seen.add(opt.name)

        if self.help is not None and not isinstance(self.help, str):
            raise TypeError(f"help must be a str or None, got {self.help!r}")
        if self.show is not None and not isinstance(self.show, bool):
            raise TypeError(f"show must be a bool or None, got {self.show!r}")

        object.__setattr__(self, "options", options)
        object.__setattr__(self, "exit_codes", types.MappingProxyType(exit_codes))

    def merged_over(self, base: CliContract | None) -> CliContract:
        """Pure field-wise merge in which ``self`` (more specific) wins.

        ``merged_over(None)`` returns ``self`` (the identical object).  Otherwise
        returns a new contract with ``options == (*base.options, *self.options)``,
        ``exit_codes == {**base.exit_codes, **self.exit_codes}`` and
        ``format_success``/``prepare``/``help``/``show`` taken from ``self`` unless
        it is ``None``.  The result goes back through ``__post_init__``.  Does no
        signature inspection.

        Raises:
            ValueError: ``self`` and ``base`` share an option name.
        """
        if base is None:
            return self
        clash = sorted(
            {o.name for o in base.options} & {o.name for o in self.options}
        )
        if clash:
            raise ValueError(f"duplicate CliOption name(s) across contracts: {clash}")
        return CliContract(
            format_success=(
                self.format_success
                if self.format_success is not None
                else base.format_success
            ),
            exit_codes={**base.exit_codes, **self.exit_codes},
            options=(*base.options, *self.options),
            prepare=self.prepare if self.prepare is not None else base.prepare,
            help=self.help if self.help is not None else base.help,
            show=self.show if self.show is not None else base.show,
        )


def _resolve_exit(
    exc: Exception,
    ctx: CliContext,
    exit_codes: Mapping[type[Exception], int | ExitHandler],
) -> int:
    """Map *exc* to a process exit code (spec 5.3), reporting it on stderr.

    *exit_codes* is the effective (merged) contract's map.  Matching is by MRO,
    most specific first, so dict order is irrelevant.  An unmapped exception, a
    mapped ``int``, a handler returning ``None`` and a failing handler all print
    the F1 line; a mapped handler otherwise renders its own report.  A handler may
    return 0 ("handled, success").  ``SystemExit`` raised by a handler propagates.
    *ctx* may be partial (``arguments == {}``).
    """
    # The MRO also lists non-Exception bases (object, mixins); they simply never match.
    for klass in typing.cast("tuple[type[Exception], ...]", type(exc).__mro__):
        if klass in exit_codes:
            value = exit_codes[klass]
            break
    else:
        value = None
    if value is None or isinstance(value, int):
        default_report(exc)
        return 1 if value is None else value
    try:
        code = value(exc, ctx)
    except SystemExit:
        raise
    except Exception:
        _log.warning(
            "cisternal: exit handler for %s failed", type(exc).__name__, exc_info=True
        )
        default_report(exc)
        return 1
    if code is None:
        default_report(exc)
        return 1
    if not isinstance(code, int) or isinstance(code, bool) or not 0 <= code <= 255:
        _log.warning("cisternal: exit handler returned %r; using 1", code)
        return 1
    return code


def _resolve_cli_hints(fn: Any, *, strict: bool, tool_name: str = "") -> dict[str, Any]:
    """Resolve the annotations of *fn*'s **parameters** into real objects.

    Why this exists (A9): the CLI closure that ``wire()`` builds has
    ``wired.py``'s ``__globals__``, but it used to copy *fn*'s raw
    ``__annotations__``.  For a tool module using
    ``from __future__ import annotations`` those are strings, and cyclopts
    resolves them with ``typing.get_type_hints`` against the closure's
    globals, so any name ``wired.py`` does not import (``Path``,
    ``Annotated``, ``Parameter``, a ``TYPE_CHECKING``-only return type, ...)
    raised ``NameError`` at registration time.

    Resolution rules:

    * **Per parameter.**  Only names in ``inspect.signature(fn).parameters``
      are resolved, each on its own, with ``include_extras=True`` so
      ``Annotated`` metadata (cyclopts ``Parameter(...)``) survives.
      ``return`` and any other non-parameter key are left out of the result.
      cyclopts reads only parameter names, so nothing it uses is lost.
    * **Globals from the unwrapped function.**  ``globalns`` is
      ``{**vars(wired_module), **src.__globals__}`` with
      ``src = inspect.unwrap(fn)``: the tool module's globals override
      ``wired.py``'s, and names that resolved before only through ``wired.py``
      (``Any`` imported by the tool module under ``TYPE_CHECKING``) keep
      resolving.  The wrapper's own globals are not used: a
      ``functools.wraps`` wrapper such as ``timed_command``'s belongs to
      ``adapters/cli.py``, and passing an explicit ``globalns`` turns off
      ``get_type_hints``' own ``__wrapped__`` unwrapping.
    * **Empty ``__annotations__`` fallback.**  The raw annotations come from
      ``fn.__annotations__`` (which ``functools.wraps`` copies on CPython 3.13).
      When that is empty and *fn* has ``__wrapped__``, they come from
      ``src.__annotations__`` instead (CPython 3.14, PEP 649, may leave a
      wrapper's ``__annotations__`` empty).  This substitution is for
      resolution only.
    * **Failure.**  ``NameError``, ``AttributeError``, ``TypeError`` or
      ``SyntaxError`` (a malformed string annotation such as ``"list[int"``)
      for any parameter:

      - ``strict=False`` (the no-contract path) returns the legacy raw copy
        ``dict(fn.__annotations__)``, ``return`` key included, so cyclopts then
        fails exactly as it did before this fix;
      - ``strict=True`` raises :class:`CisternalWireError` naming *tool_name*
        and the parameter.

    ``inspect.signature(fn)`` is never changed by this function; the caller
    keeps ``__signature__`` as it was.

    Args:
        fn:        The tool function (possibly a ``functools.wraps`` wrapper).
        strict:    Raise on an unresolvable parameter instead of falling back.
        tool_name: Used only in the ``strict`` error message.

    Returns:
        ``{parameter_name: resolved_hint}`` for each annotated parameter.

    Raises:
        CisternalWireError: Only when ``strict`` is true.
    """
    from cisternal.registration import wired as wired_module  # lazy: wired imports us

    src = inspect.unwrap(fn)
    globalns = {**vars(wired_module), **getattr(src, "__globals__", {})}

    raw = fn.__annotations__
    if not raw and hasattr(fn, "__wrapped__"):
        raw = src.__annotations__

    out: dict[str, Any] = {}
    for pname in inspect.signature(fn).parameters:
        if pname not in raw:
            continue

        def shim() -> None: ...

        shim.__annotations__ = {pname: raw[pname]}
        try:
            out[pname] = typing.get_type_hints(
                shim, include_extras=True, globalns=globalns
            )[pname]
        except (NameError, AttributeError, TypeError, SyntaxError) as e:
            if strict:
                raise CisternalWireError(
                    message=(
                        f"tool {tool_name!r}: cannot resolve annotation of "
                        f"parameter {pname!r}: {getattr(e, 'name', None) or e}"
                    )
                ) from e
            # Legacy fallback: raw copy, exactly as before (including 'return').
            return dict(fn.__annotations__)
    return out


# ---------------------------------------------------------------------------
# Re-binding after ``prepare`` (spec 5.2)
# ---------------------------------------------------------------------------

_POSITIONAL_KINDS = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _rebind(
    sig: inspect.Signature, arguments: Mapping[str, Any]
) -> inspect.BoundArguments:
    """Turn ``ctx.arguments`` (after ``prepare``) back into a call's arguments.

    Four steps, each failing with a ``TypeError`` that the builder's F1 handler
    turns into the F1 line (or a mapped code), before the telemetry span opens:

    1. **Unknown keys.**  A key that is not a parameter of *sig*.
    2. **Rebuild ``(args, kwargs)`` by parameter kind**, in declaration order.
       The *gap* is the first positional-only or positional-or-keyword name that
       *arguments* lacks.  Before the gap, positional values go into ``args``.
       After it, a present positional-only value or a non-empty ``*args`` tuple
       cannot be placed (``TypeError``), and a positional-or-keyword value goes
       into ``kwargs`` by name.  Keyword-only values go into ``kwargs``, and the
       ``**kwargs`` dict is merged into ``kwargs``.
    3. **Bind** with ``bind_partial`` and apply defaults.
    4. **Required check.**  A parameter with no default that is still absent
       (typically a required ``parse=False`` argument that ``prepare`` did not
       set) raises ``TypeError``, so the tool is never called without it.

    Raises:
        TypeError: any of the above, or a ``bind_partial`` rejection (for
            example a ``**kwargs`` key that repeats a named parameter).
    """
    params = sig.parameters
    for key in arguments:
        if key not in params:
            raise TypeError(f"prepare set unknown argument {key!r}")

    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    gap: str | None = None
    for name, param in params.items():
        kind = param.kind
        if kind in _POSITIONAL_KINDS:
            if name not in arguments:
                if gap is None:
                    gap = name
                continue
            if gap is None:
                args.append(arguments[name])
            elif kind is inspect.Parameter.POSITIONAL_ONLY:
                raise TypeError(
                    f"prepare removed argument {gap!r} ahead of {name!r}"
                )
            else:
                kwargs[name] = arguments[name]
        elif kind is inspect.Parameter.VAR_POSITIONAL:
            rest = arguments.get(name, ())
            if rest:
                if gap is not None:
                    raise TypeError(
                        f"prepare removed argument {gap!r} ahead of {name!r}"
                    )
                args.extend(rest)
        elif kind is inspect.Parameter.KEYWORD_ONLY:
            if name in arguments:
                kwargs[name] = arguments[name]
        elif name in arguments:  # VAR_KEYWORD
            kwargs.update(arguments[name])

    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    for name, param in params.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param.default is inspect.Parameter.empty and name not in bound.arguments:
            raise TypeError(f"prepare removed required argument {name!r}")
    return bound


# ---------------------------------------------------------------------------
# Long-flag collision check (spec 5.4)
# ---------------------------------------------------------------------------


def _claimed_long_flags(
    identifier: str,
    hint: Any,
    default: Any,
    app_default_parameter: Any,
) -> set[str] | None:
    """The long flags (``--...``) cyclopts will give one parameter, or ``None``.

    ``None`` means cyclopts never parses the parameter (``parse=False``, or a
    ``parse`` regex that does not match *identifier*), so it claims no flag.
    Tool parameters and ``CliOption`` s use this same derivation (spec 5.4):

    * **Names.**  An explicit cyclopts ``Parameter(name=...)`` wins (a name
      without a leading hyphen becomes ``--<name>``, A25); otherwise
      ``"--" + default_name_transform(identifier)`` (A22).
    * **Negatives.**  ``Parameter.get_negatives`` (A23) on the combined
      ``Parameter`` (the App's ``default_parameter`` first, the annotation's
      ``Parameter`` s next, the normalised names last), using the hint the way
      cyclopts' ``Argument._negatives_hint`` does: an empty or ``Any`` hint
      becomes ``type(default)`` when the default is neither empty nor ``None``.

    Only ``--`` names are returned; short flags are out of scope.
    """
    from cyclopts import Parameter
    from cyclopts.annotations import resolve
    from cyclopts.utils import default_name_transform

    type_, param = Parameter.from_annotation(hint, app_default_parameter)

    parse = param.parse
    if parse is not None:
        parsed = bool(parse.search(identifier)) if isinstance(parse, re.Pattern) else bool(parse)
        if not parsed:
            return None

    explicit = tuple(
        n if n.startswith("-") else f"--{n}" for n in (param.name or ())
    )
    names = explicit or (f"--{default_name_transform(identifier)}",)
    named = Parameter.combine(param, Parameter(name=names))

    negatives_hint = type_
    if (
        hint is inspect.Parameter.empty or resolve(hint) is Any
    ) and default is not inspect.Parameter.empty and default is not None:
        negatives_hint = type(default)
    negatives = named.get_negatives(negatives_hint)
    return {n for n in (*names, *negatives) if n.startswith("--")}


def _check_cli_collisions(
    sig: inspect.Signature,
    hints: Mapping[str, Any],
    options: Sequence[CliOption],
    *,
    tool_name: str,
    app_default_parameter: Any,
) -> None:
    """Reject a ``CliOption`` that collides with the tool or with another option.

    Two checks (spec 5.4): an option *identifier* equal to any parameter name of
    the tool (positional-only, ``*args`` and ``**kwargs`` included), and an overlap
    between long flags.  Flags are derived from the *resolved* hints, never from
    ``inspect.Parameter.annotation`` (a string under ``from __future__ import
    annotations``).  Positional-only, ``*args`` and ``**kwargs`` parameters, and
    parameters cyclopts never parses, claim no flag.  cyclopts itself lets the
    first-declared parameter silently win a duplicated flag (A24), so this is the
    only guard.

    Raises:
        CisternalWireError: naming *tool_name* and the clashing identifier/flag.
    """
    if not options:
        return

    for opt in options:
        if opt.name in sig.parameters:
            raise CisternalWireError(
                message=(
                    f"tool {tool_name!r}: CliOption {opt.name!r} has the same name "
                    f"as a parameter of the tool"
                )
            )

    claimed: dict[str, str] = {}
    for pname, param in sig.parameters.items():
        if param.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        flags = _claimed_long_flags(
            pname,
            hints.get(pname, inspect.Parameter.empty),
            param.default,
            app_default_parameter,
        )
        for flag in flags or ():
            claimed.setdefault(flag, f"parameter {pname!r}")

    for opt in options:
        flags = _claimed_long_flags(
            opt.name, opt.annotation, opt.default, app_default_parameter
        )
        for flag in sorted(flags or ()):
            if flag in claimed:
                raise CisternalWireError(
                    message=(
                        f"tool {tool_name!r}: CliOption {opt.name!r} claims {flag!r}, "
                        f"which is already claimed by {claimed[flag]}"
                    )
                )
            claimed[flag] = f"option {opt.name!r}"


# ---------------------------------------------------------------------------
# The CLI callable builder (spec 5.2, 5.4)
# ---------------------------------------------------------------------------


def _option_annotation(opt: CliOption) -> Any:
    """``Annotated[annotation, Parameter(help=help)]`` when ``help`` is set."""
    if opt.help is None:
        return opt.annotation
    from cyclopts import Parameter  # lazy: R10

    return Annotated[opt.annotation, Parameter(help=opt.help)]


def _build_cli_callable(
    fn: Callable[..., Any],
    *,
    tool_name: str,
    command: str,
    contract: CliContract | None,
    recovery: tuple[Callable[[BaseException], bool], Callable[[], None]] | None,
    telemetry: bool,
    app_default_parameter: Any = None,
) -> Callable[..., Any]:
    """Build the CLI callable for *fn* (what ``wire()`` registers on cyclopts).

    With ``contract=None`` this is today's F1 closure, delegated to
    ``wired._make_cli_cmd`` (imported here, R10).  Otherwise it builds the spec 5.2
    closure, every step of which runs inside F1::

        ctx = CliContext(tool_name, command)     # empty; cannot fail
        try:
            pop the CLI-only options into ctx.options
            bind_partial(*args, **kw) through fn's own signature -> ctx.arguments
            prepare(ctx)                         # untimed
            _rebind(...)                         # untimed, before the span
            span( recovery-aware dispatch, then format_success(result, ctx) )
        except SystemExit: raise
        except Exception: sys.exit(_resolve_exit(...))

    The callable takes ``__name__`` and ``__doc__`` from *fn*, exactly as the legacy
    closure does, and no ``__wrapped__``, ``__qualname__`` or ``__module__``.  Its
    ``__signature__`` is *fn*'s with each option added keyword-only (before any
    ``**kwargs``), and its ``__annotations__`` are the strictly resolved parameter
    hints plus the options.

    Args:
        fn:          The tool function.
        tool_name:   ``entry.name``: the telemetry ``cmd`` and ``ctx.tool_name``.
        command:     ``ctx.command``: the CLI path as registered.
        contract:    The effective contract, or ``None`` for the legacy path.
        recovery:    The ``wire(recovery=...)`` pair, threaded to the dispatch.
        telemetry:   ``False`` opens no span (``cli_telemetry=False``).
        app_default_parameter:
                     The target App's resolved ``default_parameter`` (A28), used
                     only by the collision check.  ``cli_command()`` passes
                     ``None`` (R8).

    Raises:
        CisternalWireError: an unresolvable parameter annotation, or an option
            that collides with the tool's parameters (spec 5.4).
    """
    if contract is None:
        from cisternal.registration import wired  # lazy: wired imports this module

        return wired._make_cli_cmd(fn, tool_name, recovery=recovery, telemetry=telemetry)

    from cisternal.registration.compose import apply_recovery_sync

    sig = inspect.signature(fn)
    hints = _resolve_cli_hints(fn, strict=True, tool_name=tool_name)
    options = contract.options
    _check_cli_collisions(
        sig,
        hints,
        options,
        tool_name=tool_name,
        app_default_parameter=app_default_parameter,
    )

    # __signature__: fn's, plus each option keyword-only, before any **kwargs.
    params = list(sig.parameters.values())
    at = next(
        (
            i
            for i, p in enumerate(params)
            if p.kind is inspect.Parameter.VAR_KEYWORD
        ),
        len(params),
    )
    injected = [
        inspect.Parameter(
            o.name,
            inspect.Parameter.KEYWORD_ONLY,
            default=o.default,
            annotation=_option_annotation(o),
        )
        for o in options
    ]
    cli_sig = sig.replace(parameters=[*params[:at], *injected, *params[at:]])
    cli_annotations = {**hints, **{o.name: _option_annotation(o) for o in options}}

    format_success = contract.format_success
    prepare = contract.prepare
    exit_codes = contract.exit_codes
    option_defaults = [(o.name, o.default) for o in options]

    def _dispatch(a: tuple[Any, ...], k: dict[str, Any], ctx: CliContext) -> Any:
        result = apply_recovery_sync(
            typing.cast("Any", fn), recovery, *a, **k
        )
        return format_success(result, ctx) if format_success is not None else result

    # One span covers dispatch and the formatter, opened after prepare and _rebind
    # (which are never timed). A tool the consumer already instrumented keeps its
    # own span, and the formatter then runs untimed (spec 5.2).
    _timed: Callable[..., Any] = _dispatch
    if telemetry and not getattr(fn, "_cisternal_timed", False):
        from cisternal.adapters.cli import timed_command

        # Deliberately INSIDE the F1 handler below, so telemetry observes the
        # original exception rather than the SystemExit F1 converts it into.
        _timed = timed_command(tool_name)(_dispatch)

    def _cli_cmd(*args: Any, **kwargs: Any) -> Any:
        ctx = CliContext(tool_name, command)
        try:
            for opt_name, opt_default in option_defaults:
                ctx.options[opt_name] = kwargs.pop(opt_name, opt_default)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            ctx.arguments = dict(bound.arguments)
            if prepare is not None:
                prepare(ctx)
            rebound = _rebind(sig, ctx.arguments)
            return _timed(rebound.args, rebound.kwargs, ctx)
        except SystemExit:
            raise
        except Exception as exc:
            sys.exit(_resolve_exit(exc, ctx, exit_codes))

    _cli_cmd.__name__ = typing.cast("Any", fn).__name__
    _cli_cmd.__doc__ = fn.__doc__
    typing.cast("Any", _cli_cmd).__signature__ = cli_sig
    _cli_cmd.__annotations__ = cli_annotations
    return _cli_cmd


def cli_command(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    command: str | None = None,
    contract: CliContract | None = None,
    recovery: tuple[Callable[[BaseException], bool], Callable[[], None]] | None = None,
    telemetry: bool = True,
) -> Callable[..., Any]:
    """Return the CLI callable that ``wire()`` would build for *fn*.

    Register it yourself, so that a hand-written composite command gets the same
    F1, contract and telemetry behaviour as a wired tool::

        app.command(name="audit")(cli_command(audit, contract=...))
        # or, in a group wire() also uses:
        cisternal.cli_group(app, "g").command(name="x")(cli_command(x, ...))

    ``contract.help`` and ``contract.show`` are **not** applied: this returns a
    callable, not a registration, so pass ``help=``/``show=`` to ``app.command``
    yourself.  The collision check sees no App ``default_parameter`` (R8).  With
    ``contract=None`` this is exactly today's F1 closure, plus the A9 annotation
    resolution.

    Args:
        fn:        The function to expose (sync or async).
        name:      The telemetry ``cmd`` and ``ctx.tool_name``; default
                   ``fn.__name__``.
        command:   ``ctx.command``; default *name*.
        contract:  The :class:`CliContract`, or ``None``.
        recovery:  An ``(is_recoverable, recover)`` pair, as for ``wire()``.
        telemetry: ``False`` records no ``cli.cmd_*`` events.

    Raises:
        TypeError: *contract* is neither ``None`` nor a :class:`CliContract`.
        CisternalWireError: the CLI callable cannot be built (spec 5.4): an
            unresolvable parameter annotation, or an option that collides with a
            parameter or flag of *fn*.
    """
    if contract is not None and not isinstance(contract, CliContract):
        raise TypeError(
            f"cli_command: contract must be a CliContract or None, got {contract!r}"
        )
    tool_name = name if name is not None else typing.cast("Any", fn).__name__
    return _build_cli_callable(
        fn,
        tool_name=tool_name,
        command=command if command is not None else tool_name,
        contract=contract,
        recovery=recovery,
        telemetry=telemetry,
        app_default_parameter=None,
    )
