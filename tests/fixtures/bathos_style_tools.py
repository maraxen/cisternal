"""Fixtures with post-def __annotations__ mutation (bathos pattern)."""

from __future__ import annotations

from typing import Annotated
from cyclopts import Parameter


def tool_with_mutated_annotations(x: int = 0) -> int:
    """A tool whose annotations are mutated after definition.

    This mimics the bathos pattern (bathos/src/bathos/mcp.py:313-325)
    where __annotations__ are set to real objects after the def.
    """
    return x * 2


# Mutate the annotations to store real objects instead of strings
tool_with_mutated_annotations.__annotations__["x"] = Annotated[
    int, Parameter(name=["--x", "-n"])
]
tool_with_mutated_annotations.__annotations__["return"] = int
