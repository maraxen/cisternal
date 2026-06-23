"""Tests for M3.1c AntigravityEmitter (AC-M31c-1)."""

from __future__ import annotations

import json
from pathlib import Path

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.export.antigravity import AntigravityEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_antigravity_emit_manifest_minimal_fixture() -> None:
    """AC-M31c-1: gemini-extension.json plus agents/skills/hooks files."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    files = AntigravityEmitter().emit(report.bundle)

    assert "gemini-extension.json" in files
    assert "agents/recon.md" in files
    assert "skills/demo-skill/SKILL.md" in files
    assert "hooks/hooks.json" in files

    extension = json.loads(files["gemini-extension.json"])
    assert extension["name"] == "fixture-plugin"
    assert extension["contextFileName"] == "GEMINI.md"
    assert extension["agents"] == ["recon"]
    assert extension["skills"] == ["demo-skill"]
    assert extension["commands"] == ["foo"]
    assert extension["settings"] == {}

    hooks = json.loads(files["hooks/hooks.json"])
    assert "hooks" in hooks
    assert "PreToolUse" in hooks["hooks"]
