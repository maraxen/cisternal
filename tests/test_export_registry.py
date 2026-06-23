"""Tests for M3.2 emitter registry (AC-M32-1..5)."""

from __future__ import annotations

from pathlib import Path

from importlib.metadata import entry_points

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.registry import get_emitter, list_emitter_surfaces

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_entry_points_register_four_builtins() -> None:
    """AC-M32-1: editable install exposes four cisterna.emitters entry points."""
    names = {ep.name for ep in entry_points(group="cisterna.emitters")}
    assert names == {"antigravity", "claude", "copilot", "cursor"}


def test_list_emitter_surfaces_sorted() -> None:
    """AC-M32-2: list_emitter_surfaces returns sorted built-in names."""
    assert list_emitter_surfaces() == (
        "antigravity",
        "claude",
        "copilot",
        "cursor",
    )


def test_get_emitter_claude_matches_direct_ctor() -> None:
    """AC-M32-3: registry claude emitter matches ClaudeEmitter() default."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    direct = ClaudeEmitter().emit(bundle)
    via_registry = get_emitter("claude")
    assert via_registry is not None
    assert via_registry.emit(bundle) == direct


def test_get_emitter_unknown_returns_none() -> None:
    """AC-M32-4: unknown surface returns None."""
    assert get_emitter("linear") is None


def test_get_emitter_broken_factory_returns_none(monkeypatch) -> None:
    """AC-M32-5: factory exception returns None without raising."""

    def _boom(**_kwargs):
        raise RuntimeError("broken factory")

    monkeypatch.setattr(
        "cisterna.export.registry._load_entry_point_factories",
        lambda: {"cursor": _boom},
    )
    assert get_emitter("cursor") is None
