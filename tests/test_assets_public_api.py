"""Tests for AC-M3-8 (public API portion) — 6 M3 names importable via cisternal.

AC-M3-8 (spec §5):
  - AssetSpec, AssetBundle, registry_assets, Emitter, ClaudeEmitter, write_bundle
    all importable via ``import cisternal`` (top-level namespace).
  - All 6 names in cisternal.__all__.
  - importlib.import_module("cisternal.cli") succeeds.
"""

from __future__ import annotations

import importlib


# ---------------------------------------------------------------------------
# The 6 M3 public names
# ---------------------------------------------------------------------------


def test_asset_spec_importable_from_cisternal() -> None:
    """cisternal.AssetSpec is importable and is the correct class."""
    import cisternal
    from cisternal.assets.spec import AssetSpec

    assert cisternal.AssetSpec is AssetSpec


def test_asset_bundle_importable_from_cisternal() -> None:
    """cisternal.AssetBundle is importable and is the correct class."""
    import cisternal
    from cisternal.assets.bundle import AssetBundle

    assert cisternal.AssetBundle is AssetBundle


def test_registry_assets_importable_from_cisternal() -> None:
    """cisternal.registry_assets is importable and is the correct callable."""
    import cisternal
    from cisternal.assets.source import registry_assets

    assert cisternal.registry_assets is registry_assets


def test_emitter_importable_from_cisternal() -> None:
    """cisternal.Emitter is importable and is the correct class."""
    import cisternal
    from cisternal.export.base import Emitter

    assert cisternal.Emitter is Emitter


def test_claude_emitter_importable_from_cisternal() -> None:
    """cisternal.ClaudeEmitter is importable and is the correct class."""
    import cisternal
    from cisternal.export.claude import ClaudeEmitter

    assert cisternal.ClaudeEmitter is ClaudeEmitter


def test_write_bundle_importable_from_cisternal() -> None:
    """cisternal.write_bundle is importable and is the correct callable."""
    import cisternal
    from cisternal.export.write import write_bundle

    assert cisternal.write_bundle is write_bundle


# ---------------------------------------------------------------------------
# __all__ membership
# ---------------------------------------------------------------------------


def test_all_m3_names_in_dunder_all() -> None:
    """All 6 M3 names must be listed in cisternal.__all__."""
    import cisternal

    m3_names = {
        "AssetSpec",
        "AssetBundle",
        "registry_assets",
        "Emitter",
        "ClaudeEmitter",
        "write_bundle",
    }
    missing = m3_names - set(cisternal.__all__)
    assert not missing, f"Missing from cisternal.__all__: {missing}"


# ---------------------------------------------------------------------------
# cisternal.cli importable (M4 fastmcp-free path)
# ---------------------------------------------------------------------------


def test_cisternal_cli_importable_via_importlib() -> None:
    """importlib.import_module('cisternal.cli') must succeed."""
    mod = importlib.import_module("cisternal.cli")
    assert mod is not None
    assert hasattr(mod, "app"), "cisternal.cli must expose 'app' (cyclopts App)"


def test_cisternal_cli_app_is_cyclopts_app() -> None:
    """cisternal.cli.app must be a cyclopts.App instance."""
    import cyclopts

    mod = importlib.import_module("cisternal.cli")
    assert isinstance(mod.app, cyclopts.App), (
        f"cisternal.cli.app must be cyclopts.App; got {type(mod.app)}"
    )


# ---------------------------------------------------------------------------
# Smoke: names are usable (not just importable)
# ---------------------------------------------------------------------------


def test_asset_spec_constructible() -> None:
    """AssetSpec from cisternal namespace is constructible."""
    import cisternal

    spec = cisternal.AssetSpec(
        name="smoke_tool",
        kind="command",
        description="Smoke test tool.",
        params=("x", "y"),
        source="default",
    )
    assert spec.name == "smoke_tool"
    assert spec.params == ("x", "y")


def test_asset_bundle_constructible() -> None:
    """AssetBundle from cisternal namespace is constructible."""
    import cisternal

    from cisternal.assets.bundle import AssetBundle, BundleMetadata

    # Verify it's the same class available via public namespace.
    assert cisternal.AssetBundle is AssetBundle
    bundle = AssetBundle(metadata=BundleMetadata(name="n", version="1.0.0"))
    assert bundle.metadata.name == "n"
    assert bundle.commands == ()


def test_emitter_is_abstract_from_public_api() -> None:
    """cisternal.Emitter cannot be instantiated (ABC via public API)."""
    import cisternal
    import pytest as _pytest

    with _pytest.raises(TypeError):
        cisternal.Emitter()  # type: ignore[abstract]


def test_claude_emitter_instantiable_from_public_api() -> None:
    """cisternal.ClaudeEmitter can be instantiated and called from the public API."""
    import cisternal
    from cisternal.assets.bundle import AssetBundle, BundleMetadata

    emitter = cisternal.ClaudeEmitter()
    bundle = AssetBundle(metadata=BundleMetadata(name="pub", version="0.0.1"))
    files = emitter.emit(bundle)
    assert ".claude-plugin/plugin.json" in files


def test_write_bundle_callable_from_public_api(tmp_path: object) -> None:
    """cisternal.write_bundle is callable with a file dict and a path."""
    import cisternal
    from pathlib import Path

    assert callable(cisternal.write_bundle)
    # Smoke: call with an empty dict (must not raise).
    result = cisternal.write_bundle({}, Path(str(tmp_path)), dry_run=True)
    assert result.files == ()
