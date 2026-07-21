"""Tests for M3.1a AssetBundle IR extension (W1).

Covers SkillAsset, AgentAsset, HookSpecAsset, LoadReport, and sort invariants.
"""

from __future__ import annotations

import pytest

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    HookSpecAsset,
    LoadReport,
    SkillAsset,
)


def _meta() -> BundleMetadata:
    return BundleMetadata(name="test", version="1.0.0")


def test_skill_agent_hook_dataclasses_frozen() -> None:
    """M3.1a asset kinds are frozen dataclasses."""
    skill = SkillAsset(name="s1", body="# skill")
    agent = AgentAsset(name="a1", tools=("read",))
    hook = HookSpecAsset(event="PreToolUse", matcher="Bash", script="hooks/x.sh")
    with pytest.raises(AttributeError):
        skill.name = "other"  # type: ignore[misc]
    assert agent.tools == ("read",)
    assert hook.surfaces == ()


def test_commands_sorted_by_name() -> None:
    bundle = AssetBundle(
        metadata=_meta(),
        commands=(
            CommandAsset(name="zebra", description=None),
            CommandAsset(name="alpha", description=None),
        ),
    )
    assert [c.name for c in bundle.commands] == ["alpha", "zebra"]


def test_skills_sorted_by_name() -> None:
    bundle = AssetBundle(
        metadata=_meta(),
        skills=(
            SkillAsset(name="z-skill"),
            SkillAsset(name="a-skill"),
        ),
    )
    assert [s.name for s in bundle.skills] == ["a-skill", "z-skill"]


def test_agents_sorted_by_name() -> None:
    bundle = AssetBundle(
        metadata=_meta(),
        agents=(
            AgentAsset(name="z-agent"),
            AgentAsset(name="a-agent"),
        ),
    )
    assert [a.name for a in bundle.agents] == ["a-agent", "z-agent"]


def test_hook_specs_sorted_by_event_matcher_script() -> None:
    bundle = AssetBundle(
        metadata=_meta(),
        hook_specs=(
            HookSpecAsset(event="PostToolUse", matcher="*", script="b.sh"),
            HookSpecAsset(event="PreToolUse", matcher="Bash", script="a.sh"),
            HookSpecAsset(event="PreToolUse", matcher="Bash", script="z.sh"),
            HookSpecAsset(event="PreToolUse", matcher="A", script="a.sh"),
        ),
    )
    keys = [(h.event, h.matcher, h.script) for h in bundle.hook_specs]
    assert keys == sorted(keys)


def test_empty_collections_default() -> None:
    bundle = AssetBundle(metadata=_meta())
    assert bundle.commands == ()
    assert bundle.skills == ()
    assert bundle.agents == ()
    assert bundle.hook_specs == ()
    assert bundle.mcp_servers == ()


def test_load_report_holds_bundle_and_messages() -> None:
    bundle = AssetBundle(metadata=_meta())
    report = LoadReport(
        bundle=bundle,
        warnings=("missing file: x.md",),
        conflicts=("command foo: manifest vs registry",),
    )
    assert report.bundle is bundle
    assert report.warnings == ("missing file: x.md",)
    assert report.conflicts == ("command foo: manifest vs registry",)


def test_asset_bundle_hashable() -> None:
    """Frozen tuples enable hashability for golden/drift harnesses."""
    bundle = AssetBundle(
        metadata=_meta(),
        commands=(CommandAsset(name="one", description=None),),
    )
    assert hash(bundle) == hash(bundle)
