"""Tools for the 16a collision cases, with string (``from __future__``) annotations.

The check runs on the *resolved* hints, never on ``inspect.Parameter.annotation``
(which is a string here), so every case must give the same result as its
real-object twin in ``collision_tools_plain.py`` (the 16a variant, spec 11).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from cyclopts import Parameter


def tool_ident(json_out: bool = False) -> bool:
    """Parameter identifier equal to the ``json_option()`` identifier."""
    return json_out


def tool_json(json: bool = False) -> bool:
    """Parameter ``json`` claims ``--json`` (the ``json_option()`` flag)."""
    return json


def tool_x(x: bool = False) -> bool:
    """Bool ``x`` claims ``--x`` and ``--no-x``."""
    return x


def tool_explicit_json(j: Annotated[bool, Parameter(name="--json")] = False) -> bool:
    """An explicit ``Parameter(name="--json")``."""
    return j


def tool_user_negative(
    flag: Annotated[bool, Parameter(negative="off")] = False,
) -> bool:
    """A user negative ``off`` normalised to ``--off``."""
    return flag


def tool_items(items: list[str] | None = None) -> list[str] | None:
    """A ``list[str]`` parameter claims ``--items`` and ``--empty-items``."""
    return items


def tool_no_x2(f: Annotated[bool, Parameter(name="--no-x2")] = False) -> bool:
    """Claims ``--no-x2``, the derived negative of a bool option ``x2``."""
    return f


def tool_foo_named(f: Annotated[bool, Parameter(name="foo")] = False) -> bool:
    """``Parameter(name="foo")`` (no hyphen) normalises to ``--foo`` / ``--no-foo``."""
    return f


def tool_unannotated_flag(flag=False):  # noqa: ANN001, ANN201
    """Unannotated ``flag=False`` derives as bool: ``--flag`` and ``--no-flag``."""
    return flag


def tool_any_x(x: Any = False) -> Any:
    """``Any`` with a non-None default derives as ``type(default)`` (bool)."""
    return x


# --- controls that must NOT raise -------------------------------------------


def tool_star_json(*json: str) -> int:
    """``*args`` named ``json``: skipped by the flag check."""
    return len(json)


def tool_short_j(
    flag: Annotated[bool, Parameter(name=["--aaa", "-j"])] = False,
) -> bool:
    """Uses the short flag ``-j``; short flags are out of scope."""
    return flag


def tool_parse_false(*, working_dir: Annotated[str, Parameter(parse=False)]) -> str:
    """A ``parse=False`` parameter claims no flag."""
    return working_dir


def tool_path(p: Path) -> str:
    """Plain Path parameter."""
    return str(p)
