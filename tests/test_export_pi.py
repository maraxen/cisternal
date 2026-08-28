"""Tests for PiEmitter."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    McpAsset,
    SkillAsset,
)
from cisternal.export.pi import PiEmitter


def test_pi_emit_empty_bundle() -> None:
    bundle = AssetBundle(metadata=BundleMetadata(name="empty-pkg", version="0.1.0"))
    files = PiEmitter().emit(bundle)

    assert "package.json" in files
    pkg = json.loads(files["package.json"])
    assert pkg["name"] == "empty-pkg"
    assert pkg["version"] == "0.1.0"
    assert pkg["type"] == "module"
    assert pkg["keywords"] == ["pi-package"]
    assert "pi" not in pkg  # Dynamic pruning: no empty pi block
    assert ".pi/mcp.json" not in files
    assert "AGENTS.md" not in files


def test_pi_emit_single_token_mcp_command() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pkg", version="1.0.0"),
        mcp_servers=(
            McpAsset(name="single", command=("praxia-runner",)),
        ),
    )
    files = PiEmitter().emit(bundle)
    assert ".pi/mcp.json" in files
    mcp_config = json.loads(files[".pi/mcp.json"])
    server = mcp_config["mcpServers"]["single"]
    assert server["command"] == "praxia-runner"
    assert "args" not in server
    assert "env" not in server






def test_pi_emit_mcp_servers() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pi-mcp", version="1.0.0"),
        mcp_servers=(
            McpAsset(
                name="pi-tool",
                command=("node", "dist/index.js", "--port", "3000"),
                env=(("NODE_ENV", "production"),),
            ),
        ),
    )
    files = PiEmitter().emit(bundle)
    assert ".pi/mcp.json" in files
    mcp_config = json.loads(files[".pi/mcp.json"])
    assert "mcpServers" in mcp_config
    server = mcp_config["mcpServers"]["pi-tool"]
    assert server["command"] == "node"
    assert server["args"] == ["dist/index.js", "--port", "3000"]
    assert server["env"] == {"NODE_ENV": "production"}


def test_pi_emit_skills_and_prompts() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pi-skills", version="1.0.0"),
        skills=(
            SkillAsset(
                name="tdd-workflow",
                description="TDD procedures",
                body="Write test first, then code.",
                resources=(("references/cheatsheet.md", "# Cheatsheet\n"),),
            ),
        ),
        commands=(
            CommandAsset(name="audit", description="Run audit", body="Audit command body"),
        ),
    )
    files = PiEmitter().emit(bundle)

    pkg = json.loads(files["package.json"])
    assert pkg["pi"]["skills"] == ["./skills"]
    assert pkg["pi"]["prompts"] == ["./prompts"]
    assert "extensions" not in pkg["pi"]  # No ghost extensions

    assert "skills/tdd-workflow/SKILL.md" in files
    assert "skills/tdd-workflow/references/cheatsheet.md" in files
    assert "prompts/audit.md" in files
    assert "Audit command body" in files["prompts/audit.md"]


def test_pi_emit_agents_single_vs_multiple() -> None:
    # Single agent
    single_agent_bundle = AssetBundle(
        metadata=BundleMetadata(name="single", version="1.0.0"),
        agents=(AgentAsset(name="coder", description="Coder", body="Coder body"),),
    )
    files_single = PiEmitter().emit(single_agent_bundle)
    assert "AGENTS.md" in files_single
    assert "name: coder" in files_single["AGENTS.md"]
    assert "Coder body" in files_single["AGENTS.md"]
    assert "# Agents" not in files_single["AGENTS.md"]

    # Multiple agents
    multi_agent_bundle = AssetBundle(
        metadata=BundleMetadata(name="multi", version="1.0.0"),
        agents=(
            AgentAsset(name="auditor", description="Auditor", body="Audit body"),
            AgentAsset(name="coder", description="Coder", body="Coder body"),
        ),
    )
    files_multi = PiEmitter().emit(multi_agent_bundle)
    assert "AGENTS.md" in files_multi
    agents_md = files_multi["AGENTS.md"]
    assert agents_md.startswith("# Agents")
    assert "## auditor" in agents_md
    assert "## coder" in agents_md


def test_pi_purity_and_determinism(tmp_path: Path) -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="pi-test", version="1.0.0"),
        skills=(SkillAsset(name="s", body="skill body"),),
    )
    emitter = PiEmitter()

    files1 = emitter.emit(bundle)
    files2 = emitter.emit(bundle)
    assert files1 == files2

    for path in files1:
        assert "\\" not in path
