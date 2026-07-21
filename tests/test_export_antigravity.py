"""Tests for AntigravityEmitter (M13.1: real Antigravity plugin format)."""

from __future__ import annotations

import json
from pathlib import Path

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.export.antigravity import AntigravityEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_antigravity_emit_manifest_minimal_fixture() -> None:
    """M13.1: plugin.json + skills/hooks.json only — no agents, no mcp_config."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    files = AntigravityEmitter().emit(report.bundle)

    assert "plugin.json" in files
    assert "skills/demo-skill/SKILL.md" in files
    assert "hooks.json" in files

    assert "agents/recon.md" not in files
    assert not any(path.startswith("agents/") for path in files)
    assert "gemini-extension.json" not in files
    assert "hooks/hooks.json" not in files
    assert "mcp_config.json" not in files

    plugin = json.loads(files["plugin.json"])
    assert plugin == {
        "name": "fixture-plugin",
        "description": "Minimal manifest for M3.1a tests",
    }

    hooks = json.loads(files["hooks.json"])
    assert set(hooks) == {"fixture-plugin"}
    assert "PreToolUse" in hooks["fixture-plugin"]
    assert "PostToolUse" not in hooks["fixture-plugin"]
    entry = hooks["fixture-plugin"]["PreToolUse"][0]
    assert entry["matcher"] == "run_command"  # Bash remapped
    assert entry["hooks"] == [{"type": "command", "command": "hooks/pre.sh"}]


def test_antigravity_agents_never_emitted() -> None:
    """Antigravity has no file-based agent registration — agents must never appear."""
    from cisterna.assets.bundle import AgentAsset, AssetBundle, BundleMetadata

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        agents=(
            AgentAsset(name="agent-x", description="Agent X", body="Agent body"),
        ),
    )

    files = AntigravityEmitter().emit(bundle)

    assert not any(path.startswith("agents/") for path in files)


def test_antigravity_mcp_command_args_split() -> None:
    """M13.1: mcp_config.json splits command into a bare string + args array."""
    from cisterna.assets.bundle import AssetBundle, BundleMetadata, McpAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        mcp_servers=(
            McpAsset(name="test-mcp", command=("uv", "run", "python", "server.py")),
        ),
    )

    files = AntigravityEmitter().emit(bundle)

    assert ".mcp.json" not in files
    mcp = json.loads(files["mcp_config.json"])
    server = mcp["mcpServers"]["test-mcp"]
    assert server["command"] == "uv"
    assert server["args"] == ["run", "python", "server.py"]


def test_antigravity_unsupported_hook_events_dropped() -> None:
    """M13.1: only PreToolUse/PostToolUse survive; other events are silently dropped."""
    from cisterna.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(
            HookSpecAsset(event="PreToolUse", matcher="Bash", script="pre.sh"),
            HookSpecAsset(event="SessionStart", matcher="*", script="session.sh"),
            HookSpecAsset(event="PreCompact", matcher="*", script="compact.sh"),
        ),
    )

    files = AntigravityEmitter().emit(bundle)
    hooks = json.loads(files["hooks.json"])

    assert set(hooks["p"]) == {"PreToolUse"}
