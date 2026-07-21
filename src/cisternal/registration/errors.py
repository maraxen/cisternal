"""Exceptions for the cisternal registration subsystem.

This module defines error types raised by cisternal.wire() and related
registration machinery.
"""

from __future__ import annotations


class CisternalWireError(Exception):
    """Raised when cisternal.wire() cannot complete because expected tools were
    never registered.

    Attributes:
        missing: Tool names that were expected but not found in the registry
            at wire-time.

    Example::

        try:
            server = cisternal.wire(registry="default")
        except CisternalWireError as e:
            print(e.missing)  # ["tool_a", "tool_b"]
    """

    def __init__(
        self,
        missing: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        self.missing: list[str] = list(missing or [])
        if message is None:
            message = (
                f"cisternal.wire(): expected tools never registered: {self.missing}"
            )
        super().__init__(message)
