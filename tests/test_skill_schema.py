"""Skill frontmatter schema: every modelled Claude Code key exports, loads and round-trips.

Context: Claude Code ignores unknown SKILL.md keys (``triggers`` among them),
so triggering phrases must ride in ``when_to_use``. See the research note
``.praxia/docs/research/261017_skill-frontmatter-schema.md``.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import yaml

from cisternal.assets.bundle import AssetBundle, BundleMetadata, SkillAsset
from cisternal.assets.manifest import ManifestAssetSource, _split_frontmatter
from cisternal.assets.skill_schema import LISTING_CAP_CHARS, check_skill
from cisternal.assets.snapshot import bundle_from_dict
from cisternal.export._markdown import format_skill_markdown

FULL = SkillAsset(
    name="demo",
    description="Does the demo thing.",
    triggers=("alpha", "beta"),
    when_to_use="Use for demos.",
    paths=("src/**/*.py", "docs/*.md"),
    argument_hint="[target]",
    arguments=("target", "mode"),
    disable_model_invocation=True,
    user_invocable=False,
    allowed_tools=("Read", "Bash(git add *)"),
    disallowed_tools=("WebFetch",),
    model="inherit",
    effort="high",
    context="fork",
    agent="Explore",
    shell="bash",
    license="MIT",
    compatibility="claude-code",
)


def _fm(skill: SkillAsset) -> dict:
    fm, _ = _split_frontmatter(format_skill_markdown(skill))
    return yaml.safe_load(fm)


def test_every_modelled_key_is_emitted_with_the_documented_spelling() -> None:
    fm = _fm(FULL)
    assert fm == {
        "name": "demo",
        "description": "Does the demo thing.",
        "when_to_use": "Use for demos. Triggers: alpha, beta.",
        "paths": ["src/**/*.py", "docs/*.md"],
        "argument-hint": "[target]",
        "arguments": ["target", "mode"],
        "disable-model-invocation": True,
        "user-invocable": False,
        "allowed-tools": ["Read", "Bash(git add *)"],
        "disallowed-tools": ["WebFetch"],
        "model": "inherit",
        "effort": "high",
        "context": "fork",
        "agent": "Explore",
        "shell": "bash",
        "license": "MIT",
        "compatibility": "claude-code",
    }


def test_absent_values_are_omitted_so_plain_skills_export_unchanged() -> None:
    md = format_skill_markdown(SkillAsset(name="s", description="d", body="b\n"))
    assert md == "---\nname: s\ndescription: d\n---\nb\n"


def test_triggers_only_fold_into_when_to_use() -> None:
    fm = _fm(SkillAsset(name="s", triggers=("x", "y")))
    assert fm == {"name": "s", "when_to_use": "Triggers: x, y."}


def test_snapshot_round_trip_keeps_every_field() -> None:
    bundle = AssetBundle(metadata=BundleMetadata(name="p", version="1"), skills=(FULL,))
    data = {
        "metadata": asdict(bundle.metadata),
        "skills": [asdict(s) for s in bundle.skills],
    }
    assert bundle_from_dict(data).skills == (FULL,)


def _write_plugin(tmp_path: Path, skill_md: str, entry_extra: str = "") -> Path:
    root = tmp_path / "plugin"
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (root / ".praxia").mkdir()
    manifest = root / ".praxia" / "manifest.toml"
    manifest.write_text(
        '[plugin]\nname = "p"\nversion = "1.0.0"\n\n'
        '[[plugin.skills]]\nname = "demo"\npath = "skills/demo/SKILL.md"\n' + entry_extra,
        encoding="utf-8",
    )
    return manifest


def _load(manifest: Path):
    report = ManifestAssetSource(manifest).load()
    return report.bundle.skills[0], report.warnings


def test_loader_reads_source_frontmatter_and_manifest_wins_on_conflict(tmp_path: Path) -> None:
    md = (
        "---\nname: demo\ndescription: from source\nwhen_to_use: source when\n"
        "allowed-tools:\n  - Read\npaths: a/*.py, b/*.py\nmodel: sonnet\n---\nBody\n"
    )
    skill, _ = _load(_write_plugin(tmp_path, md, 'model = "haiku"\ndescription = "from manifest"\n'))
    assert skill.description == "from manifest"
    assert skill.model == "haiku"
    assert skill.when_to_use == "source when"
    assert skill.allowed_tools == ("Read",)
    assert skill.paths == ("a/*.py", "b/*.py")
    assert skill.body == "Body\n"


def test_source_triggers_key_is_read_and_folded(tmp_path: Path) -> None:
    md = "---\nname: demo\ndescription: d\ntriggers:\n  - one\n  - two\n---\nB\n"
    skill, _ = _load(_write_plugin(tmp_path, md))
    assert skill.triggers == ("one", "two")
    assert skill.effective_when_to_use == "Triggers: one, two."


def test_triple_dash_inside_a_value_does_not_end_the_frontmatter() -> None:
    fm, body = _split_frontmatter("---\nname: x\ndescription: a --- b\n---\nBody --- here\n")
    assert "a --- b" in fm
    assert body == "Body --- here\n"


def test_invalid_yaml_warns_and_falls_back_to_the_manifest(tmp_path: Path) -> None:
    md = "---\nname: demo\ndescription: bad: colon: here\n---\nB\n"
    skill, warnings = _load(_write_plugin(tmp_path, md, 'description = "ok"\n'))
    assert skill.description == "ok"
    assert any("not valid YAML" in w for w in warnings)


def test_unmodelled_and_unknown_keys_are_reported_as_dropped(tmp_path: Path) -> None:
    md = "---\nname: demo\ndescription: d\nhooks: {}\nbogus: 1\n---\nB\n"
    _, warnings = _load(_write_plugin(tmp_path, md))
    assert any("'hooks' is not carried" in w for w in warnings)
    assert any("'bogus' is not carried" in w for w in warnings)


def test_listing_cap_warning_counts_description_plus_folded_triggers() -> None:
    ok = SkillAsset(name="s", description="d" * 100)
    assert check_skill(ok) == []
    over = replace(ok, description="d" * LISTING_CAP_CHARS, triggers=("t",))
    assert any("listing cap" in w for w in check_skill(over))


def test_forbidden_name_characters_warn() -> None:
    assert check_skill(SkillAsset(name="a<b", description="d"))
    assert check_skill(SkillAsset(name="a​b", description="d"))
    assert check_skill(SkillAsset(name="fine-name", description="d")) == []
