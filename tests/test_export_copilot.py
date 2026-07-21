"""Tests for M3.1b CopilotEmitter (AC-M31b-2)."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.copilot import CopilotEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_copilot_emit_manifest_minimal_fixture() -> None:
    """AC-M31b-2: plugin.json inline hooks and agent/skill files."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    files = CopilotEmitter().emit(report.bundle)

    assert "plugin.json" in files
    assert "agents/recon.agent.md" in files
    assert "skills/demo-skill/SKILL.md" in files

    plugin = json.loads(files["plugin.json"])
    assert plugin["name"] == "fixture-plugin"
    assert plugin["agents"] == ["recon"]
    assert plugin["skills"] == ["demo-skill"]
    assert "hooks" in plugin
    assert "preToolUse" in plugin["hooks"]

    pre = plugin["hooks"]["preToolUse"][0]
    assert pre["matcher"] == "Bash"
    assert pre["hooks"][0]["type"] == "command"
    assert pre["hooks"][0]["command"] == "hooks/pre.sh"
