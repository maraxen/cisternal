"""Shared pytest fixtures and helpers for cisterna registration tests.

Provides a single shared SpyAdapter class used across test modules to avoid
duplication and ensure consistent spy behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class SpyAdapter:
    """Minimal spy adapter for asserting no adapter methods are called.

    Tracks all calls to emit_start, emit_end, emit_error, shape_ok, shape_error.
    Does NOT subclass cisterna.adapters.base.AdapterBase to avoid a hard import
    dependency on adapters from other repos.  wire() and compose_mcp_callable()
    accept any object for the 'adapter' parameter and intentionally never call
    any method on it (C5 / AC-M2-6).
    """

    calls: list[str] = field(default_factory=list)

    def emit_start(self, *a: Any, **kw: Any) -> None:
        self.calls.append("emit_start")

    def emit_end(self, *a: Any, **kw: Any) -> None:
        self.calls.append("emit_end")

    def emit_error(self, *a: Any, **kw: Any) -> None:
        self.calls.append("emit_error")

    def shape_ok(self, *a: Any, **kw: Any) -> Any:
        self.calls.append("shape_ok")

    def shape_error(self, *a: Any, **kw: Any) -> Any:
        self.calls.append("shape_error")


@pytest.fixture()
def spy_adapter() -> SpyAdapter:
    """Return a fresh SpyAdapter instance for asserting no adapter methods are called."""
    return SpyAdapter()
