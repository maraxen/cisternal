"""Tests for HookSpec surface filter (AC-M31b-3, L15)."""

from __future__ import annotations

import json

from cisterna.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset
from cisterna.export.copilot import CopilotEmitter
from cisterna.export.cursor import CursorEmitter
from cisterna.export.hooks import hooks_for_surface


def test_hooks_for_surface_empty_means_all() -> None:
    spec = HookSpecAsset(
        event="PreToolUse",
        matcher="*",
        script="hook.sh",
        surfaces=(),
    )
    assert hooks_for_surface((spec,), "cursor") == (spec,)
    assert hooks_for_surface((spec,), "copilot") == (spec,)


def test_hooks_for_surface_filters_by_token() -> None:
    cursor_only = HookSpecAsset(
        event="PreToolUse",
        matcher="Bash",
        script="cursor.sh",
        surfaces=("cursor",),
    )
    copilot_only = HookSpecAsset(
        event="PostToolUse",
        matcher="Write",
        script="copilot.sh",
        surfaces=("copilot",),
    )
    specs = (cursor_only, copilot_only)

    assert hooks_for_surface(specs, "cursor") == (cursor_only,)
    assert hooks_for_surface(specs, "copilot") == (copilot_only,)


def test_cursor_only_hook_not_in_copilot_export() -> None:
    """AC-M31b-3: surfaces=['cursor'] hook appears only on cursor export."""
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(
            HookSpecAsset(
                event="PreToolUse",
                matcher="Bash",
                script="only-cursor.sh",
                surfaces=("cursor",),
            ),
        ),
    )

    cursor_plugin = json.loads(CursorEmitter().emit(bundle)[".cursor-plugin/plugin.json"])
    copilot_plugin = json.loads(CopilotEmitter().emit(bundle)["plugin.json"])

    assert "hooks" in cursor_plugin
    assert "hooks" not in copilot_plugin
