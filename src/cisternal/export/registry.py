"""Emitter discovery and dispatch via importlib.metadata entry points (M3.2)."""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any

from cisternal.export.antigravity import AntigravityEmitter
from cisternal.export.base import Emitter
from cisternal.export.claude import ClaudeEmitter
from cisternal.export.copilot import CopilotEmitter
from cisternal.export.cursor import CursorEmitter
from cisternal.export.jcode import JCodeEmitter
from cisternal.export.opencode import OpenCodeEmitter
from cisternal.export.pi import PiEmitter

_log = logging.getLogger("cisternal.export.registry")

_ENTRY_POINT_GROUP = "cisternal.emitters"

def claude_factory(*, emit_command_bodies: bool = False, **_kwargs: Any) -> ClaudeEmitter:
    return ClaudeEmitter(emit_command_bodies=emit_command_bodies)


def cursor_factory(**_kwargs: Any) -> CursorEmitter:
    return CursorEmitter()


def copilot_factory(**_kwargs: Any) -> CopilotEmitter:
    return CopilotEmitter()


def antigravity_factory(**_kwargs: Any) -> AntigravityEmitter:
    return AntigravityEmitter()


def opencode_factory(**_kwargs: Any) -> OpenCodeEmitter:
    return OpenCodeEmitter()


def pi_factory(**_kwargs: Any) -> PiEmitter:
    return PiEmitter()


def jcode_factory(**_kwargs: Any) -> JCodeEmitter:
    return JCodeEmitter()


def _builtin_factories() -> dict[str, Callable[..., Emitter]]:
    return {
        "antigravity": antigravity_factory,
        "claude": claude_factory,
        "copilot": copilot_factory,
        "cursor": cursor_factory,
        "jcode": jcode_factory,
        "opencode": opencode_factory,
        "pi": pi_factory,
    }



def _load_entry_point_factories() -> dict[str, Callable[..., Emitter]]:
    factories = _builtin_factories()
    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except TypeError:
        try:
            eps = importlib.metadata.entry_points().select(group=_ENTRY_POINT_GROUP)
        except Exception:
            _log.warning("cisternal.export.registry: entry_points failed", exc_info=True)
            return factories
    except Exception:
        _log.warning("cisternal.export.registry: entry_points query failed", exc_info=True)
        return factories

    for ep in eps:
        try:
            factory = ep.load()
        except Exception:
            _log.warning(
                "cisternal.export.registry: failed to load entry point %r",
                ep.name,
                exc_info=True,
            )
            continue
        if not callable(factory):
            _log.warning(
                "cisternal.export.registry: entry point %r is not callable",
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
        try:
            return factory(emit_command_bodies=emit_command_bodies)
        except TypeError:
            return factory()
    except Exception:
        _log.warning(
            "cisternal.export.registry: factory for surface %r failed",
            surface,
            exc_info=True,
        )
        return None

