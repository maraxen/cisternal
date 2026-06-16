"""Typer CLI timing adapter (spec §4.2, AC-CLI-1).

Provides CliAdapter for Typer CLI commands and timed_command decorator
to instrument command execution with cli.cmd_start and cli.cmd_end events.

The decorator is CLI-specific: unlike MCP adapters, it re-raises exceptions
to the CLI, which owns exit codes.
"""

import functools
import time
from typing import Any

from cisterna import emit_event
from cisterna.adapters.base import AdapterBase


class CliAdapter(AdapterBase):
    """Adapter for Typer CLI commands.

    Event names (spec §4.2): cli.cmd_start, cli.cmd_end.
    Response shape: passthrough (CLI owns stdout/exit codes).
    """

    ALLOWED_NAMES = frozenset({"cli.cmd_start", "cli.cmd_end"})

    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shape success: passthrough result (CLI owns output)."""
        return result

    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shape error: not used by CLI (exceptions re-raise directly)."""
        return None


def timed_command(cmd_name: str | None = None):
    """Decorator to emit CLI command timing events.

    Emits cli.cmd_start before execution and cli.cmd_end after.
    On exception: cli.cmd_end with ok=False, exc_type, then re-raises
    (CLI owns the exit code).

    Args:
        cmd_name: Optional custom command name. If None, uses function.__name__.

    Returns:
        Decorator function.

    Example:
        @timed_command()
        def my_command(arg1: str):
            print(f"Running {arg1}")
            return 0

        @timed_command("custom_name")
        def another_command():
            return 0
    """

    def decorator(fn):
        name = cmd_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            emit_event("cli.cmd_start", cmd=name)
            t0 = time.monotonic_ns()
            try:
                result = fn(*args, **kwargs)
                duration_ms = (time.monotonic_ns() - t0) / 1e6
                emit_event("cli.cmd_end", cmd=name, duration_ms=duration_ms, ok=True)
                return result
            except Exception as exc:
                duration_ms = (time.monotonic_ns() - t0) / 1e6
                emit_event(
                    "cli.cmd_end",
                    cmd=name,
                    duration_ms=duration_ms,
                    ok=False,
                    exc_type=type(exc).__name__,
                )
                raise

        return wrapper

    return decorator
