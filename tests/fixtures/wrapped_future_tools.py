"""Fixtures with wrapped tools (functools.wraps) and future annotations."""

from __future__ import annotations

import functools
from pathlib import Path

from cisternal.adapters.cli import timed_command


def _wrapped_tool_impl(p: Path) -> str:
    """Inner function for the wrapped tool."""
    return str(p)


def _make_wrapped_tool():
    """Create a wrapped tool using functools.wraps."""
    @functools.wraps(_wrapped_tool_impl)
    def wrapped_tool(*args, **kwargs):
        """A tool wrapped with functools.wraps and timed_command.

        This tests that annotations are resolved through the wrapper's
        __wrapped__ attribute when the wrapper's own __annotations__
        come from the original function via functools.wraps.
        """
        return _wrapped_tool_impl(*args, **kwargs)

    return timed_command("wrapped_tool")(wrapped_tool)


wrapped_tool = _make_wrapped_tool()


def simple_tool(x: int) -> int:
    """A simple unwrapped tool for baseline comparison."""
    return x + 1
