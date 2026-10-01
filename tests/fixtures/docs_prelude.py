"""Stubs for consumer modules used in documentation examples.

This module is installed into sys.modules under various consumer package names
so that the documentation examples can be tested without requiring the actual
consumer packages to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


# redsox stubs

class SeamExplosionError(Exception):
    """A bare Exception subclass with optional report attribute."""
    pass


@dataclass
class SeamExplosionReport:
    """A report attached to SeamExplosionError."""
    message: str

    def format_text(self) -> str:
        return self.message


def load_config(path: str) -> dict:
    """Load a config file."""
    return {"config": path}


def derive_seams(config: dict) -> list[dict]:
    """Derive seams from a config."""
    return [{"id": 1, "name": "seam1"}]


# alphex stubs

def _render(data: Any) -> str:
    """Render data for CLI output."""
    return str(data)


def _surface(data: Any) -> dict:
    """Return data as a surface/envelope."""
    return {"data": data}


# myxcel stubs

class MyxcelError(Exception):
    """Base error with integer exit code."""
    exit_code: int = 1

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class ConfigError(MyxcelError):
    """Config error with different exit code."""
    exit_code = 2


# contemplex stubs

class ErrorCode(StrEnum):
    """Error codes as string enum."""
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_TASK_TYPE = "INVALID_TASK_TYPE"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    PHASE_MISMATCH = "PHASE_MISMATCH"
    GATE_BLOCKED = "GATE_BLOCKED"
    CORRUPT_SESSION = "CORRUPT_SESSION"
    WRITE_FAILED = "WRITE_FAILED"
    INTERNAL = "INTERNAL"
    STAGING_FAILED = "STAGING_FAILED"


@dataclass
class ContemplexError(Exception):
    """Error with string-valued code."""
    code: ErrorCode
    context: dict[str, Any] | None = None

    def __init__(self, code: ErrorCode, message: str = "", context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.context = context or {}


# MCP server stub

class FakeMCPServer:
    """A stub MCP server that accepts tool registrations."""

    def __init__(self, name: str = "test"):
        self.name = name
        self.tools = {}

    def tool(self, **kwargs):
        """Register a tool."""
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


mcp = FakeMCPServer("docs")
