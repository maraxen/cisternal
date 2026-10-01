"""Fixtures using from __future__ import annotations for testing A9 fix."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from cyclopts import Parameter

if TYPE_CHECKING:
    from collections.abc import Callable

    UnresolvedType = Callable[[int], str]


def tool_with_path_param(p: Path) -> str:
    """A tool using Path annotation under future annotations."""
    return str(p)


def tool_with_type_checking_return() -> UnresolvedType:
    """Tool whose return type is only available under TYPE_CHECKING.

    This tests that an unresolvable return type does not raise
    (return type is not checked during parameter hint resolution).
    """

    def inner(x: int) -> str:
        return str(x)

    return inner


def tool_with_annotated_param(p: Annotated[Path, "description"]) -> str:
    """Tool using Annotated with Path under future annotations."""
    return str(p)


def tool_with_cyclopts_param(
    p: Annotated[Path, Parameter(name=["--path", "-p"], help="A path.")],
) -> str:
    """Tool using Annotated[Path, Parameter(...)] under future annotations (test 9)."""
    return str(p)


def tool_with_unresolvable_param(x: NotImportedAnywhere) -> str:  # noqa: F821
    """Parameter annotation names something that exists nowhere (test 16c)."""
    return str(x)


def tool_with_malformed_param(x: int) -> str:
    """Parameter annotation is the malformed string ``"list[int"`` (test 16c).

    The malformed string is stored after the ``def`` because, under
    ``from __future__ import annotations``, writing it in the signature would
    double-quote it.
    """
    return str(x)


tool_with_malformed_param.__annotations__["x"] = "list[int"
