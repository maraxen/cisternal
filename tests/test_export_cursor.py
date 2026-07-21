"""Tests for M3.1b CursorEmitter (AC-M31b-1, AC-M31b-6)."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.bundle import AgentAsset, AssetBundle, BundleMetadata
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.cursor import CursorEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_cursor_emit_manifest_minimal_fixture() -> None:
    """AC-M31b-1: manifest_minimal emits plugin.json, hooks, agent/skill files."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    files = CursorEmitter().emit(report.bundle)

    assert ".cursor-plugin/plugin.json" in files
    assert ".cursor/hooks.json" in files
    assert "agents/recon.agent.md" in files
    assert "skills/demo-skill/SKILL.md" in files

    plugin = json.loads(files[".cursor-plugin/plugin.json"])
    assert plugin["name"] == "fixture-plugin"
    assert plugin["version"] == "1.2.3"
    assert plugin["agents"] == ["recon"]
    assert plugin["skills"] == ["demo-skill"]

    hooks_file = json.loads(files[".cursor/hooks.json"])
    assert hooks_file["version"] == 1
    assert "beforeShellExecution" in hooks_file["hooks"]

    assert "Agent body for tests" in files["agents/recon.agent.md"]
    assert "Skill content" in files["skills/demo-skill/SKILL.md"]


def test_cursor_fail_closed_omits_agents_key_without_body() -> None:
    """AC-M31b-6: agents key absent when agent bodies would not be emitted."""
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        agents=(
            AgentAsset(name="ghost", description="Ghost", body=""),
            AgentAsset(name="present", description="Here", body="Agent body\n"),
        ),
    )

    files = CursorEmitter().emit(bundle)
    plugin = json.loads(files[".cursor-plugin/plugin.json"])

    assert "ghost" not in plugin.get("agents", [])
    assert plugin["agents"] == ["present"]
    assert "agents/present.agent.md" in files
    assert "agents/ghost.agent.md" not in files


def test_cursor_omits_agents_and_skills_keys_when_all_empty() -> None:
    """L17: no empty agents/skills arrays in plugin.json."""
    bundle = AssetBundle(
        metadata=BundleMetadata(name="empty", version="0.0.0"),
        agents=(AgentAsset(name="no-body", body=""),),
        skills=(),
    )

    plugin = json.loads(CursorEmitter().emit(bundle)[".cursor-plugin/plugin.json"])
    assert "agents" not in plugin
    assert "skills" not in plugin


def test_cursor_emit_is_pure_no_filesystem(tmp_path: Path) -> None:
    """CursorEmitter.emit performs zero I/O."""
    bundle = AssetBundle(metadata=BundleMetadata(name="x", version="1.0.0"))
    marker = tmp_path / "marker"
    marker.write_text("untouched", encoding="utf-8")

    CursorEmitter().emit(bundle)

    assert marker.read_text(encoding="utf-8") == "untouched"
