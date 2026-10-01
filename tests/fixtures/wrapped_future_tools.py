"""Fixtures with wrapped tools (functools.wraps) and future annotations."""

from __future__ import annotations

import functools
from pathlib import Path

from cisternal.adapters.cli import timed_command


@timed_command("wrapped_tool")
@functools.wraps
def wrapped_tool(p: Path) -> str:
    """A tool wrapped with functools.wraps and timed_command.

    This tests that annotations are resolved through the wrapper's
    __wrapped__ attribute when the wrapper's own __annotations__
    come from the original function via functools.wraps.
    """
    return str(p)


def simple_tool(x: int) -> int:
    """A simple unwrapped tool for baseline comparison."""
    return x + 1
