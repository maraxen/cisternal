"""Tests for M3.1a manifest and composite asset sources (W2)."""

from __future__ import annotations

from pathlib import Path

import cisterna
from cisterna.assets.composite import CompositeAssetSource
from cisterna.assets.manifest import ManifestAssetSource
from cisterna.assets.source import registry_bundle

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "manifest_minimal"
MANIFEST = FIXTURE_ROOT / "manifest.toml"


def test_manifest_loads_skills_agents_hooks_commands() -> None:
    """AC-M31a-1: manifest loads IR kinds without raising."""
    report = ManifestAssetSource(MANIFEST).load()
    bundle = report.bundle
    assert bundle.metadata.name == "fixture-plugin"
    assert len(bundle.skills) == 1
    assert bundle.skills[0].name == "demo-skill"
    assert "Skill content" in bundle.skills[0].body
    assert len(bundle.agents) == 1
    assert bundle.agents[0].name == "recon"
    assert len(bundle.hook_specs) == 1
    assert bundle.hook_specs[0].event == "PreToolUse"
    assert len(bundle.commands) == 1
    assert bundle.commands[0].name == "foo"
    assert "Manifest command" in bundle.commands[0].body


def test_manifest_agent_default_tools_from_frontmatter() -> None:
    """AC-M31a-3b: empty manifest tools → YAML default_tools on agent file."""
    report = ManifestAssetSource(MANIFEST).load()
    agent = report.bundle.agents[0]
    assert agent.tools == ("read", "search")


def test_registry_bundle_commands_only() -> None:
    """AC-M31a-9: registry_bundle maps tools to commands; other kinds empty."""

    @cisterna.tool
    def alpha_tool(x: int) -> int:
        """Alpha."""
        return x

    @cisterna.tool
    def beta_tool(y: str) -> str:
        """Beta."""
        return y

    bundle = registry_bundle()
    assert [c.name for c in bundle.commands] == ["alpha_tool", "beta_tool"]
    assert bundle.agents == ()
    assert bundle.skills == ()
    assert bundle.hook_specs == ()
    assert bundle.mcp_servers == ()


def test_composite_manifest_wins_on_command_conflict(tmp_path: Path) -> None:
    """AC-M31a-2: manifest command wins; conflict recorded when bodies differ."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "commands").mkdir()
    (manifest_dir / "commands" / "foo.md").write_text("manifest body\n", encoding="utf-8")
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[plugin.export_command]
claude_code = ["commands/foo.md"]
""".strip(),
        encoding="utf-8",
    )

    @cisterna.tool
    def foo() -> None:
        """Registry foo."""

    report = CompositeAssetSource(manifest_dir / "manifest.toml").load()
    assert report.bundle.commands[0].body == "manifest body\n"
    assert any("foo" in c for c in report.conflicts)


def test_manifest_missing_file_warns_never_raises(tmp_path: Path) -> None:
    """Missing command path produces warning, not exception."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[plugin.export_command]
claude_code = ["commands/missing.md"]
""".strip(),
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert report.bundle.commands[0].name == "missing"
    assert report.bundle.commands[0].body == ""
    assert any("missing" in w for w in report.warnings)
