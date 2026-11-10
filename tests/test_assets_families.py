"""Tests for Asset Schema C2 extensions: families, verbs, covers_families, distinctive_strings, and guidance lints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisternal.assets.bundle import (
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    LoadReport,
    McpAsset,
    SkillAsset,
)
from cisternal.assets.composite import merge_registry
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.assets.snapshot import dumps_snapshot, loads_snapshot
from cisternal.assets.validate import (
    build_hermetic_tool_index,
    check_dangling_tool_names,
    check_uncovered_families,
    extract_quoted_tool_candidates,
    strip_code_fences,
)
from cisternal.cli import app


def _meta(name: str = "test-pkg") -> BundleMetadata:
    return BundleMetadata(name=name, version="1.0.0")


def test_asset_bundle_hashable_with_families_and_verbs() -> None:
    """AssetBundle must remain hashable even when families and verbs dicts are present."""
    bundle = AssetBundle(
        metadata=_meta(),
        commands=(CommandAsset(name="one", description=None),),
        families={"query": ("bathos/run_sql", "bathos/find_runs")},
        verbs={"sql": {"subcommands": {"query": "bathos/run_sql"}}},
    )
    assert hash(bundle) == hash(bundle)
    assert bundle.families == {"query": ("bathos/run_sql", "bathos/find_runs")}
    assert "sql" in bundle.verbs


def test_skill_asset_covers_families_and_distinctive_strings() -> None:
    """SkillAsset carries covers_families and distinctive_strings tuples."""
    skill = SkillAsset(
        name="test-skill",
        description="A test skill",
        covers_families=("query", "audit"),
        distinctive_strings=("run_sql", "experiment_query"),
    )
    assert skill.covers_families == ("query", "audit")
    assert skill.distinctive_strings == ("run_sql", "experiment_query")


def test_load_report_advisories_channel() -> None:
    """LoadReport supports non-fatal advisories tuple."""
    bundle = AssetBundle(metadata=_meta())
    report = LoadReport(
        bundle=bundle,
        warnings=("warn1",),
        conflicts=("conf1",),
        advisories=("advisory1",),
    )
    assert report.advisories == ("advisory1",)


def test_composite_merge_families_and_verbs() -> None:
    """merge_registry merges families (unioning tool lists) and verbs."""
    manifest_bundle = AssetBundle(
        metadata=_meta(),
        families={"fam1": ("server1/toolA",), "fam2": ("server1/toolB",)},
        verbs={"v1": {"server1": "toolA"}},
    )
    manifest_report = LoadReport(
        bundle=manifest_bundle,
        advisories=("manifest advisory",),
    )
    merged_report = merge_registry(manifest_report, registry="default")
    assert "fam1" in merged_report.bundle.families
    assert merged_report.bundle.families["fam1"] == ("server1/toolA",)
    assert "v1" in merged_report.bundle.verbs
    assert merged_report.advisories == ("manifest advisory",)


def test_snapshot_late_defaults_roundtrip() -> None:
    """dumps_snapshot pops empty families/verbs/skill defaults and loads_snapshot restores them."""
    skill = SkillAsset(name="skill-1", description="desc")
    bundle = AssetBundle(
        metadata=_meta(),
        skills=(skill,),
    )
    raw_json = dumps_snapshot(bundle)
    doc = json.loads(raw_json)
    # Check that late defaults are popped to keep snapshot clean
    assert "families" not in doc["bundle"]
    assert "verbs" not in doc["bundle"]
    assert "covers_families" not in doc["bundle"]["skills"][0]
    assert "distinctive_strings" not in doc["bundle"]["skills"][0]

    # Check that restoration reconstructs default empty structures
    restored = loads_snapshot(raw_json)
    assert restored.families == {}
    assert restored.verbs == {}
    assert restored.skills[0].covers_families == ()
    assert restored.skills[0].distinctive_strings == ()


def test_snapshot_non_default_families_and_verbs() -> None:
    """Non-default families and verbs are serialized and restored."""
    skill = SkillAsset(
        name="skill-1",
        covers_families=("query",),
        distinctive_strings=("query_sql",),
    )
    bundle = AssetBundle(
        metadata=_meta(),
        skills=(skill,),
        families={"query": ("srv/tool1",)},
        verbs={"sql": {"subcommands": {"q": "srv/tool1"}}},
    )
    raw_json = dumps_snapshot(bundle)
    doc = json.loads(raw_json)
    assert doc["bundle"]["families"] == {"query": ["srv/tool1"]}
    assert "sql" in doc["bundle"]["verbs"]

    restored = loads_snapshot(raw_json)
    assert restored.families == {"query": ("srv/tool1",)}
    assert restored.skills[0].covers_families == ("query",)
    assert restored.skills[0].distinctive_strings == ("query_sql",)


def test_manifest_source_loads_families_and_verbs(tmp_path: Path) -> None:
    """ManifestAssetSource parses [families] and [verbs] from manifest TOML."""
    manifest_file = tmp_path / ".praxia" / "manifest.toml"
    manifest_file.parent.mkdir(parents=True)
    manifest_file.write_text(
        """
[plugin]
name = "myplugin"
version = "0.1.0"
description = "My test plugin"

[families]
query = ["bare_tool", "other_server/other_tool"]

[verbs]
status = { cmd = "myplugin/status" }
""",
        encoding="utf-8",
    )
    source = ManifestAssetSource(manifest_file)
    report = source.load()
    assert report.warnings == ()
    # bare_tool normalized with plugin name
    assert report.bundle.families["query"] == (
        "myplugin/bare_tool",
        "other_server/other_tool",
    )
    assert "status" in report.bundle.verbs


def test_strip_code_fences() -> None:
    """strip_code_fences removes backtick and tilde fenced code blocks."""
    md = """# Header
Here is prose with `inline_tool`.

```python
# In code fence:
`mcp__fake__tool`
```

More prose with `another_tool`.

~~~bash
`dangling/tool`
~~~
Final line.
"""
    stripped = strip_code_fences(md)
    assert "`inline_tool`" in stripped
    assert "`another_tool`" in stripped
    assert "`mcp__fake__tool`" not in stripped
    assert "`dangling/tool`" not in stripped


def test_hermetic_tool_index_and_candidate_extraction() -> None:
    """build_hermetic_tool_index collects tools and declared servers."""
    bundle = AssetBundle(
        metadata=_meta("praxia"),
        commands=(CommandAsset(name="run_cmd", description=None),),
        mcp_servers=(McpAsset(name="bathos", command=("bth",)),),
        families={"sql": ("bathos/run_sql",)},
        verbs={"query": {"subcommands": {"find": "bathos/find_runs"}}},
    )
    known, servers = build_hermetic_tool_index(bundle)
    assert "bathos/run_sql" in known
    assert "bathos/find_runs" in known
    assert "praxia/run_cmd" in known
    assert "bathos" in servers

    text = """
Call `bathos/run_sql` or `mcp__plugin_bathos_bathos__find_runs`.
Also see `references/guide.md` and `unrelated/path.py`.
"""
    candidates = extract_quoted_tool_candidates(text, declared_servers=servers)
    canonical_keys = [c[1] for c in candidates]
    assert "bathos/run_sql" in canonical_keys
    assert "bathos/find_runs" in canonical_keys
    # Non-declared server paths are ignored
    assert not any("guide" in k for k in canonical_keys)
    assert not any("path" in k for k in canonical_keys)


def test_uncovered_families_advisory() -> None:
    """Declared families with 0 covering skills generate advisories."""
    skill = SkillAsset(name="s1", covers_families=("fam_a",))
    bundle = AssetBundle(
        metadata=_meta(),
        skills=(skill,),
        families={"fam_a": ("srv/t1",), "fam_b": ("srv/t2",)},
    )
    advisories = check_uncovered_families(bundle)
    assert len(advisories) == 1
    assert "fam_b" in advisories[0]


def test_dangling_tool_names_fatal_warning() -> None:
    """Quoted tool names not present in known_tools generate fatal warnings."""
    # skill quotes bathos/nonexistent_tool
    skill = SkillAsset(
        name="s1",
        description="Quotes `bathos/nonexistent_tool` and `mcp__bathos__run_sql`",
        body="Body without dangling tool",
    )
    bundle = AssetBundle(
        metadata=_meta(),
        skills=(skill,),
        mcp_servers=(McpAsset(name="bathos", command=("bth",)),),
        families={"sql": ("bathos/run_sql",)},
    )
    warnings = check_dangling_tool_names(bundle)
    assert len(warnings) == 1
    assert "nonexistent_tool" in warnings[0]
    assert "dangling tool name" in warnings[0]


def test_cli_validate_advisory_exits_0(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """CLI validate exits 0 when only advisories (uncovered families) exist."""
    manifest_file = tmp_path / ".praxia" / "manifest.toml"
    manifest_file.parent.mkdir(parents=True)
    skill_file = tmp_path / "skills" / "my_skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        """---
name: my-skill
description: A clean skill
---
Body text
""",
        encoding="utf-8",
    )
    manifest_file.write_text(
        f"""
[plugin]
name = "cisternal"
version = "0.1.0"

[families]
uncovered_family = ["cisternal/tool_a"]

[[plugin.skills]]
name = "my-skill"
path = "{skill_file.relative_to(tmp_path)}"
""",
        encoding="utf-8",
    )
    # validate_assets with manifest
    with pytest.raises(SystemExit) as exc:
        app(["assets", "validate", "--manifest", str(manifest_file)])
    assert exc.value.code == 0
    assert any("uncovered_family" in msg for msg in caplog.messages)


def test_cli_validate_dangling_tool_exits_1(tmp_path: Path) -> None:
    """CLI validate exits 1 when a skill quotes a dangling tool."""
    manifest_file = tmp_path / ".praxia" / "manifest.toml"
    manifest_file.parent.mkdir(parents=True)
    skill_file = tmp_path / "skills" / "my_skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        """---
name: my-skill
description: Quotes dangling `myserver/missing_tool`
---
Body text
""",
        encoding="utf-8",
    )
    manifest_file.write_text(
        f"""
[plugin]
name = "myserver"
version = "0.1.0"

[plugin.mcp]
command = ["myserver"]

[families]
known_fam = ["myserver/good_tool"]

[[plugin.skills]]
name = "my-skill"
path = "{skill_file.relative_to(tmp_path)}"
""",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        app(["assets", "validate", "--manifest", str(manifest_file)])
    assert exc.value.code == 1
