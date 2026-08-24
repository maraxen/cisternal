"""Tests for AntigravityEmitter (M13.1: real Antigravity plugin format)."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.antigravity import AntigravityEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / ".praxia" / "manifest.toml"
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


def test_antigravity_agents_bundled_into_subagents_skill() -> None:
    """Antigravity synthesizes agents into a skills/{bundle}_subagents directory."""
    from cisternal.assets.bundle import AgentAsset, AssetBundle, BundleMetadata

    bundle = AssetBundle(
        metadata=BundleMetadata(name="mytool", version="1.0.0"),
        agents=(
            AgentAsset(
                name="agent-x",
                description="Agent X role",
                tools=("read_file", "write_to_file"),
                model="flash",
                body="Agent X prompt body",
            ),
        ),
    )

    files = AntigravityEmitter().emit(bundle)

    # Raw agents/ directory is never emitted at root
    assert not any(path.startswith("agents/") for path in files)

    # Synthesized subagents skill
    skill_md_path = "skills/mytool_subagents/SKILL.md"
    ref_path = "skills/mytool_subagents/references/agent-x.md"

    assert skill_md_path in files
    assert ref_path in files

    assert "name: mytool_subagents" in files[skill_md_path]
    assert "agent-x" in files[skill_md_path]
    assert "references/agent-x.md" in files[skill_md_path]

    ref_content = files[ref_path]
    assert "# Subagent Specification: agent-x" in ref_content
    assert "Agent X prompt body" in ref_content
    assert "`read_file`, `write_to_file`" in ref_content


def test_antigravity_rules_emitted_when_description_present() -> None:
    """Antigravity plugin emits rules/AGENTS.md when bundle description is present."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata

    bundle = AssetBundle(
        metadata=BundleMetadata(
            name="p", version="1.0.0", description="Plugin level guidelines"
        )
    )

    files = AntigravityEmitter().emit(bundle)

    assert "rules/AGENTS.md" in files
    assert "Plugin level guidelines" in files["rules/AGENTS.md"]


def test_antigravity_skill_resources_emitted() -> None:
    """Antigravity plugin emits sibling resources of skills."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, SkillAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        skills=(
            SkillAsset(
                name="my-skill",
                body="Skill body",
                resources=(("references/guide.md", "# Guide"),),
            ),
        ),
    )

    files = AntigravityEmitter().emit(bundle)

    assert "skills/my-skill/SKILL.md" in files
    assert "skills/my-skill/references/guide.md" in files
    assert files["skills/my-skill/references/guide.md"] == "# Guide"


def test_antigravity_subagents_fallback_fields() -> None:
    """Antigravity subagents skill uses clean fallback strings for omitted agent fields."""
    from cisternal.assets.bundle import AgentAsset, AssetBundle, BundleMetadata

    bundle = AssetBundle(
        metadata=BundleMetadata(name="mytool", version="1.0.0"),
        agents=(
            AgentAsset(name="sparse-agent", description="A sparse agent"),
        ),
    )

    files = AntigravityEmitter().emit(bundle)
    ref_path = "skills/mytool_subagents/references/sparse-agent.md"
    assert ref_path in files

    ref_content = files[ref_path]
    assert "- **Recommended Model**: `inherit`" in ref_content
    assert "- **Configured Tools**: default tools" in ref_content
    assert "(No custom system prompt)" in ref_content


def test_antigravity_mcp_single_token_no_args() -> None:
    """Single token MCP command emits without args key."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, McpAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        mcp_servers=(
            McpAsset(name="single-mcp", command=("my-server",)),
        ),
    )

    files = AntigravityEmitter().emit(bundle)
    server = json.loads(files["mcp_config.json"])["mcpServers"]["single-mcp"]
    assert server["command"] == "my-server"
    assert "args" not in server


def test_antigravity_hook_matcher_aggregation() -> None:
    """Multiple hooks sharing a matcher aggregate into a single entry list."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset

    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(
            HookSpecAsset(event="PreToolUse", matcher="Bash", script="pre1.sh"),
            HookSpecAsset(event="PreToolUse", matcher="Bash", script="pre2.sh"),
        ),
    )

    files = AntigravityEmitter().emit(bundle)
    hooks = json.loads(files["hooks.json"])
    pre_tool = hooks["p"]["PreToolUse"]

    # Remapped to run_command and aggregated into one matcher entry
    assert len(pre_tool) == 1
    assert pre_tool[0]["matcher"] == "run_command"
    assert pre_tool[0]["hooks"] == [
        {"type": "command", "command": "pre1.sh"},
        {"type": "command", "command": "pre2.sh"},
    ]


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
