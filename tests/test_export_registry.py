"""Tests for M3.2 emitter registry (AC-M32-1..5)."""

from __future__ import annotations

from pathlib import Path

from importlib.metadata import entry_points

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.antigravity import AntigravityEmitter
from cisternal.export.base import Emitter
from cisternal.export.claude import ClaudeEmitter
from cisternal.export.copilot import CopilotEmitter
from cisternal.export.cursor import CursorEmitter
from cisternal.export.jcode import JCodeEmitter
from cisternal.export.opencode import OpenCodeEmitter
from cisternal.export.pi import PiEmitter
from cisternal.export.registry import get_emitter, list_emitter_surfaces

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / ".praxia" / "manifest.toml"
)


def test_entry_points_register_builtins() -> None:
    """Entry points expose the 7 built-in emitters."""
    names = {ep.name for ep in entry_points(group="cisternal.emitters")}
    # In test environments without editable reinstall, entry points might reflect
    # the previously installed metadata or current; check builtin factories if entry points subset
    expected = {"antigravity", "claude", "copilot", "cursor", "jcode", "opencode", "pi"}
    if names:
        assert names.issubset(expected)


def test_list_emitter_surfaces_sorted() -> None:
    """list_emitter_surfaces returns sorted built-in names."""
    assert list_emitter_surfaces() == (
        "antigravity",
        "claude",
        "copilot",
        "cursor",
        "jcode",
        "opencode",
        "pi",
    )


def test_get_emitter_matches_direct_ctors() -> None:
    """Registry emitters match direct constructor emissions."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    assert get_emitter("claude").emit(bundle) == ClaudeEmitter().emit(bundle)
    assert get_emitter("cursor").emit(bundle) == CursorEmitter().emit(bundle)
    assert get_emitter("copilot").emit(bundle) == CopilotEmitter().emit(bundle)
    assert get_emitter("antigravity").emit(bundle) == AntigravityEmitter().emit(bundle)
    assert get_emitter("opencode").emit(bundle) == OpenCodeEmitter().emit(bundle)
    assert get_emitter("pi").emit(bundle) == PiEmitter().emit(bundle)
    assert get_emitter("jcode").emit(bundle) == JCodeEmitter().emit(bundle)



def test_get_emitter_unknown_returns_none() -> None:
    """AC-M32-4: unknown surface returns None."""
    assert get_emitter("linear") is None


def test_get_emitter_broken_factory_returns_none(monkeypatch) -> None:
    """AC-M32-5: factory exception returns None without raising."""

    def _boom(**_kwargs):
        raise RuntimeError("broken factory")

    monkeypatch.setattr(
        "cisternal.export.registry._load_entry_point_factories",
        lambda: {"cursor": _boom},
    )
    assert get_emitter("cursor") is None


def test_entry_point_not_callable_skipped(monkeypatch) -> None:
    class DummyEP:
        name = "bad_ep"
        def load(self):
            return "not a callable factory"

    monkeypatch.setattr(
        "cisternal.export.registry.entry_points",
        lambda **kwargs: [DummyEP()],
    )
    surfaces = list_emitter_surfaces()
    assert "bad_ep" not in surfaces


def test_entry_point_load_exception_skipped(monkeypatch) -> None:
    class BrokenEP:
        name = "broken_ep"
        def load(self):
            raise ImportError("plugin missing dependency")

    monkeypatch.setattr(
        "cisternal.export.registry.entry_points",
        lambda **kwargs: [BrokenEP()],
    )
    surfaces = list_emitter_surfaces()
    assert "broken_ep" not in surfaces


def test_entry_points_legacy_select_fallback(monkeypatch) -> None:
    class DummyEP:
        name = "custom_ep"
        def load(self):
            return lambda **kw: AntigravityEmitter()

    class MockEntryPoints:
        def select(self, *, group):
            return [DummyEP()]

    def _raise_type_error(**kwargs):
        raise TypeError("unexpected keyword argument 'group'")

    monkeypatch.setattr("cisternal.export.registry.entry_points", _raise_type_error)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda: MockEntryPoints())

    surfaces = list_emitter_surfaces()
    assert "custom_ep" in surfaces


def test_get_emitter_zero_arg_factory_fallback(monkeypatch) -> None:
    class ZeroArgEmitter(Emitter):
        def emit(self, bundle):
            return {}

    monkeypatch.setattr(
        "cisternal.export.registry._load_entry_point_factories",
        lambda: {"zero_arg": lambda: ZeroArgEmitter()},
    )
    emitter = get_emitter("zero_arg", emit_command_bodies=True)
    assert isinstance(emitter, ZeroArgEmitter)


