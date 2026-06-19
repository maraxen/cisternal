"""Tests for AC-M3-8 (public API portion) — 6 M3 names importable via cisterna.

AC-M3-8 (spec §5):
  - AssetSpec, AssetBundle, registry_assets, Emitter, ClaudeEmitter, write_bundle
    all importable via ``import cisterna`` (top-level namespace).
  - All 6 names in cisterna.__all__.
  - importlib.import_module("cisterna.cli") succeeds.
"""

from __future__ import annotations

import importlib


# ---------------------------------------------------------------------------
# The 6 M3 public names
# ---------------------------------------------------------------------------


def test_asset_spec_importable_from_cisterna() -> None:
    """cisterna.AssetSpec is importable and is the correct class."""
    import cisterna
    from cisterna.assets.spec import AssetSpec

    assert cisterna.AssetSpec is AssetSpec


def test_asset_bundle_importable_from_cisterna() -> None:
    """cisterna.AssetBundle is importable and is the correct class."""
    import cisterna
    from cisterna.assets.bundle import AssetBundle

    assert cisterna.AssetBundle is AssetBundle


def test_registry_assets_importable_from_cisterna() -> None:
    """cisterna.registry_assets is importable and is the correct callable."""
    import cisterna
    from cisterna.assets.source import registry_assets

    assert cisterna.registry_assets is registry_assets


def test_emitter_importable_from_cisterna() -> None:
    """cisterna.Emitter is importable and is the correct class."""
    import cisterna
    from cisterna.export.base import Emitter

    assert cisterna.Emitter is Emitter


def test_claude_emitter_importable_from_cisterna() -> None:
    """cisterna.ClaudeEmitter is importable and is the correct class."""
    import cisterna
    from cisterna.export.claude import ClaudeEmitter

    assert cisterna.ClaudeEmitter is ClaudeEmitter


def test_write_bundle_importable_from_cisterna() -> None:
    """cisterna.write_bundle is importable and is the correct callable."""
    import cisterna
    from cisterna.export.write import write_bundle

    assert cisterna.write_bundle is write_bundle


# ---------------------------------------------------------------------------
# __all__ membership
# ---------------------------------------------------------------------------


def test_all_m3_names_in_dunder_all() -> None:
    """All 6 M3 names must be listed in cisterna.__all__."""
    import cisterna

    m3_names = {
        "AssetSpec",
        "AssetBundle",
        "registry_assets",
        "Emitter",
        "ClaudeEmitter",
        "write_bundle",
    }
    missing = m3_names - set(cisterna.__all__)
    assert not missing, f"Missing from cisterna.__all__: {missing}"


# ---------------------------------------------------------------------------
# cisterna.cli importable (M4 fastmcp-free path)
# ---------------------------------------------------------------------------


def test_cisterna_cli_importable_via_importlib() -> None:
    """importlib.import_module('cisterna.cli') must succeed."""
    mod = importlib.import_module("cisterna.cli")
    assert mod is not None
    assert hasattr(mod, "app"), "cisterna.cli must expose 'app' (cyclopts App)"


def test_cisterna_cli_app_is_cyclopts_app() -> None:
    """cisterna.cli.app must be a cyclopts.App instance."""
    import cyclopts

    mod = importlib.import_module("cisterna.cli")
    assert isinstance(mod.app, cyclopts.App), (
        f"cisterna.cli.app must be cyclopts.App; got {type(mod.app)}"
    )


# ---------------------------------------------------------------------------
# Smoke: names are usable (not just importable)
# ---------------------------------------------------------------------------


def test_asset_spec_constructible() -> None:
    """AssetSpec from cisterna namespace is constructible."""
    import cisterna

    spec = cisterna.AssetSpec(
        name="smoke_tool",
        kind="command",
        description="Smoke test tool.",
        params=("x", "y"),
        source="default",
    )
    assert spec.name == "smoke_tool"
    assert spec.params == ("x", "y")


def test_asset_bundle_constructible() -> None:
    """AssetBundle from cisterna namespace is constructible."""
    import cisterna

    from cisterna.assets.bundle import AssetBundle, BundleMetadata

    # Verify it's the same class available via public namespace.
    assert cisterna.AssetBundle is AssetBundle
    bundle = AssetBundle(metadata=BundleMetadata(name="n", version="1.0.0"))
    assert bundle.metadata.name == "n"
    assert bundle.commands == ()


def test_emitter_is_abstract_from_public_api() -> None:
    """cisterna.Emitter cannot be instantiated (ABC via public API)."""
    import cisterna
    import pytest as _pytest

    with _pytest.raises(TypeError):
        cisterna.Emitter()  # type: ignore[abstract]


def test_claude_emitter_instantiable_from_public_api() -> None:
    """cisterna.ClaudeEmitter can be instantiated and called from the public API."""
    import cisterna
    from cisterna.assets.bundle import AssetBundle, BundleMetadata

    emitter = cisterna.ClaudeEmitter()
    bundle = AssetBundle(metadata=BundleMetadata(name="pub", version="0.0.1"))
    files = emitter.emit(bundle)
    assert ".claude-plugin/plugin.json" in files


def test_write_bundle_callable_from_public_api(tmp_path: object) -> None:
    """cisterna.write_bundle is callable with a file dict and a path."""
    import cisterna
    from pathlib import Path

    assert callable(cisterna.write_bundle)
    # Smoke: call with an empty dict (must not raise).
    result = cisterna.write_bundle({}, Path(str(tmp_path)), dry_run=True)
    assert result.files == ()
