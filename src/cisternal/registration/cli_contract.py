"""CLI-callable helpers for ``wire()``: annotation resolution (the A9 fix).

This module stays fastmcp-free and import-cycle-free: its only module-scope
cisternal import is :mod:`cisternal.registration.errors`.  Anything that would
pull in ``cisternal.registration.wired`` (which imports this module) is imported
inside the function that needs it.

Spec: ``.praxia/docs/specs/261001_wire-cli-contract.md`` (section 4 and 5.5).
"""

from __future__ import annotations

import inspect
import typing
from typing import Any

from cisternal.registration.errors import CisternalWireError


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
