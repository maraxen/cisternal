"""skillmod: fold legacy ``triggers`` into ``when_to_use``, verified, textual edits."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

from cisternal.assets.manifest import ManifestAssetSource, _split_frontmatter
from cisternal.assets.skillmod import migrate_manifest

SKILL_MD = """---
name: demo
description: >-
  Folded description
  across two lines.
triggers:
  - mrx demo
  - "fix: bug"
license: MIT
---
# Body

Text with --- inside.
"""

MANIFEST = """# keep this comment
[plugin]
name = "p"
version = "1.0.0"

[[plugin.skills]]
name = "other"
path = "skills/other/SKILL.md"
triggers = ["not-mine"]

[[plugin.skills]]
name = "demo"
path = "skills/demo/SKILL.md"
description = "Demo skill"
triggers = [
  "mrx demo",   # trailing comment
  "fix: bug",
]
# tail comment
"""


def _plugin(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    for name, text in (("demo", SKILL_MD), ("other", "---\nname: other\ndescription: o\n---\nB\n")):
        (root / "skills" / name).mkdir(parents=True)
        (root / "skills" / name / "SKILL.md").write_text(text, encoding="utf-8")
    (root / ".praxia").mkdir()
    manifest = root / ".praxia" / "manifest.toml"
    manifest.write_text(MANIFEST, encoding="utf-8")
    return manifest


def test_dry_run_plans_but_writes_nothing(tmp_path: Path) -> None:
    manifest = _plugin(tmp_path)
    changes = {c.skill: c for c in migrate_manifest(manifest)}
    assert changes["demo"].status == "migrate"
    assert changes["demo"].triggers == ("mrx demo", "fix: bug")
    assert manifest.read_text(encoding="utf-8") == MANIFEST
    assert (manifest.parent.parent / "skills/demo/SKILL.md").read_text(encoding="utf-8") == SKILL_MD


def test_apply_folds_triggers_and_keeps_everything_else(tmp_path: Path) -> None:
    manifest = _plugin(tmp_path)
    changes = {c.skill: c for c in migrate_manifest(manifest, apply=True)}
    assert changes["demo"].status == "migrate"

    skill_md = (manifest.parent.parent / "skills/demo/SKILL.md").read_text(encoding="utf-8")
    fm, body = _split_frontmatter(skill_md)
    doc = yaml.safe_load(fm)
    assert doc == {
        "name": "demo",
        "description": "Folded description across two lines.",
        "when_to_use": "Triggers: mrx demo, fix: bug.",
        "license": "MIT",
    }
    assert body == "# Body\n\nText with --- inside.\n"

    text = manifest.read_text(encoding="utf-8")
    assert "# keep this comment" in text and "# tail comment" in text
    parsed = tomllib.loads(text)
    skills = {s["name"]: s for s in parsed["plugin"]["skills"]}
    assert "triggers" not in skills["demo"]
    assert "triggers" not in skills["other"]
    other_md = (manifest.parent.parent / "skills/other/SKILL.md").read_text(encoding="utf-8")
    assert yaml.safe_load(_split_frontmatter(other_md)[0])["when_to_use"] == "Triggers: not-mine."


def test_exported_listing_text_is_unchanged_by_the_migration(tmp_path: Path) -> None:
    manifest = _plugin(tmp_path)
    old = {s.name: s for s in ManifestAssetSource(manifest).load().bundle.skills}["demo"]
    migrate_manifest(manifest, apply=True)
    new = {s.name: s for s in ManifestAssetSource(manifest).load().bundle.skills}["demo"]
    assert new.triggers == ()
    assert (new.description, new.effective_when_to_use) == (
        old.description,
        old.effective_when_to_use,
    )


def test_apply_is_idempotent(tmp_path: Path) -> None:
    manifest = _plugin(tmp_path)
    migrate_manifest(manifest, apply=True)
    snapshot = manifest.read_text(encoding="utf-8")
    again = {c.skill: c for c in migrate_manifest(manifest, apply=True)}
    assert again["demo"].status == "unchanged"
    assert manifest.read_text(encoding="utf-8") == snapshot


def test_existing_when_to_use_in_the_skill_is_kept_first(tmp_path: Path) -> None:
    manifest = _plugin(tmp_path)
    skill = manifest.parent.parent / "skills/demo/SKILL.md"
    skill.write_text(
        "---\nname: demo\ndescription: d\nwhen_to_use: Use it.\ntriggers: [a, b]\n---\nB\n",
        encoding="utf-8",
    )
    migrate_manifest(manifest, apply=True)
    doc = yaml.safe_load(_split_frontmatter(skill.read_text(encoding="utf-8"))[0])
    assert doc["when_to_use"] == "Use it. Triggers: mrx demo, fix: bug, a, b."
