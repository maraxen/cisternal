"""Tests for M3.1a manifest and composite asset sources (W2)."""

from __future__ import annotations

from pathlib import Path

import cisternal
from cisternal.assets.composite import CompositeAssetSource
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.assets.source import registry_bundle

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "manifest_minimal"
MANIFEST = FIXTURE_ROOT / ".praxia" / "manifest.toml"


def test_manifest_resolves_paths_from_repo_root(tmp_path: Path) -> None:
    """Asset paths are relative to the parent of ``.praxia/`` (praxia parent-of-parent)."""
    plugin_root = tmp_path / "plugin"
    praxia = plugin_root / ".praxia"
    skill_dir = plugin_root / "skills" / "demo"
    praxia.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("root-relative skill body\n", encoding="utf-8")
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.skills]]
name = "demo"
path = "skills/demo/SKILL.md"
""".strip(),
        encoding="utf-8",
    )
    report = ManifestAssetSource(praxia / "manifest.toml").load()
    assert report.warnings == ()
    assert report.bundle.skills[0].body == "root-relative skill body\n"


def test_export_command_argv_is_not_command_files(tmp_path: Path) -> None:
    """``[plugin.export_command]`` is praxia argv; it must not become CommandAssets."""
    plugin_root = tmp_path / "plugin"
    praxia = plugin_root / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[plugin.export_command]
claude_code = ["bth", "--export"]
""".strip(),
        encoding="utf-8",
    )
    report = ManifestAssetSource(praxia / "manifest.toml").load()
    assert report.bundle.commands == ()
    assert not any("missing or unreadable" in w for w in report.warnings)


def _praxia_manifest(plugin_root: Path, contents: str) -> Path:
    praxia = plugin_root / ".praxia"
    praxia.mkdir(parents=True)
    path = praxia / "manifest.toml"
    path.write_text(contents.strip() + "\n", encoding="utf-8")
    return path


def test_manifest_loads_skills_agents_hooks() -> None:
    """AC-M31a-1: manifest loads IR kinds without raising; commands come from registry."""
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
    assert bundle.commands == ()


def test_manifest_agent_default_tools_from_frontmatter() -> None:
    """AC-M31a-3b: empty manifest tools → YAML default_tools on agent file."""
    report = ManifestAssetSource(MANIFEST).load()
    agent = report.bundle.agents[0]
    assert agent.tools == ("read", "search")


def test_registry_bundle_commands_only() -> None:
    """AC-M31a-9: registry_bundle maps tools to commands; other kinds empty."""

    @cisternal.tool
    def alpha_tool(x: int) -> int:
        """Alpha."""
        return x

    @cisternal.tool
    def beta_tool(y: str) -> str:
        """Beta."""
        return y

    bundle = registry_bundle()
    assert [c.name for c in bundle.commands] == ["alpha_tool", "beta_tool"]
    assert bundle.agents == ()
    assert bundle.skills == ()
    assert bundle.hook_specs == ()
    assert bundle.mcp_servers == ()


def test_composite_registry_commands_pass_through(tmp_path: Path) -> None:
    """Manifest has no command files; registry commands pass through with no conflict."""
    manifest = _praxia_manifest(
        tmp_path / "plugin",
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"
""",
    )

    @cisternal.tool
    def foo() -> None:
        """Registry foo."""

    report = CompositeAssetSource(manifest).load()
    by_name = {c.name: c for c in report.bundle.commands}
    assert "foo" in by_name
    assert report.conflicts == ()


def test_manifest_missing_skill_file_warns_never_raises(tmp_path: Path) -> None:
    """Missing skill path produces warning, not exception."""
    manifest = _praxia_manifest(
        tmp_path / "plugin",
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.skills]]
name = "missing"
path = "skills/missing/SKILL.md"
""",
    )
    report = ManifestAssetSource(manifest).load()
    assert report.bundle.skills[0].name == "missing"
    assert report.bundle.skills[0].body == ""
    assert any("missing" in w for w in report.warnings)


def test_manifest_hook_spec_path_loads_content(tmp_path: Path) -> None:
    """M13.2: hook_specs entry with a path key populates HookSpecAsset.content."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text(
        "#!/bin/bash\necho pre\n", encoding="utf-8"
    )
    manifest = _praxia_manifest(
        plugin_root,
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.hook_specs]]
event = "PreToolUse"
matcher = "Bash"
script = "pre.sh"
path = "hooks/pre.sh"
""",
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.script == "pre.sh"
    assert spec.content == "#!/bin/bash\necho pre\n"
    assert report.warnings == ()


def test_manifest_hook_spec_no_path_leaves_content_empty() -> None:
    """M13.2: hook_specs entries without a path key are unaffected (back-compat)."""
    report = ManifestAssetSource(MANIFEST).load()
    assert report.bundle.hook_specs[0].content == ""


def test_manifest_hook_spec_missing_path_warns_never_raises(tmp_path: Path) -> None:
    """M13.2: a path pointing at a missing file warns, doesn't raise; content stays empty."""
    manifest = _praxia_manifest(
        tmp_path / "plugin",
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.hook_specs]]
event = "PreToolUse"
matcher = "Bash"
script = "pre.sh"
path = "hooks/missing.sh"
""",
    )
    report = ManifestAssetSource(manifest).load()
    assert report.bundle.hook_specs[0].content == ""
    assert any("pre.sh" in w for w in report.warnings)


def test_manifest_loads_marketplace_table(tmp_path: Path) -> None:
    """[plugin.marketplace] loads into AssetBundle.marketplace."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"

[plugin.marketplace]
name = "demo-marketplace"

[plugin.marketplace.owner]
name = "Demo Owner"
email = "demo@example.com"
""",
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    marketplace = report.bundle.marketplace
    assert marketplace is not None
    assert marketplace.name == "demo-marketplace"
    assert marketplace.owner_name == "Demo Owner"
    assert marketplace.owner_email == "demo@example.com"
    assert marketplace.owner_url == ""


def test_manifest_marketplace_name_defaults_to_plugin_name(tmp_path: Path) -> None:
    """[plugin.marketplace] with no `name` falls back to [plugin].name."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"

[plugin.marketplace]
""",
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert report.bundle.marketplace is not None
    assert report.bundle.marketplace.name == "demo-plugin"


def test_manifest_without_marketplace_table_leaves_it_none() -> None:
    """No [plugin.marketplace] table → bundle.marketplace stays None."""
    report = ManifestAssetSource(MANIFEST).load()
    assert report.bundle.marketplace is None
