"""Adversarial challenge test suite for Milestone M4 (Track C Part 2: C4a & C6).

Stress-tests:
1. Check (a) containment & baseline ref capability erosion detection, invalid ref handling.
2. Check (b) no overclaim & token extraction: nested code fences, Pascal/camelCase boundaries,
   backticked function literals with trailing (), case-insensitive stopwords, distinctive strings shielding.
3. Check (c) scope header boundaries: line 50 vs 51, character offsets, case-insensitivity, heading levels.
4. C6 triage-tool listing character count cap (<= 150) and security audit.
5. Golden digest integrity under snapshot check and surface digests.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

import pytest

from cisternal.assets.bundle import AssetBundle, BundleMetadata, SkillAsset
from cisternal.assets.load import load_asset_report
from cisternal.assets.validate import (
    C4A_STOPWORDS,
    check_baseline_capability_erosion,
    check_distinctive_strings_containment,
    check_listing_no_overclaim,
    check_scope_header,
    strip_code_fences,
)


class TestCheckABaselineContainment:
    """Stress tests for Check (a) distinctive strings containment and baseline erosion."""

    def test_baseline_erosion_detected_on_removed_distinctive_string(
        self, tmp_path: Path
    ) -> None:
        """Removing a distinctive string present in baseline commit triggers CAPABILITY_EROSION_DETECTED."""
        repo_dir = tmp_path / "test_repo"
        repo_dir.mkdir()
        skill_dir = repo_dir / ".praxia" / "skills" / "sample-skill"
        skill_dir.mkdir(parents=True)
        manifest_file = repo_dir / ".praxia" / "manifest.toml"
        skill_file = skill_dir / "SKILL.md"

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "challenger@example.com"],
            cwd=repo_dir,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Challenger"], cwd=repo_dir, check=True
        )

        manifest_file.write_text(
            """
[plugin]
name = "test-plugin"
version = "0.1.0"
skills = [
    { name = "sample-skill", path = "skills/sample-skill/SKILL.md" }
]
""",
            encoding="utf-8",
        )

        # Baseline skill has two distinctive strings
        skill_file.write_text(
            """---
name: sample-skill
description: "Sample tool."
distinctive_strings:
  - "legacy-capability"
  - "retained-capability"
---

# Sample Skill
## Scope
Legacy and retained capabilities.
""",
            encoding="utf-8",
        )

        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "--no-verify", "-m", "Baseline commit"],
            cwd=repo_dir,
            check=True,
        )

        # Current bundle: removed 'legacy-capability' completely from listing and body
        eroded_skill = SkillAsset(
            name="sample-skill",
            description="Sample tool without old features.",
            body="## Scope\n\nOnly retained-capability is described here.",
            distinctive_strings=("retained-capability",),
        )
        bundle = AssetBundle(
            metadata=BundleMetadata(name="test-plugin", version="0.1.0"),
            skills=(eroded_skill,),
        )

        warnings = check_baseline_capability_erosion(
            bundle,
            baseline_ref="HEAD",
            manifest_path=manifest_file,
            cwd=repo_dir,
        )

        assert len(warnings) == 1
        assert "CAPABILITY_EROSION_DETECTED" in warnings[0]
        assert "legacy-capability" in warnings[0]

    def test_baseline_erosion_not_emitted_if_retained_in_body_or_refs(
        self, tmp_path: Path
    ) -> None:
        """If a baseline distinctive string is kept in body/references, no erosion warning is emitted."""
        repo_dir = tmp_path / "test_repo_retain"
        repo_dir.mkdir()
        skill_dir = repo_dir / ".praxia" / "skills" / "sample-skill"
        skill_dir.mkdir(parents=True)
        manifest_file = repo_dir / ".praxia" / "manifest.toml"
        skill_file = skill_dir / "SKILL.md"

        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "challenger@example.com"],
            cwd=repo_dir,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Challenger"], cwd=repo_dir, check=True
        )

        manifest_file.write_text(
            """
[plugin]
name = "test-plugin"
version = "0.1.0"
skills = [
    { name = "sample-skill", path = "skills/sample-skill/SKILL.md" }
]
""",
            encoding="utf-8",
        )
        skill_file.write_text(
            """---
name: sample-skill
description: "Sample tool."
distinctive_strings:
  - "legacy-capability"
---
# Sample
## Scope
Legacy capability.
""",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "--no-verify", "-m", "Baseline commit"],
            cwd=repo_dir,
            check=True,
        )

        # Removed from distinctive_strings frontmatter, BUT retained in references
        retained_skill = SkillAsset(
            name="sample-skill",
            description="Sample tool.",
            body="## Scope\n\nMain description.",
            distinctive_strings=("new-keyword",),
            resources=(("references/details.md", "Here legacy-capability is kept."),),
        )
        bundle = AssetBundle(
            metadata=BundleMetadata(name="test-plugin", version="0.1.0"),
            skills=(retained_skill,),
        )

        warnings = check_baseline_capability_erosion(
            bundle,
            baseline_ref="HEAD",
            manifest_path=manifest_file,
            cwd=repo_dir,
        )
        assert warnings == []

    def test_baseline_ref_invalid_exit_2_cli(self) -> None:
        """cisternal assets validate --baseline-ref exits 2 on nonexistent git ref."""
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "assets",
                "validate",
                "--manifest",
                ".praxia/manifest.toml",
                "--baseline-ref",
                "nonexistent-git-ref-xyz",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 2
        assert "invalid baseline ref" in res.stderr

    def test_baseline_ref_head_overflow_exit_2_cli(self) -> None:
        """cisternal assets validate --baseline-ref exits 2 on HEAD~99999."""
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "assets",
                "validate",
                "--manifest",
                ".praxia/manifest.toml",
                "--baseline-ref",
                "HEAD~99999",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 2
        assert "invalid baseline ref" in res.stderr

    def test_baseline_ref_invalid_python_value_error(self) -> None:
        """check_baseline_capability_erosion directly raises ValueError on invalid git ref."""
        bundle = AssetBundle(metadata=BundleMetadata(name="test", version="1.0"))
        with pytest.raises(
            ValueError, match="invalid baseline ref: nonexistent-git-ref-xyz"
        ):
            check_baseline_capability_erosion(
                bundle, baseline_ref="nonexistent-git-ref-xyz"
            )

        with pytest.raises(ValueError, match="invalid baseline ref: HEAD~99999"):
            check_baseline_capability_erosion(bundle, baseline_ref="HEAD~99999")

    def test_baseline_new_skill_skipped_cleanly(self) -> None:
        """Newly added skill absent in baseline ref is cleanly skipped."""
        report = load_asset_report(manifest=Path(".praxia/manifest.toml"))
        # At HEAD commit (82293e7), triage-tool did not exist in git
        warnings = check_baseline_capability_erosion(
            report.bundle,
            baseline_ref="HEAD",
            manifest_path=Path(".praxia/manifest.toml"),
        )
        assert warnings == []

    def test_containment_case_insensitivity_and_whitespace(self) -> None:
        """Check (a) containment handles case-insensitivity and strips leading/trailing spaces."""
        skill = SkillAsset(
            name="test-skill",
            description="Provides PRUNE-LIST and cisternal usage features.",
            body="## When to Use\n\nRun triage-tool now.",
            distinctive_strings=("  prune-list  ", "CISternal USAGE", "triage-tool"),
        )
        assert check_distinctive_strings_containment(skill) == []


class TestCheckBNoOverclaim:
    """Stress tests for Check (b) topic token extraction and overclaim verification."""

    def test_strip_code_fences_nested_quadruple_and_triple(self) -> None:
        """strip_code_fences handles nested fences (quadruple backticks enclosing triple backticks) and tildes."""
        nested_text = """
Introduction
````markdown
```python
def ungrounded_token():
    pass
```
````
Normal prose with `real_token`.
~~~bash
echo "inside tildes"
~~~
Final paragraph.
"""
        stripped = strip_code_fences(nested_text)
        assert "ungrounded_token" not in stripped
        assert "inside tildes" not in stripped
        assert "Normal prose with `real_token`." in stripped
        assert "Final paragraph." in stripped

    def test_strip_code_fences_odd_backticks_do_not_invert_inline_tokens(self) -> None:
        """Triple backticks inside fenced blocks do not invert inline backtick parsing outside."""
        text = """
Text before
```bash
echo `foo`
echo ```
echo `bar`
```
Text after with `my_valid_inline` span.
"""
        stripped = strip_code_fences(text)
        assert "echo" not in stripped
        assert "my_valid_inline" in stripped

    def test_pascal_and_camel_regex_boundary_single_capitalized_words(self) -> None:
        """Single capitalized prose words (e.g. 'Build', 'Decides', 'When') are NOT topic candidates."""
        skill = SkillAsset(
            name="test-caps",
            description="Build decides when to run the task with standard tooling.",
            body="## Scope\n\nGeneral prose without headings for build or decides.",
            distinctive_strings=(),
        )
        warnings = check_listing_no_overclaim(skill)
        assert warnings == [], (
            f"Unexpected warnings for single capitalized words: {warnings}"
        )

    def test_pascal_and_camel_regex_boundary_compound_identifiers(self) -> None:
        """Terms like 'QuantumEngine' and 'mySpecialTool' MUST be detected and flagged when ungrounded."""
        skill = SkillAsset(
            name="test-detected",
            description="Integrates QuantumEngine and mySpecialTool seamlessly.",
            body="## Scope\n\nNo mention here.",
            distinctive_strings=(),
        )
        warnings = check_listing_no_overclaim(skill)
        assert len(warnings) == 2
        assert any("QuantumEngine" in w for w in warnings)
        assert any("mySpecialTool" in w for w in warnings)

    def test_backticked_function_call_literals(self) -> None:
        """Backticked literals with `()` strip the parens and match identifier in body or references."""
        # Body has bare my_func
        skill_pass = SkillAsset(
            name="test-func",
            description="Invokes `my_func()` for execution.",
            body="## Scope\n\nBody mentions my_func without parentheses.",
            distinctive_strings=(),
        )
        assert check_listing_no_overclaim(skill_pass) == []

        # Absent from body
        skill_fail = SkillAsset(
            name="test-func-fail",
            description="Invokes `missing_func()` for execution.",
            body="## Scope\n\nOther functions.",
            distinctive_strings=(),
        )
        warns = check_listing_no_overclaim(skill_fail)
        assert len(warns) == 1
        assert "missing_func" in warns[0]

    def test_stopword_filtering_case_insensitive(self) -> None:
        """Case-insensitive stopwords ('agent-asset', 'read-only', 'fail-open', 'cli-to-mcp') are filtered."""
        for word in ("agent-asset", "read-only", "fail-open", "cli-to-mcp"):
            assert word.lower() in C4A_STOPWORDS

        skill = SkillAsset(
            name="test-stops",
            description="Provides READ-ONLY AGENT-ASSET with FAIL-OPEN CLI-TO-MCP handling.",
            body="## Scope\n\nProse without headings.",
            distinctive_strings=(),
        )
        assert check_listing_no_overclaim(skill) == []

    def test_distinctive_strings_shielding_prose_only(self) -> None:
        """Terms matching distinctive_strings are shielded from Check (b) even in ungrounded plain prose."""
        skill = SkillAsset(
            name="test-shield",
            description="Provides custom-pipeline and DeepOptimizer support.",
            body="## Scope\n\nIn plain prose without code fences, custom-pipeline and DeepOptimizer are discussed.",
            distinctive_strings=("custom-pipeline", "DeepOptimizer"),
        )
        assert check_listing_no_overclaim(skill) == []

    def test_grounding_in_headings_fences_and_inline_code(self) -> None:
        """Non-backticked topic candidates pass if grounded in heading, code fence, or inline span."""
        # 1. Grounded in heading
        s1 = SkillAsset(
            name="s1",
            description="Uses NeuralOptimizer.",
            body="## Scope\n\n### NeuralOptimizer Configuration\n\nDetails.",
        )
        assert check_listing_no_overclaim(s1) == []

        # 2. Grounded in fenced code block (including quadruple backticks)
        s2 = SkillAsset(
            name="s2",
            description="Uses NeuralOptimizer.",
            body="## Scope\n\n````markdown\n```python\nNeuralOptimizer.run()\n```\n````",
        )
        assert check_listing_no_overclaim(s2) == []

        # 3. Grounded in inline code span
        s3 = SkillAsset(
            name="s3",
            description="Uses NeuralOptimizer.",
            body="## Scope\n\nRun with `NeuralOptimizer` activated.",
        )
        assert check_listing_no_overclaim(s3) == []


class TestCheckCScopeHeader:
    """Stress tests for Check (c) scope heading detection and boundary enforcement."""

    def test_scope_header_line_50_vs_51(self) -> None:
        """Heading on line 50 passes; heading on line 51 fails."""
        # Exactly line 50 (49 lines + heading)
        body_line_50 = ("line\n" * 49) + "## Scope\n"
        assert (
            check_scope_header(
                SkillAsset(name="t50", description="", body=body_line_50)
            )
            == []
        )

        # Exactly line 51 (50 lines + heading)
        body_line_51 = ("line\n" * 50) + "## Scope\n"
        warns_51 = check_scope_header(
            SkillAsset(name="t51", description="", body=body_line_51)
        )
        assert len(warns_51) == 1
        assert (
            "missing '## Scope' or '## When to Use' heading within first 50 body lines"
            in warns_51[0]
        )

    def test_scope_header_character_offset_boundary(self) -> None:
        """Heading starting within 2,000 characters passes; heading starting beyond 2,000 characters fails."""
        # Preceding content with 1,999 characters (heading starts at 2,000th character, offset 1999)
        body_char_2000 = ("a" * 1998) + "\n## Scope\n"
        assert (
            check_scope_header(
                SkillAsset(name="t2000", description="", body=body_char_2000)
            )
            == []
        )

        # Preceding content with 2,000 characters (heading starts at 2,001st character, offset 2000)
        body_char_2001 = ("a" * 1999) + "\n## Scope\n"
        warns_2001 = check_scope_header(
            SkillAsset(name="t2001", description="", body=body_char_2001)
        )
        assert len(warns_2001) == 1
        assert "exceeding 2000 character limit" in warns_2001[0]

    def test_scope_header_case_insensitivity_and_variants(self) -> None:
        """Headings matching '## scope', '## WHEN TO USE', '## Scope: Overview' all pass."""
        for variant in (
            "## scope",
            "## WHEN TO USE",
            "## Scope: Overview",
            "## When to Use: Details",
            "##   Scope",
            "##   when   to   use",
        ):
            skill = SkillAsset(
                name="t", description="", body=f"{variant}\n\nBody content."
            )
            assert check_scope_header(skill) == [], f"Variant failed: {variant}"

    def test_scope_header_markdown_heading_levels(self) -> None:
        """Only '##' level headings pass; '#', '###', '####' and unrelated words fail."""
        for invalid in (
            "# Scope",
            "### Scope",
            "#### Scope",
            "# When to Use",
            "### When to Use",
            "## Scopes",
            "## Scoped",
        ):
            skill = SkillAsset(
                name="t", description="", body=f"{invalid}\n\nBody content."
            )
            warns = check_scope_header(skill)
            assert len(warns) == 1, f"Expected failure for {invalid}, got: {warns}"


class TestC6TriageToolStress:
    """Stress tests for C6 triage-tool skill constraints and security audit."""

    def test_triage_tool_listing_character_cap(self) -> None:
        """triage-tool listing length strictly satisfies listing_chars <= 150 (Spec §C6)."""
        report = load_asset_report(manifest=Path(".praxia/manifest.toml"))
        triage = next(
            (s for s in report.bundle.skills if s.name == "triage-tool"), None
        )
        assert triage is not None, "triage-tool not found in manifest bundle"
        assert triage.listing_chars <= 150
        assert triage.listing_chars == 102

    def test_triage_tool_security_audit_no_mutating_commands(self) -> None:
        """Security audit: triage-tool SKILL.md and references contain zero commands mutating host configs."""
        paths = [
            Path(".praxia/skills/triage-tool/SKILL.md"),
            Path(".praxia/skills/triage-tool/references/triage_workflow.md"),
        ]
        for p in paths:
            assert p.is_file(), f"Missing file: {p}"
            text = p.read_text(encoding="utf-8")
            # Verify no redirect or shell overwrite of settings.json, .claude.json, config.toml
            assert not re.search(r">\s*~?/\.claude", text)
            assert not re.search(r"rm\s+~?/\.claude", text)
            assert not re.search(r"sed\s+.*settings\.json", text)
            assert not re.search(r">\s*~?/\.config/cisternal", text)
            assert not re.search(r"rm\s+~?/\.config/cisternal", text)

    def test_triage_tool_explicit_non_destructive_contract(self) -> None:
        """triage-tool explicitly affirms non-destructive operation."""
        skill_text = Path(".praxia/skills/triage-tool/SKILL.md").read_text(
            encoding="utf-8"
        )
        ref_text = Path(
            ".praxia/skills/triage-tool/references/triage_workflow.md"
        ).read_text(encoding="utf-8")
        assert "never writes or modifies" in skill_text.lower()
        assert "~/.claude/settings.json" in skill_text
        assert "~/.claude.json" in skill_text
        assert "non-destructive recommendations" in ref_text.lower()


class TestGoldenDigestIntegrity:
    """Verify integrity of all golden digests and snapshot check."""

    def test_snapshot_parity_check(self) -> None:
        """cisternal assets snapshot --check exits 0 without drift."""
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "assets",
                "snapshot",
                "--manifest",
                ".praxia/manifest.toml",
                "--out",
                "src/cisternal/agent_plugin.json",
                "--check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert "snapshot up to date" in res.stdout

    def test_all_self_manifest_golden_digests_match(self) -> None:
        """All 8 standard digests and 4 rust-parity digests match current manifest output."""
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_golden_matrix.py",
                "tests/test_rust_parity_matrix.py",
                "-k",
                "self_manifest",
                "-v",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert "12 passed" in res.stdout
