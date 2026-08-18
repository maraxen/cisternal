"""Tests for skill sibling-resource bundling (references/, scripts/, assets/).

Previously an emitter wrote only a skill's SKILL.md body and silently
dropped everything else in its directory (documented gap: myxcel's
marketplace README, "sibling-file export limitation"). SkillAsset.resources
+ ManifestAssetSource + ClaudeEmitter now carry those files through.
"""

from __future__ import annotations

from pathlib import Path

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export.claude import ClaudeEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_skill_resources" / ".praxia" / "manifest.toml"
)


def test_manifest_loader_collects_sibling_resources() -> None:
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    assert report.warnings == ()

    skill = report.bundle.skills[0]
    assert skill.name == "demo-skill"
    resource_paths = dict(skill.resources)
    assert resource_paths["references/foo.md"] == "# Foo reference\n\nReference content.\n"
    assert resource_paths["scripts/bar.py"] == 'print("bar")\n'


def test_claude_emitter_bundles_skill_resources() -> None:
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    files = ClaudeEmitter().emit(report.bundle)

    assert "skills/demo-skill/SKILL.md" in files
    assert "skills/demo-skill/references/foo.md" in files
    assert "skills/demo-skill/scripts/bar.py" in files
    assert files["skills/demo-skill/references/foo.md"] == "# Foo reference\n\nReference content.\n"


def test_manifest_minimal_fixture_has_no_resources() -> None:
    """Regression guard: a skill with no references//scripts/ dirs must not
    gain a spurious `resources` tuple, so unrelated golden digests stay put.
    """
    minimal = Path(__file__).parent / "fixtures" / "manifest_minimal" / ".praxia" / "manifest.toml"
    report = ManifestAssetSource(minimal).load()
    skill = report.bundle.skills[0]
    assert skill.resources == ()
