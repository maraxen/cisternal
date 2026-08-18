"""Regression test for the skill-export frontmatter/metadata bug (bugfix,
cisternal/mcp-middleware-fix, 260728).

Confirmed bug: ``_load_skills`` read an entire SKILL.md file -- including its
own ``---`` frontmatter -- into ``SkillAsset.body``. ``format_skill_markdown``
then prepended a SECOND ``---\\nname: ...\\n---`` block on export, so any skill
whose source file already had frontmatter (the normal case -- e.g. maraxiom's
skill files) got doubled, malformed frontmatter on export. Additionally,
``SkillAsset.description`` was never populated from the manifest's
``[[plugin.skills]]`` entry, and the manifest's ``triggers = [...]`` field was
silently dropped.

This test exercises the full pipeline: a manifest entry with
description/triggers, pointing at a SKILL.md that itself starts with its own
``---\\nname: ...\\n---`` frontmatter -> load via ManifestAssetSource -> render
via format_skill_markdown -> assert exactly ONE frontmatter block, with the
manifest's description/triggers present, and the SKILL.md's own body content
(everything after ITS original frontmatter) preserved unchanged below the new
frontmatter block.
"""

from __future__ import annotations

from pathlib import Path

from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export._markdown import format_skill_markdown

SOURCE_BODY = "# Demo Skill\n\nThis is the skill body content.\n"
SOURCE_SKILL_MD = (
    "---\n"
    "name: demo-skill\n"
    "description: source-file-own-description\n"
    "---\n"
    f"{SOURCE_BODY}"
)


def _write_manifest(tmp_path: Path, *, description: str, triggers: list[str]) -> Path:
    manifest_dir = tmp_path / "plugin"
    (manifest_dir / "skills" / "demo-skill").mkdir(parents=True)
    (manifest_dir / "skills" / "demo-skill" / "SKILL.md").write_text(
        SOURCE_SKILL_MD, encoding="utf-8"
    )

    triggers_toml = ", ".join(f'"{t}"' for t in triggers)
    praxia = manifest_dir / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        f"""
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.skills]]
name = "demo-skill"
path = "skills/demo-skill/SKILL.md"
description = "{description}"
triggers = [{triggers_toml}]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return praxia / "manifest.toml"


def test_manifest_description_and_triggers_plumbed_through(tmp_path: Path) -> None:
    """SkillAsset.description comes from the manifest entry; triggers carried too."""
    manifest_path = _write_manifest(
        tmp_path,
        description="manifest-provided description",
        triggers=["do the thing", "trigger phrase"],
    )
    report = ManifestAssetSource(manifest_path).load()
    skill = report.bundle.skills[0]

    assert skill.name == "demo-skill"
    assert skill.description == "manifest-provided description"
    assert skill.triggers == ("do the thing", "trigger phrase")


def test_manifest_missing_description_falls_back_to_frontmatter(
    tmp_path: Path,
) -> None:
    """No manifest description -> falls back to the SKILL.md's own frontmatter
    description field."""
    manifest_dir = tmp_path / "plugin"
    (manifest_dir / "skills" / "demo-skill").mkdir(parents=True)
    (manifest_dir / "skills" / "demo-skill" / "SKILL.md").write_text(
        SOURCE_SKILL_MD, encoding="utf-8"
    )
    praxia = manifest_dir / ".praxia"
    praxia.mkdir(parents=True)
    (praxia / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.skills]]
name = "demo-skill"
path = "skills/demo-skill/SKILL.md"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    report = ManifestAssetSource(praxia / "manifest.toml").load()
    skill = report.bundle.skills[0]

    assert skill.description == "source-file-own-description"
    assert skill.triggers == ()


def test_loaded_body_excludes_source_frontmatter(tmp_path: Path) -> None:
    """The SKILL.md's own frontmatter is stripped before it reaches SkillAsset.body
    (mirrors _load_agents/_parse_agent_markdown) -- this is what prevents the
    doubled-frontmatter bug on export."""
    manifest_path = _write_manifest(
        tmp_path, description="d", triggers=[]
    )
    report = ManifestAssetSource(manifest_path).load()
    skill = report.bundle.skills[0]

    assert skill.body == SOURCE_BODY
    assert "name: demo-skill" not in skill.body
    assert "source-file-own-description" not in skill.body


def test_export_produces_exactly_one_frontmatter_block(tmp_path: Path) -> None:
    """End-to-end: export renders exactly ONE frontmatter block (not doubled),
    with manifest description/triggers, and the original body preserved
    unchanged below it."""
    manifest_path = _write_manifest(
        tmp_path,
        description="manifest-provided description",
        triggers=["do the thing", "trigger phrase"],
    )
    report = ManifestAssetSource(manifest_path).load()
    skill = report.bundle.skills[0]

    rendered = format_skill_markdown(skill)

    # Exactly one frontmatter block: the string "---" appears exactly twice
    # (open + close), never a third/fourth time from a doubled block.
    assert rendered.count("---") == 2, (
        f"Expected exactly one frontmatter block (2 '---' delimiters), "
        f"got {rendered.count('---')} in:\n{rendered}"
    )

    frontmatter, _, body = rendered.partition("---\n")[2].partition("\n---")
    # (the SKILL.md's own "name:"/"description:" frontmatter must not reappear
    # as a second block further down)
    assert rendered.strip().startswith("---")
    lines = rendered.splitlines()
    assert lines[0] == "---"
    close_idx = lines[1:].index("---") + 1
    header = lines[:close_idx]

    assert "name: demo-skill" in header
    assert "description: manifest-provided description" in header
    assert "triggers:" in header
    assert "  - do the thing" in header
    assert "  - trigger phrase" in header

    # The body below the (single) frontmatter block is the SKILL.md's own
    # body, unchanged, with no leaked frontmatter fields anywhere in it.
    rest = "\n".join(lines[close_idx + 1 :])
    assert SOURCE_BODY.strip() in rest
    assert "source-file-own-description" not in rest
    assert rest.count("---") == 0
