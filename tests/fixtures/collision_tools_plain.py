"""Real-object twin of ``collision_tools.py`` (no ``from __future__ import annotations``).

Same function names and signatures, so the 16a cases run once against real
annotation objects and once (the variant) against string annotations.
"""

from pathlib import Path
from typing import Annotated, Any

from cyclopts import Parameter


def tool_ident(json_out: bool = False) -> bool:
    return json_out


def tool_json(json: bool = False) -> bool:
    return json


def tool_x(x: bool = False) -> bool:
    return x


def tool_explicit_json(j: Annotated[bool, Parameter(name="--json")] = False) -> bool:
    return j


def tool_user_negative(
    flag: Annotated[bool, Parameter(negative="off")] = False,
) -> bool:
    return flag


def tool_items(items: list[str] | None = None) -> list[str] | None:
    return items


def tool_no_x2(f: Annotated[bool, Parameter(name="--no-x2")] = False) -> bool:
    return f


def tool_foo_named(f: Annotated[bool, Parameter(name="foo")] = False) -> bool:
    return f


def tool_unannotated_flag(flag=False):  # noqa: ANN001, ANN201
    return flag


def tool_any_x(x: Any = False) -> Any:
    return x


def tool_star_json(*json: str) -> int:
    return len(json)


def tool_short_j(
    flag: Annotated[bool, Parameter(name=["--aaa", "-j"])] = False,
) -> bool:
    return flag


def tool_parse_false(*, working_dir: Annotated[str, Parameter(parse=False)]) -> str:
    return working_dir


def tool_path(p: Path) -> str:
    return str(p)
