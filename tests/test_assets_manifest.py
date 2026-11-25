"""Tests for M3.1a manifest and composite asset sources (W2)."""

from __future__ import annotations

import json
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


def test_manifest_hook_spec_resources_loaded_by_basename(tmp_path: Path) -> None:
    """#6859: hook_specs resources are read and stored under their basename."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "lib").mkdir()
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (plugin_root / "lib" / "helpers.sh").write_text("helper\n", encoding="utf-8")
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
resources = ["lib/helpers.sh"]
""",
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.resources == (("helpers.sh", "helper\n"),)
    assert report.warnings == ()


def test_manifest_hook_spec_missing_resource_warns_and_loads(tmp_path: Path) -> None:
    """#6859: an unreadable resource adds a warning and is skipped; load succeeds."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
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
resources = ["lib/gone.sh"]
""",
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == "#!/bin/bash\n"
    assert spec.resources == ()
    assert any("gone.sh" in w for w in report.warnings)


def test_manifest_hook_spec_resources_without_path_warn_and_are_ignored(
    tmp_path: Path,
) -> None:
    """#6859: resources with no path key warn and are dropped."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "lib").mkdir(parents=True)
    (plugin_root / "lib" / "helpers.sh").write_text("helper\n", encoding="utf-8")
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
resources = ["lib/helpers.sh"]
""",
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == ""
    assert spec.resources == ()
    assert any("resources" in w and "path" in w for w in report.warnings)


def test_manifest_hook_spec_basename_collision_with_different_content_warns(
    tmp_path: Path,
) -> None:
    """#6859: two bundled files sharing a basename but not content warn at load."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "a").mkdir(parents=True)
    (plugin_root / "b").mkdir(parents=True)
    (plugin_root / "a" / "run.sh").write_text("#!/bin/bash\necho a\n", encoding="utf-8")
    (plugin_root / "b" / "run.sh").write_text("#!/bin/bash\necho b\n", encoding="utf-8")
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
script = "a/run.sh"
path = "a/run.sh"

[[plugin.hook_specs]]
event = "PreToolUse"
matcher = "Write"
script = "b/run.sh"
path = "b/run.sh"
""",
    )
    report = ManifestAssetSource(manifest).load()
    assert len(report.bundle.hook_specs) == 2
    assert any("run.sh" in w and "collid" in w for w in report.warnings)


def test_manifest_hook_spec_identical_basename_same_content_no_warning(
    tmp_path: Path,
) -> None:
    """#6859: the same basename with identical content is not a collision."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "a").mkdir(parents=True)
    (plugin_root / "b").mkdir(parents=True)
    (plugin_root / "a" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (plugin_root / "b" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
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
script = "a/run.sh"
path = "a/run.sh"

[[plugin.hook_specs]]
event = "PreToolUse"
matcher = "Write"
script = "b/run.sh"
path = "b/run.sh"
""",
    )
    report = ManifestAssetSource(manifest).load()
    assert report.warnings == ()


def test_snapshot_round_trip_keeps_hook_resources() -> None:
    """#6859: resources survive dumps/loads; empty resources keep old snapshot bytes."""
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, HookSpecAsset
    from cisternal.assets.snapshot import dumps_snapshot, loads_snapshot

    spec = HookSpecAsset(
        event="PreToolUse",
        matcher="Bash",
        script="guard.sh",
        content="#!/bin/bash\n",
        resources=(("lib.sh", "helper\n"),),
    )
    bundle = AssetBundle(metadata=BundleMetadata(name="p", version="1.0.0"), hook_specs=(spec,))
    text = dumps_snapshot(bundle)
    (back,) = loads_snapshot(text).hook_specs
    assert back.resources == (("lib.sh", "helper\n"),)
    assert back == spec

    plain = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        hook_specs=(HookSpecAsset(event="PreToolUse", matcher="Bash", script="x.sh"),),
    )
    assert '"resources"' not in dumps_snapshot(plain)


def _hook_manifest_text(*entries: str) -> str:
    header = """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"
"""
    return header + "".join(entries)


def _hook_entry(script: str, path: str = "", extra: str = "") -> str:
    lines = [
        "",
        "[[plugin.hook_specs]]",
        'event = "PreToolUse"',
        'matcher = "Bash"',
        f'script = "{script}"',
    ]
    if path:
        lines.append(f'path = "{path}"')
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def test_manifest_script_with_args_and_path_is_not_bundled(tmp_path: Path) -> None:
    """#6859 review: a script with whitespace cannot name a bundled file; warn, do not bundle."""
    from cisternal.export.claude import ClaudeEmitter

    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("guard.sh --strict", path="hooks/pre.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == ""
    assert any("guard.sh --strict" in w for w in report.warnings)

    files = ClaudeEmitter().emit(report.bundle)
    hooks = json.loads(files["hooks/hooks.json"])["hooks"]
    assert hooks["PreToolUse"][0]["hooks"][0]["command"] == "guard.sh --strict"
    assert not any(path.startswith("hooks/scripts/") for path in files)


def test_manifest_unsafe_resource_name_is_skipped(tmp_path: Path) -> None:
    """#6859 review: a resource whose basename has a space is skipped with a warning."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (plugin_root / "lib").mkdir()
    (plugin_root / "lib" / "my helper.sh").write_text("helper\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["lib/my helper.sh"]')
        ),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == "#!/bin/bash\n"
    assert spec.resources == ()
    assert any("my helper.sh" in w for w in report.warnings)


def test_manifest_script_with_parent_segment_is_not_bundled(tmp_path: Path) -> None:
    """#6859 review: a script with a '..' segment is refused even though its file name is safe."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("../../x.sh", path="hooks/pre.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == ""
    assert any("../../x.sh" in w and ".." in w for w in report.warnings)


def test_manifest_nul_in_hook_path_warns_and_does_not_raise(tmp_path: Path) -> None:
    """#6859 review: a NUL byte in a hook path raises ValueError inside resolve(); load must not raise."""
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("x.sh", path="a\\u0000b.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == ""
    assert any("x.sh" in w for w in report.warnings)


def test_manifest_nul_in_resource_dir_warns_and_does_not_raise(tmp_path: Path) -> None:
    """#6859 review: a NUL in a resource's directory part must not raise out of load()."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["li\\u0000b/x.sh"]'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == "#!/bin/bash\n"
    assert spec.resources == ()
    assert any("x.sh" in w for w in report.warnings)


def test_manifest_nul_in_resource_name_warns_and_does_not_raise(tmp_path: Path) -> None:
    """Guard: a NUL in a resource's file name is refused by the name rule without raising."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["a\\u0000b.sh"]'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.resources == ()
    assert any("a\x00b.sh" in w or "characters outside" in w for w in report.warnings)


def test_manifest_empty_resource_warns_and_is_not_claimed(tmp_path: Path) -> None:
    """#6859 review: an empty resource file warns and is skipped, so it never claims its name."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (plugin_root / "lib").mkdir()
    (plugin_root / "lib" / "util.sh").write_text("", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["lib/util.sh"]'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == "#!/bin/bash\n"
    assert spec.resources == ()
    assert any("util.sh" in w and "empty" in w for w in report.warnings)


def test_manifest_unsafe_script_basename_without_whitespace_is_not_bundled(
    tmp_path: Path,
) -> None:
    """#6859 review (guard): a '$' in the script's file name is refused by the name rule."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("agent_assets/a$b.sh", path="hooks/pre.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    assert report.bundle.hook_specs[0].content == ""
    assert any("a$b.sh" in w for w in report.warnings)


def test_manifest_symlink_inside_root_pointing_outside_is_not_bundled(tmp_path: Path) -> None:
    """#6859 review (guard): a symlink under the root whose target is outside is refused."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    outside = tmp_path / "outside_target.sh"
    outside.write_text("#!/bin/bash\necho leak\n", encoding="utf-8")
    (plugin_root / "hooks" / "link.sh").symlink_to(outside)
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("link.sh", path="hooks/link.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    assert report.bundle.hook_specs[0].content == ""
    assert any("outside the manifest root" in w for w in report.warnings)


def test_manifest_script_with_space_in_directory_refused_by_whitespace_rule(
    tmp_path: Path,
) -> None:
    """#6859 review: only the whitespace rule catches a space in a directory part (file name is clean)."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("dir with space/x.sh", path="hooks/pre.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    assert report.bundle.hook_specs[0].content == ""
    assert any("whitespace" in w for w in report.warnings)


def test_manifest_hook_script_collision_later_spec_not_bundled(tmp_path: Path) -> None:
    """#6859 review: a later spec whose script name clashes with different content is not bundled."""
    from cisternal.export.claude import ClaudeEmitter

    plugin_root = tmp_path / "plugin"
    (plugin_root / "a").mkdir(parents=True)
    (plugin_root / "b").mkdir(parents=True)
    (plugin_root / "a" / "run.sh").write_text("#!/bin/bash\necho a\n", encoding="utf-8")
    (plugin_root / "b" / "run.sh").write_text("#!/bin/bash\necho b\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("a/run.sh", path="a/run.sh"),
            _hook_entry("b/run.sh", path="b/run.sh").replace('"Bash"', '"Write"'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    first, second = report.bundle.hook_specs
    assert first.content == "#!/bin/bash\necho a\n"
    assert second.content == ""
    assert any("run.sh" in w and "collides" in w for w in report.warnings)

    files = ClaudeEmitter().emit(report.bundle)
    assert files["hooks/scripts/run.sh"] == "#!/bin/bash\necho a\n"
    commands = sorted(
        h["command"]
        for entry in json.loads(files["hooks/hooks.json"])["hooks"]["PreToolUse"]
        for h in entry["hooks"]
    )
    assert commands == ['"${CLAUDE_PLUGIN_ROOT}"/hooks/scripts/run.sh', "b/run.sh"]


def test_manifest_resource_collision_drops_only_the_resource(tmp_path: Path) -> None:
    """#6859 review: a later resource clashing with different content is dropped, script kept."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (plugin_root / "lib").mkdir()
    (plugin_root / "lib" / "util.sh").write_text("one\n", encoding="utf-8")
    (plugin_root / "other").mkdir()
    (plugin_root / "other" / "util.sh").write_text("two\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["lib/util.sh"]'),
            _hook_entry("pre2.sh", path="hooks/pre.sh", extra='resources = ["other/util.sh"]').replace(
                '"Bash"', '"Write"'
            ),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    first, second = report.bundle.hook_specs
    assert first.resources == (("util.sh", "one\n"),)
    assert second.content == "#!/bin/bash\n"
    assert second.resources == ()
    assert any("util.sh" in w and "collides" in w for w in report.warnings)


def test_manifest_resource_escaping_root_and_absolute_path_are_refused(
    tmp_path: Path,
) -> None:
    """#6859 review: resources and paths must resolve inside the manifest root."""
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/bash\necho outside\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("abs.sh", path=str(outside)),
            _hook_entry("esc.sh", path="../outside.sh").replace('"Bash"', '"Write"'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    absolute, escaped = report.bundle.hook_specs
    assert absolute.content == ""
    assert escaped.content == ""
    assert sum("outside" in w for w in report.warnings) >= 2
    # The resource rule is exercised by test_manifest_escaping_resource_is_skipped_with_script_kept;
    # here the script is refused first, so no resource assertion would test anything.


def test_manifest_escaping_resource_is_skipped_with_script_kept(tmp_path: Path) -> None:
    """#6859 review: an escaping resource is skipped; the in-root script still bundles."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    outside = tmp_path / "secret.sh"
    outside.write_text("leak\n", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["../secret.sh"]'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == "#!/bin/bash\n"
    assert spec.resources == ()
    assert any("secret.sh" in w for w in report.warnings)


def test_manifest_non_utf8_resource_warns_and_loads(tmp_path: Path) -> None:
    """#6859 review: a non-UTF-8 resource warns instead of raising out of load()."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "pre.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (plugin_root / "lib").mkdir()
    (plugin_root / "lib" / "blob.sh").write_bytes(b"\xff\xfe\x00bad")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(
            _hook_entry("pre.sh", path="hooks/pre.sh", extra='resources = ["lib/blob.sh"]'),
        ),
    )
    report = ManifestAssetSource(manifest).load()
    spec = report.bundle.hook_specs[0]
    assert spec.content == "#!/bin/bash\n"
    assert spec.resources == ()
    assert any("blob.sh" in w for w in report.warnings)


def test_manifest_empty_hook_script_warns_and_is_not_bundled(tmp_path: Path) -> None:
    """#6859 review: a path to an empty file warns; the spec is not bundled."""
    plugin_root = tmp_path / "plugin"
    (plugin_root / "hooks").mkdir(parents=True)
    (plugin_root / "hooks" / "empty.sh").write_text("", encoding="utf-8")
    manifest = _praxia_manifest(
        plugin_root,
        _hook_manifest_text(_hook_entry("empty.sh", path="hooks/empty.sh")),
    )
    report = ManifestAssetSource(manifest).load()
    assert report.bundle.hook_specs[0].content == ""
    assert any("empty" in w and "empty.sh" in w for w in report.warnings)
