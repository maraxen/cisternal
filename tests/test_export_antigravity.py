"""Tests for AntigravityEmitter (M13.1: real Antigravity plugin format)."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.antigravity import AntigravityEmitter

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
    from cisternal.assets.bundle import AgentAsset, AssetBundle, BundleMetadata

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
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, McpAsset

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
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset

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


def test_antigravity_mcp_env_passthrough() -> None:
    """M13.2: mcp_config.json carries env vars through when present."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, McpAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        mcp_servers=(
            McpAsset(
                name="test-mcp",
                command=("uv", "run", "python", "server.py"),
                env=(("FOO", "bar"), ("BAZ", "qux")),
            ),
        ),
    )

    files = AntigravityEmitter().emit(bundle)
    server = json.loads(files["mcp_config.json"])["mcpServers"]["test-mcp"]

    assert server["env"] == {"FOO": "bar", "BAZ": "qux"}


def test_antigravity_mcp_no_env_key_when_empty() -> None:
    """M13.2: no env key at all when the server has no env vars (unchanged from M13.1)."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, McpAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        mcp_servers=(McpAsset(name="test-mcp", command=("uv", "run", "server.py")),),
    )

    files = AntigravityEmitter().emit(bundle)
    server = json.loads(files["mcp_config.json"])["mcpServers"]["test-mcp"]

    assert "env" not in server


def test_antigravity_hook_content_bundles_script_file() -> None:
    """M13.2: a hook spec with content writes scripts/<script> and references it."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(
            HookSpecAsset(
                event="PreToolUse",
                matcher="Bash",
                script="pre.sh",
                content="#!/bin/bash\necho pre\n",
            ),
        ),
    )

    files = AntigravityEmitter().emit(bundle)

    assert files["scripts/pre.sh"] == "#!/bin/bash\necho pre\n"
    hooks = json.loads(files["hooks.json"])
    entry = hooks["p"]["PreToolUse"][0]
    assert entry["hooks"] == [{"type": "command", "command": "./scripts/pre.sh"}]


def test_antigravity_hook_without_content_no_script_file() -> None:
    """M13.2: a hook spec without content emits no scripts/ file (back-compat)."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(
            HookSpecAsset(event="PreToolUse", matcher="Bash", script="pre.sh"),
        ),
    )

    files = AntigravityEmitter().emit(bundle)

    assert "scripts/pre.sh" not in files
    assert not any(path.startswith("scripts/") for path in files)
    hooks = json.loads(files["hooks.json"])
    entry = hooks["p"]["PreToolUse"][0]
    assert entry["hooks"] == [{"type": "command", "command": "pre.sh"}]
