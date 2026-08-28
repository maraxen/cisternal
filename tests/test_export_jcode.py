"""Tests for JCodeEmitter."""

from __future__ import annotations

import json
from pathlib import Path

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    MarketplaceAsset,
    McpAsset,
    SkillAsset,
)
from cisternal.export.jcode import JCodeEmitter


def test_jcode_emit_empty_bundle() -> None:
    bundle = AssetBundle(metadata=BundleMetadata(name="empty-jcode", version="1.0.0"))
    files = JCodeEmitter().emit(bundle)

    assert "plugin.json" in files
    plugin = json.loads(files["plugin.json"])
    assert plugin["name"] == "empty-jcode"
    assert plugin["version"] == "1.0.0"
    assert "skills" not in plugin
    assert "agents" not in plugin
    assert "mcpServers" not in plugin
    assert ".jcode/mcp.json" not in files
    assert "marketplace.json" not in files


def test_jcode_emit_full_bundle() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="full-jcode", version="2.0.0", description="Desc"),
        agents=(AgentAsset(name="bot", description="Bot agent", body="Bot body"),),
        skills=(
            SkillAsset(
                name="refactor",
                description="Refactoring",
                body="Refactor steps",
                resources=(("references/rules.md", "Rule 1"),),
            ),
        ),
        mcp_servers=(
            McpAsset(
                name="db-server",
                command=("praxia-db", "serve"),
                env=(("DB_URL", "sqlite:///test.db"),),
            ),
        ),
        marketplace=MarketplaceAsset(name="jcode-market", owner_name="Owner"),
    )
    files = JCodeEmitter().emit(bundle)

    plugin = json.loads(files["plugin.json"])
    assert plugin["name"] == "full-jcode"
    assert plugin["agents"] == ["bot"]
    assert plugin["skills"] == ["refactor"]
    assert "db-server" in plugin["mcpServers"]

    assert "agents/bot.md" in files
    assert "Bot body" in files["agents/bot.md"]

    assert "skills/refactor/SKILL.md" in files
    assert "skills/refactor/references/rules.md" in files
    assert files["skills/refactor/references/rules.md"] == "Rule 1"

    assert ".jcode/mcp.json" in files
    mcp_config = json.loads(files[".jcode/mcp.json"])
    assert "db-server" in mcp_config["mcpServers"]
    assert mcp_config["mcpServers"]["db-server"]["command"] == "praxia-db"
    assert mcp_config["mcpServers"]["db-server"]["args"] == ["serve"]

    assert "marketplace.json" in files
    market = json.loads(files["marketplace.json"])
    assert market["$schema"] == "https://anthropic.com/claude-code/marketplace.schema.json"
    assert market["name"] == "jcode-market"
    assert market["description"] == "Desc"
    assert market["owner"]["name"] == "Owner"
    assert market["plugins"] == [
        {
            "name": "full-jcode",
            "description": "Desc",
            "version": "2.0.0",
            "source": "./",
        }
    ]


def test_jcode_mcp_single_token_no_env() -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        mcp_servers=(McpAsset(name="single", command=("server-bin",)),),
    )
    files = JCodeEmitter().emit(bundle)
    plugin = json.loads(files["plugin.json"])
    server = plugin["mcpServers"]["single"]
    assert server["command"] == "server-bin"
    assert "args" not in server
    assert "env" not in server



def test_jcode_purity_and_determinism(tmp_path: Path) -> None:
    bundle = AssetBundle(
        metadata=BundleMetadata(name="jcode-test", version="1.0.0"),
        skills=(SkillAsset(name="s", body="skill body"),),
    )
    emitter = JCodeEmitter()

    files1 = emitter.emit(bundle)
    files2 = emitter.emit(bundle)
    assert files1 == files2

    for path in files1:
        assert "\\" not in path
