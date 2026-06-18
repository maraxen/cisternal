"""Exceptions for the cisterna registration subsystem.

This module defines error types raised by cisterna.wire() and related
registration machinery.
"""

from __future__ import annotations


class CisternaWireError(Exception):
    """Raised when cisterna.wire() cannot complete because expected tools were
    never registered.

    Attributes:
        missing: Tool names that were expected but not found in the registry
            at wire-time.

    Example::

        try:
            server = cisterna.wire(registry="default")
        except CisternaWireError as e:
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
                f"cisterna.wire(): expected tools never registered: {self.missing}"
            )
        super().__init__(message)
