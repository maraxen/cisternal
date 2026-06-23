"""Emitter discovery and dispatch via importlib.metadata entry points (M3.2)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any

from cisterna.export.antigravity import AntigravityEmitter
from cisterna.export.base import Emitter
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.copilot import CopilotEmitter
from cisterna.export.cursor import CursorEmitter

_log = logging.getLogger("cisterna.export.registry")

_ENTRY_POINT_GROUP = "cisterna.emitters"

def claude_factory(*, emit_command_bodies: bool = False, **_kwargs: Any) -> ClaudeEmitter:
    return ClaudeEmitter(emit_command_bodies=emit_command_bodies)


def cursor_factory(**_kwargs: Any) -> CursorEmitter:
    return CursorEmitter()


def copilot_factory(**_kwargs: Any) -> CopilotEmitter:
    return CopilotEmitter()


def antigravity_factory(**_kwargs: Any) -> AntigravityEmitter:
    return AntigravityEmitter()


def _builtin_factories() -> dict[str, Callable[..., Emitter]]:
    return {
        "antigravity": antigravity_factory,
        "claude": claude_factory,
        "copilot": copilot_factory,
        "cursor": cursor_factory,
    }


def _load_entry_point_factories() -> dict[str, Callable[..., Emitter]]:
    factories = _builtin_factories()
    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except TypeError:
        # Python <3.10 compatibility path not needed (requires-python >=3.13).
        eps = entry_points().select(group=_ENTRY_POINT_GROUP)

    for ep in eps:
        try:
            factory = ep.load()
        except Exception:
            _log.warning(
                "cisterna.export.registry: failed to load entry point %r",
                ep.name,
                exc_info=True,
            )
            continue
        if not callable(factory):
            _log.warning(
                "cisterna.export.registry: entry point %r is not callable",
                ep.name,
            )
            continue
        factories[ep.name] = factory
    return factories


def list_emitter_surfaces() -> tuple[str, ...]:
    """Return sorted registered emitter surface names."""
    return tuple(sorted(_load_entry_point_factories()))


def get_emitter(surface: str, *, emit_command_bodies: bool = False) -> Emitter | None:
    """Return an emitter for *surface*, or None if unknown or load failed."""
    factories = _load_entry_point_factories()
    factory = factories.get(surface)
    if factory is None:
        return None
    try:
        if surface == "claude":
            return factory(emit_command_bodies=emit_command_bodies)
        return factory()
    except Exception:
        _log.warning(
            "cisterna.export.registry: factory for surface %r failed",
            surface,
            exc_info=True,
        )
        return None
