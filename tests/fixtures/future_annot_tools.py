"""Fixtures using from __future__ import annotations for testing A9 fix."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

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
