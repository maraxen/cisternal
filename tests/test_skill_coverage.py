"""Tests for C3 Skill Coverage Engine (Spec §C3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisternal.assets.bundle import SkillAsset
from cisternal.usage.coverage import (
    evaluate_situation_set,
    load_monitored_skills,
    match_distinctive_strings,
    mine_skill_opportunities,
)


def test_load_monitored_skills_workspace() -> None:
    """load_monitored_skills discovers all 6 monitored skills in .praxia/manifest.toml."""
    manifest_path = Path(".praxia/manifest.toml")
    monitored, unmonitored = load_monitored_skills(manifest_paths=[manifest_path])
    assert len(monitored) == 6
    for expected in (
        "export-trust",
        "run-cisternal",
        "customizing-tools",
        "writing-skill-triggers",
        "triage-tool",
        "developing-in-shadow",
    ):
        assert expected in monitored
        skill = monitored[expected]
        assert len(skill.distinctive_strings) >= 1
    assert unmonitored == []


def test_load_monitored_skills_unconfigured_marketplace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_monitored_skills with nonexistent marketplace directory skips cleanly."""
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_dir))
    nonexistent = tmp_path / "nonexistent_marketplace"
    monitored, unmonitored = load_monitored_skills(marketplace_dir=nonexistent)
    assert len(monitored) >= 1  # loads default manifest
    assert not (cfg_dir / "cisternal" / "config.toml").is_file()


def test_load_monitored_skills_marketplace_plugins(tmp_path: Path) -> None:
    """load_monitored_skills discovers plugins in <marketplace>/plugins/<name>/ via sidecar and SKILL.md."""
    m_root = tmp_path / "marketplace"
    plugins_dir = m_root / "plugins"

    # Plugin 1: .claude-plugin/cisternal-source.json with skills_meta
    p1_dir = plugins_dir / "plugin_sidecar"
    p1_sidecar_dir = p1_dir / ".claude-plugin"
    p1_sidecar_dir.mkdir(parents=True)
    p1_sidecar = {
        "skills_meta": {
            "sidecar-monitored": {
                "covers_families": ["testing"],
                "distinctive_strings": ["sidecar-trigger", "run-sidecar"],
            },
            "sidecar-unmonitored": {
                "covers_families": [],
                "distinctive_strings": [],
            },
        }
    }
    (p1_sidecar_dir / "cisternal-source.json").write_text(
        json.dumps(p1_sidecar), encoding="utf-8"
    )

    # Plugin 2: skills/<skill>/SKILL.md direct frontmatter parsing
    p2_dir = plugins_dir / "plugin_markdown"
    p2_monitored_skill = p2_dir / "skills" / "markdown-monitored"
    p2_monitored_skill.mkdir(parents=True)
    (p2_monitored_skill / "SKILL.md").write_text(
        """---
name: markdown-monitored
description: Markdown skill with distinctive strings
covers_families:
  - docs
distinctive_strings:
  - markdown-trigger
  - run-markdown
---
# Markdown Monitored
When to use this skill.
""",
        encoding="utf-8",
    )

    p2_unmonitored_skill = p2_dir / "skills" / "markdown-unmonitored"
    p2_unmonitored_skill.mkdir(parents=True)
    (p2_unmonitored_skill / "SKILL.md").write_text(
        """---
name: markdown-unmonitored
description: Markdown skill lacking distinctive strings
---
# Markdown Unmonitored
When to use this skill.
""",
        encoding="utf-8",
    )

    monitored, unmonitored = load_monitored_skills(marketplace_dir=m_root)

    # Verify monitored skills discovered from both plugins
    assert "sidecar-monitored" in monitored
    assert monitored["sidecar-monitored"].distinctive_strings == (
        "sidecar-trigger",
        "run-sidecar",
    )
    assert monitored["sidecar-monitored"].covers_families == ("testing",)

    assert "markdown-monitored" in monitored
    assert monitored["markdown-monitored"].distinctive_strings == (
        "markdown-trigger",
        "run-markdown",
    )
    assert monitored["markdown-monitored"].covers_families == ("docs",)

    # Verify unmonitored skills recorded from both plugins
    unmonitored_names = {u.name: u for u in unmonitored}
    assert "sidecar-unmonitored" in unmonitored_names
    assert (
        unmonitored_names["sidecar-unmonitored"].reason == "missing distinctive_strings"
    )
    assert "markdown-unmonitored" in unmonitored_names
    assert (
        unmonitored_names["markdown-unmonitored"].reason
        == "missing distinctive_strings"
    )


def test_load_monitored_skills_marketplace_fallback(tmp_path: Path) -> None:
    """load_monitored_skills falls back to direct child dirs if plugins/ subdir does not exist."""
    m_root = tmp_path / "flat_marketplace"
    p_dir = m_root / "flat_plugin"
    skill_dir = p_dir / "skills" / "flat-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: flat-skill
description: Flat layout skill
distinctive_strings:
  - flat-trigger
---
# Flat Skill
""",
        encoding="utf-8",
    )

    monitored, _ = load_monitored_skills(marketplace_dir=m_root)
    assert "flat-skill" in monitored
    assert monitored["flat-skill"].distinctive_strings == ("flat-trigger",)


def test_match_distinctive_strings() -> None:
    """match_distinctive_strings performs whole-token, case-insensitive boundary matching."""
    distinctive = ["prune-list", "cisternal usage", "pyo3"]

    # Positive matches
    assert match_distinctive_strings("Please run prune-list now", distinctive) == [
        "prune-list"
    ]
    assert match_distinctive_strings(
        "Inspect Cisternal Usage reports", distinctive
    ) == ["cisternal usage"]
    assert match_distinctive_strings("Compile the pyo3 extension", distinctive) == [
        "pyo3"
    ]

    # Negative matches (non-boundary or distractor)
    assert match_distinctive_strings("prune-listing is different", distinctive) == []
    assert match_distinctive_strings("pyo3_binding with underscore", distinctive) == []
    assert match_distinctive_strings("unrelated command line", distinctive) == []


def test_evaluate_synthetic_situation_fixture_certified_gate() -> None:
    """evaluate_situation_set on synthetic_situations.jsonl certifies p_hat >= 0.80 over n >= 50."""
    manifest_path = Path(".praxia/manifest.toml")
    situations_path = Path("tests/fixtures/situations/synthetic_situations.jsonl")
    assert situations_path.is_file()

    monitored, _ = load_monitored_skills(manifest_paths=[manifest_path])
    report, records = evaluate_situation_set(
        situations_path=situations_path,
        skills=monitored,
        threshold=0.80,
    )

    assert report.total_situations == 80
    assert report.matched_turns == 60
    assert report.matched_turns >= 50  # satisfies sample size ceiling
    assert report.true_positives == 60
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.precision == 1.00
    assert report.precision >= 0.80
    assert report.status == "PASS"

    # Verify Wilson intervals are calculated and bounded
    assert 0.90 <= report.precision_ci.lower <= 1.0
    assert 0.99 <= report.precision_ci.upper <= 1.0
    assert len(records) == 80


def test_evaluate_situation_inconclusive_gate(tmp_path: Path) -> None:
    """evaluate_situation_set returns INCONCLUSIVE when matched turns n < 50."""
    # Create small fixture with only 10 turns
    small_file = tmp_path / "small_situations.jsonl"
    with open(small_file, "w", encoding="utf-8") as f:
        for i in range(10):
            record = {
                "id": f"sit_{i}",
                "prompt": "Run prune-list to check servers",
                "expected_skills": ["triage-tool"],
            }
            f.write(json.dumps(record) + "\n")

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool",
            distinctive_strings=("prune-list",),
        )
    }

    report, records = evaluate_situation_set(small_file, skills=skills, threshold=0.80)
    assert report.matched_turns == 10
    assert report.precision == 1.0
    assert report.status == "INCONCLUSIVE"


def test_evaluate_situation_failed_gate(tmp_path: Path) -> None:
    """evaluate_situation_set returns FAIL when precision < threshold over n >= 50 turns."""
    fail_file = tmp_path / "fail_situations.jsonl"
    with open(fail_file, "w", encoding="utf-8") as f:
        # 30 TP, 30 FP -> precision 30/60 = 0.50 < 0.80 over n=60
        for i in range(30):
            # TP
            f.write(
                json.dumps(
                    {
                        "id": f"sit_tp_{i}",
                        "prompt": "Run prune-list now",
                        "expected_skills": ["triage-tool"],
                    }
                )
                + "\n"
            )
            # FP (triage-tool detected but not expected)
            f.write(
                json.dumps(
                    {
                        "id": f"sit_fp_{i}",
                        "prompt": "Run prune-list now",
                        "expected_skills": ["other-skill"],
                    }
                )
                + "\n"
            )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool",
            distinctive_strings=("prune-list",),
        )
    }

    report, records = evaluate_situation_set(fail_file, skills=skills, threshold=0.80)
    assert report.matched_turns == 60
    assert report.true_positives == 30
    assert report.false_positives == 30
    assert report.precision == 0.50
    assert report.status == "FAIL"


def test_mine_skill_opportunities_empty_dir(tmp_path: Path) -> None:
    """mine_skill_opportunities runs safely on empty or nonexistent directory."""
    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool",
            distinctive_strings=("prune-list",),
        )
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)
    assert "triage-tool" in report.skills
    assert report.skills["triage-tool"].opportunities == 0


def test_mine_skill_opportunities_positive_invoked(tmp_path: Path) -> None:
    """Test planted opportunity detected and loaded before action."""
    proj = tmp_path / "project_alpha"
    proj.mkdir()
    sess = proj / "sess1.jsonl"
    sess.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"content": "Please run prune-list to inspect servers."},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "input": {"skill": "triage-tool"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "cisternal prune-list"},
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)
    assert "triage-tool" in report.skills
    stat = report.skills["triage-tool"]
    assert stat.opportunities == 1
    assert stat.invoked == 1
    assert stat.loaded_before_action == 1
    assert stat.missed_opportunities == 0
    assert stat.post_load_tool_calls == 1
    assert len(report.mined_situations) == 1
    assert report.mined_situations[0]["expected_skills"] == ["triage-tool"]


def test_mine_skill_opportunities_missed(tmp_path: Path) -> None:
    """Test planted opportunity detected and NOT invoked (missed opportunity)."""
    proj = tmp_path / "project_beta"
    proj.mkdir()
    sess = proj / "sess2.jsonl"
    sess.write_text(
        json.dumps({"type": "user", "message": {"content": "Run prune-list now."}})
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {"type": "assistant", "message": {"content": "I did not load any skill."}}
        )
        + "\n",
        encoding="utf-8",
    )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)
    stat = report.skills["triage-tool"]
    assert stat.opportunities == 1
    assert stat.invoked == 0
    assert stat.loaded_before_action == 0
    assert stat.missed_opportunities == 1
    assert stat.post_load_tool_calls == 0


def test_mine_skill_opportunities_invoked_late(tmp_path: Path) -> None:
    """Test planted opportunity invoked late (action executed before skill load)."""
    proj = tmp_path / "project_gamma"
    proj.mkdir()
    sess = proj / "sess3.jsonl"
    sess.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"content": "Please prune-list the registrations."},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "git status"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "input": {"skill": "triage-tool"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "cisternal prune-list"},
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)
    stat = report.skills["triage-tool"]
    assert stat.opportunities == 1
    assert stat.invoked == 1
    assert stat.loaded_before_action == 0  # not loaded before action!
    assert stat.missed_opportunities == 0
    assert stat.post_load_tool_calls == 1


def test_mine_skill_opportunities_multiturn_no_leakage(tmp_path: Path) -> None:
    """Test multi-turn session: turn 1 matches Skill A, turn 2 matches Skill B without leakage."""
    proj = tmp_path / "project_delta"
    proj.mkdir()
    sess = proj / "sess4.jsonl"
    sess.write_text(
        # Turn 1: Skill A (triage-tool)
        json.dumps({"type": "user", "message": {"content": "Check prune-list servers"}})
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "input": {"skill": "triage-tool"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "bth sql"},
                        }
                    ]
                },
            }
        )
        + "\n"
        # Turn 2: Skill B (customizing-tools)
        + json.dumps(
            {
                "type": "user",
                "message": {"content": "Now help me re-implement using pyo3"},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "git status"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "input": {"skill": "customizing-tools"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "cargo build"},
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
        "customizing-tools": SkillAsset(
            name="customizing-tools", distinctive_strings=("pyo3", "re-implement")
        ),
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)

    # Skill A assertions (Turn 1 only)
    stat_a = report.skills["triage-tool"]
    assert stat_a.opportunities == 1
    assert stat_a.invoked == 1
    assert stat_a.loaded_before_action == 1
    assert stat_a.missed_opportunities == 0
    assert stat_a.post_load_tool_calls == 1  # Only the 1 tool call in Turn 1!

    # Skill B assertions (Turn 2 only)
    stat_b = report.skills["customizing-tools"]
    assert stat_b.opportunities == 1
    assert stat_b.invoked == 1
    assert stat_b.loaded_before_action == 0  # Invoked late in Turn 2
    assert stat_b.missed_opportunities == 0
    assert (
        stat_b.post_load_tool_calls == 1
    )  # Only the 1 tool call after load in Turn 2!


def test_mine_skill_opportunities_golden_redacted_fixture() -> None:
    """Test mine_skill_opportunities runs safely over golden_redacted.jsonl fixture without crash."""
    fixture_path = Path("tests/fixtures/transcripts/golden_redacted.jsonl")
    assert fixture_path.is_file()

    skills = {
        "run-cisternal": SkillAsset(
            name="run-cisternal",
            distinctive_strings=("telemetry doctor", "run-cisternal"),
        ),
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
    }
    report = mine_skill_opportunities(
        projects_dir=fixture_path.parent.parent, skills=skills
    )
    assert "run-cisternal" in report.skills
    # run-cisternal is invoked in golden_redacted without opportunity prompt
    assert report.skills["run-cisternal"].invoked == 1
    assert report.skills["run-cisternal"].opportunities == 0
    assert report.skills["run-cisternal"].missed_opportunities == 0


def test_mine_skill_opportunities_synthetic_flat_records(tmp_path: Path) -> None:
    """Test backward compatibility with synthetic flat user_turn and tool_use records."""
    proj = tmp_path / "project_flat"
    proj.mkdir()
    sess = proj / "flat.jsonl"
    sess.write_text(
        json.dumps({"type": "user_turn", "text": "Execute prune-list"})
        + "\n"
        + json.dumps(
            {"type": "tool_use", "name": "Skill", "input": {"skill": "triage-tool"}}
        )
        + "\n"
        + json.dumps({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}})
        + "\n",
        encoding="utf-8",
    )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)
    stat = report.skills["triage-tool"]
    assert stat.opportunities == 1
    assert stat.invoked == 1
    assert stat.loaded_before_action == 1
    assert stat.post_load_tool_calls == 1


def test_mine_skill_opportunities_multi_session_accumulation(tmp_path: Path) -> None:
    """Verify post_load_tool_calls accumulates across multiple sessions without clobbering."""
    proj = tmp_path / "project_multi"
    proj.mkdir()
    s1 = proj / "s1.jsonl"
    s1.write_text(
        json.dumps({"type": "user", "message": {"content": "Run prune-list now"}})
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "input": {"skill": "triage-tool"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "ls -la"},
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "cat info.txt"},
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    s2 = proj / "s2.jsonl"
    s2.write_text(
        json.dumps({"type": "user", "message": {"content": "Please prune-list again"}})
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Skill",
                            "input": {"skill": "triage-tool"},
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    skills = {
        "triage-tool": SkillAsset(
            name="triage-tool", distinctive_strings=("prune-list",)
        ),
    }
    report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)
    stat = report.skills["triage-tool"]
    assert stat.opportunities == 2
    assert stat.invoked == 2
    assert stat.loaded_before_action == 2
    assert stat.missed_opportunities == 0
    assert stat.post_load_tool_calls == 2
