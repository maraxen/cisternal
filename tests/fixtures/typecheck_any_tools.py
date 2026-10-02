"""Fixtures with TYPE_CHECKING imports for testing annotation resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


def tool_with_any_param(x: Any) -> str:
    """A tool using Any that is imported only under TYPE_CHECKING.

    This tests that when Any is resolved through wired.py's globals
    (where it is imported), the tool still registers successfully.
    """
    return f"x={x}"
