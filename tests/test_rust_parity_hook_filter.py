"""Rust parity hook surface filter behavior (M12.3 / CH-303)."""

from __future__ import annotations

import json

from cisterna.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset
from cisterna.assets.validate_golden import surface_digest_rust_parity
from cisterna.export.cursor import CursorEmitter


def test_rust_parity_includes_copilot_only_hook_on_cursor() -> None:
    """Rust-parity lane passes all hook_specs; legacy cursor export filters by surface."""
    copilot_hook = HookSpecAsset(
        event="PreToolUse",
        matcher="Bash",
        script="hooks/copilot-only.sh",
        surfaces=("copilot",),
    )
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(copilot_hook,),
    )

    legacy_files = CursorEmitter().emit(bundle)
    legacy_plugin = json.loads(legacy_files[".cursor-plugin/plugin.json"])
    assert "hooks" not in legacy_plugin

    rust_files = CursorEmitter(rust_parity=True).emit(bundle)
    assert ".cursor/hooks.json" in rust_files
    assert surface_digest_rust_parity(bundle, "cursor")
