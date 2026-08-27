"""Tests for OpenCodeEmitter."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    McpAsset,
    SkillAsset,
)
from cisternal.export.opencode import OpenCodeEmitter


def test_opencode_emit_empty_bundle() -> None:
    bundle = AssetBundle(metadata=BundleMetadata(name="empty", version="1.0.0"))
    files = OpenCodeEmitter().emit(bundle)

    assert "opencode.json" in files
    config = json.loads(files["opencode.json"])
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert "mcp" not in config


def test_opencode_emit_mcp_servers() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pkg", version="1.0.0"),
        mcp_servers=(
            McpAsset(
                name="test-server",
                command=("praxia", "mcp", "--flag"),
                env=(("API_KEY", "secret"), ("ENV", "dev")),
            ),
        ),
    )
    files = OpenCodeEmitter().emit(bundle)
    config = json.loads(files["opencode.json"])
    assert "mcp" in config
    assert "test-server" in config["mcp"]
    server = config["mcp"]["test-server"]
    assert server["type"] == "local"
    assert server["command"] == ["praxia", "mcp", "--flag"]
    assert server["environment"] == {"API_KEY": "secret", "ENV": "dev"}
    assert "env" not in server  # Strict OpenCode schema conformance: "environment" not "env"


def test_opencode_emit_skills_with_resources() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pkg", version="1.0.0"),
        skills=(
            SkillAsset(
                name="my-skill",
                description="Skill description",
                body="Instructions here",
                triggers=("run my skill",),
                resources=(("references/guide.md", "# Guide\n"),),
            ),
            SkillAsset(name="ghost", description="No body", body=""),
        ),
    )
    files = OpenCodeEmitter().emit(bundle)

    assert ".opencode/skills/my-skill/SKILL.md" in files
    assert "skills/my-skill/SKILL.md" in files
    assert files[".opencode/skills/my-skill/SKILL.md"] == files["skills/my-skill/SKILL.md"]
    assert ".opencode/skills/my-skill/references/guide.md" in files
    assert "skills/my-skill/references/guide.md" in files

    # Ghost skill with empty body is omitted
    assert ".opencode/skills/ghost/SKILL.md" not in files
    assert "skills/ghost/SKILL.md" not in files


def test_opencode_emit_agents_and_commands() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pkg", version="1.0.0"),
        agents=(
            AgentAsset(
                name="coder",
                description="Coding specialist",
                tools=("bash", "edit"),
                model="claude-sonnet",
                body="You are a coder.",
            ),
            AgentAsset(name="empty-agent", body=""),
        ),
        commands=(
            CommandAsset(name="review", description="Review changes", body="Review code diffs"),
            CommandAsset(name="empty-cmd", body=""),
        ),
    )
    files = OpenCodeEmitter().emit(bundle)

    assert ".opencode/agents/coder.md" in files
    assert "You are a coder." in files[".opencode/agents/coder.md"]
    assert ".opencode/agents/empty-agent.md" not in files

    assert ".opencode/commands/review.md" in files
    assert "Review code diffs" in files[".opencode/commands/review.md"]
    assert ".opencode/commands/empty-cmd.md" not in files


def test_opencode_yaml_scalar_safety() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        agents=(
            AgentAsset(
                name="audit:sec",
                model="vendor/model:v1",
                description="Desc # with comment",
                body="Agent instructions",
            ),
            AgentAsset(name="100", body="Numbered agent"),
        ),
        skills=(
            SkillAsset(
                name="16:9",
                description="Ratio skill",
                body="Skill instructions",
            ),
        ),
        commands=(
            CommandAsset(name="cmd:run", body="Run command body"),
        ),
    )
    files = OpenCodeEmitter().emit(bundle)
    assert ".opencode/agents/audit:sec.md" in files
    agent_content = files[".opencode/agents/audit:sec.md"]
    frontmatter = yaml.safe_load(agent_content.split("---")[1])
    assert frontmatter["name"] == "audit:sec"
    assert frontmatter["model"] == "vendor/model:v1"


def test_opencode_empty_body_skill_with_resources_omitted() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        skills=(
            SkillAsset(
                name="ghost",
                description="No body",
                body="",
                resources=(("references/guide.md", "Content"),),
            ),
        ),
    )
    files = OpenCodeEmitter().emit(bundle)
    assert ".opencode/skills/ghost/SKILL.md" not in files
    assert ".opencode/skills/ghost/references/guide.md" not in files
    assert "skills/ghost/SKILL.md" not in files


def test_opencode_purity_and_determinism(tmp_path: Path) -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="purity-test", version="1.0.0"),
        skills=(SkillAsset(name="s", body="skill body"),),
    )
    emitter = OpenCodeEmitter()

    files1 = emitter.emit(bundle)
    files2 = emitter.emit(bundle)
    assert files1 == files2

    # Forward-slash paths invariant
    for path in files1:
        assert "\\" not in path

