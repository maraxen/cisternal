"""Adversarial stress-testing suite for Milestone M4 (Track C Part 2: C3 Skill Coverage Engine).

Executed by challenger_m4_1 to adversarially test:
1. Token boundary matching in match_distinctive_strings:
   - Substring matches that are NOT whole-tokens (e.g. pyo3 in pyo3_bindings, unpyo3, pyo3000, pyo3-lib).
   - Unicode punctuation, brackets, hyphens, underscores, quotes around distinctive strings.
   - Distinctive strings containing special regex characters or multiple words ("cisternal usage", "telemetry doctor").
2. evaluate_situation_set invariants & boundaries:
   - Zero situations, underpowered sample size n < 50 (assert status INCONCLUSIVE).
   - Boundary condition n = 50: precision exactly at 0.80 vs 0.78 vs 0.799 vs 0.801.
   - Exact mathematical check of Wilson confidence intervals against manual formula.
   - Situations with multiple expected skills and multiple detected skills (TP, FP, FN calculation accuracy).
3. mine_skill_opportunities stress-testing:
   - Transcripts with interleaved user prompts, tool use, subagents, and skills.
   - Empirical verification of TranscriptEvent attribute access bug and transcript schema mismatch.
   - Verification of loaded_before_action detection and missed opportunity categorization.
4. CLI cisternal skill-coverage flags & safety:
   - Multiple repeatable --manifest options.
   - Non-existent situations file (fails gracefully with INCONCLUSIVE).
   - --situations-out with directory creation and JSONL validation.
   - Read-only guarantee: verify running skill-coverage with unconfigured marketplace NEVER creates ~/.config/cisternal/config.toml.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys

from cisternal.assets.bundle import SkillAsset
from cisternal.usage.coverage import (
    evaluate_situation_set,
    load_monitored_skills,
    match_distinctive_strings,
    mine_skill_opportunities,
)
from cisternal.usage.usage import wilson_confidence_interval


# ==============================================================================
# Suite 1: Token Boundary Matching (match_distinctive_strings)
# ==============================================================================


class TestTokenBoundaryMatchingAdversarial:
    """Stress-test whole-token case-insensitive boundary matching for distinctive strings."""

    def test_substring_matches_rejected(self) -> None:
        """Substrings of larger tokens must be strictly rejected."""
        distinctive = ["pyo3", "prune-list", "export-trust"]

        # Postfix extensions
        assert match_distinctive_strings("pyo3_bindings are here", distinctive) == []
        assert match_distinctive_strings("pyo3000 is futuristic", distinctive) == []
        assert match_distinctive_strings("prune-listing details", distinctive) == []
        assert match_distinctive_strings("export-trusts are valid", distinctive) == []
        assert match_distinctive_strings("pyo3-dev module", distinctive) == []

        # Prefix extensions
        assert match_distinctive_strings("unpyo3 is invalid", distinctive) == []
        assert match_distinctive_strings("pre-pyo3 build", distinctive) == []
        assert match_distinctive_strings("subprune-list items", distinctive) == []
        assert match_distinctive_strings("noexport-trust check", distinctive) == []

        # Infix substrings
        assert match_distinctive_strings("the_pyo3_engine", distinctive) == []
        assert match_distinctive_strings("run_prune-list_now", distinctive) == []

    def test_brackets_quotes_delimiters_accepted(self) -> None:
        """Standard delimiters (brackets, parens, quotes, backticks) must match."""
        distinctive = ["pyo3", "re-implement", "customizing-tools"]

        # Parentheses and brackets
        assert match_distinctive_strings("(pyo3)", distinctive) == ["pyo3"]
        assert match_distinctive_strings("[pyo3]", distinctive) == ["pyo3"]
        assert match_distinctive_strings("{pyo3}", distinctive) == ["pyo3"]
        assert match_distinctive_strings("<pyo3>", distinctive) == ["pyo3"]

        # Quotes: standard, curly, and typographic
        assert match_distinctive_strings('"pyo3"', distinctive) == ["pyo3"]
        assert match_distinctive_strings("'pyo3'", distinctive) == ["pyo3"]
        assert match_distinctive_strings("`pyo3`", distinctive) == ["pyo3"]
        assert match_distinctive_strings("“pyo3”", distinctive) == ["pyo3"]
        assert match_distinctive_strings("‘pyo3’", distinctive) == ["pyo3"]
        assert match_distinctive_strings("«pyo3»", distinctive) == ["pyo3"]

        # Delimited hyphenated strings
        assert match_distinctive_strings('("re-implement")', distinctive) == [
            "re-implement"
        ]
        assert match_distinctive_strings("`customizing-tools`", distinctive) == [
            "customizing-tools"
        ]

    def test_unicode_punctuation_accepted(self) -> None:
        """Unicode dashes, ellipses, inverted punctuation must serve as token boundaries."""
        distinctive = ["pyo3", "telemetry doctor"]

        # Em dash and en dash
        assert match_distinctive_strings("use—pyo3—here", distinctive) == ["pyo3"]
        assert match_distinctive_strings("start–pyo3–end", distinctive) == ["pyo3"]

        # Ellipsis
        assert match_distinctive_strings("loading…pyo3…done", distinctive) == ["pyo3"]

        # International punctuation
        assert match_distinctive_strings("¿pyo3?", distinctive) == ["pyo3"]
        assert match_distinctive_strings("¡pyo3!", distinctive) == ["pyo3"]

        # Sentence terminators and commas
        assert match_distinctive_strings("Check pyo3. Then proceed.", distinctive) == [
            "pyo3"
        ]
        assert match_distinctive_strings(
            "Review pyo3, bathos, and xtrax.", distinctive
        ) == ["pyo3"]
        assert match_distinctive_strings("Is it pyo3? Yes!", distinctive) == ["pyo3"]

    def test_multi_word_distinctive_strings(self) -> None:
        """Multi-word phrases must match with exact internal whitespace and boundaries."""
        distinctive = ["cisternal usage", "telemetry doctor", "assets export"]

        # Exact match
        assert match_distinctive_strings("run cisternal usage --json", distinctive) == [
            "cisternal usage"
        ]
        assert match_distinctive_strings("check telemetry doctor now", distinctive) == [
            "telemetry doctor"
        ]

        # Case-insensitivity
        assert match_distinctive_strings("Run Cisternal Usage Now", distinctive) == [
            "cisternal usage"
        ]
        assert match_distinctive_strings("TELEMETRY DOCTOR output", distinctive) == [
            "telemetry doctor"
        ]

        # Partial word extensions must be rejected
        assert match_distinctive_strings("cisternal usages report", distinctive) == []
        assert match_distinctive_strings("telemetry doctors on call", distinctive) == []
        assert match_distinctive_strings("assets exporting now", distinctive) == []

    def test_special_regex_characters_in_distinctive_string(self) -> None:
        """Distinctive strings containing regex metacharacters must be safely escaped."""
        distinctive = ["c++", "v1.0.0", "a+b", "re-implement?"]

        assert match_distinctive_strings("compile c++ codebase", distinctive) == ["c++"]
        assert match_distinctive_strings("compile c++11 codebase", distinctive) == []
        assert match_distinctive_strings("release v1.0.0 is live", distinctive) == [
            "v1.0.0"
        ]
        assert (
            match_distinctive_strings("release v1.0.00 is invalid", distinctive) == []
        )

    def test_empty_and_whitespace_distinctive_strings_ignored(self) -> None:
        """Empty or whitespace-only distinctive strings must be skipped without errors."""
        distinctive = ["", "   ", "valid-token", "\t\n"]
        assert match_distinctive_strings("check valid-token now", distinctive) == [
            "valid-token"
        ]
        assert match_distinctive_strings("just some text", distinctive) == []


# ==============================================================================
# Suite 2: Situation Benchmark Evaluation (evaluate_situation_set)
# ==============================================================================


class TestEvaluateSituationSetAdversarial:
    """Stress-test evaluate_situation_set statistical gates and multi-label calculation."""

    @staticmethod
    def _manual_wilson(x: int, n: int, z: float = 1.95996) -> tuple[float, float]:
        """Independent reference implementation of 95% two-sided Wilson interval."""
        if n <= 0:
            return 0.0, 0.0
        p_hat = x / n
        denom = 1.0 + (z * z) / n
        center = (p_hat + (z * z) / (2.0 * n)) / denom
        radicand = (p_hat * (1.0 - p_hat) / n) + ((z * z) / (4.0 * n * n))
        margin = (z / denom) * math.sqrt(max(0.0, radicand))
        return max(0.0, center - margin), min(1.0, center + margin)

    def test_wilson_ci_exact_mathematical_parity(self) -> None:
        """Verify Wilson interval implementation matches reference formula across grid."""
        test_cases = [
            (0, 0),
            (0, 1),
            (1, 1),
            (0, 50),
            (40, 50),
            (50, 50),
            (30, 60),
            (60, 60),
            (100, 120),
            (799, 1000),
            (800, 1000),
            (801, 1000),
        ]
        for x, n in test_cases:
            ref_low, ref_high = self._manual_wilson(x, n)
            ci = wilson_confidence_interval(x, n)
            assert math.isclose(ci.lower, ref_low, abs_tol=1e-12), (
                f"Lower bound mismatch for {x}/{n}"
            )
            assert math.isclose(ci.upper, ref_high, abs_tol=1e-12), (
                f"Upper bound mismatch for {x}/{n}"
            )

    def test_zero_situations_inconclusive(self, tmp_path: Path) -> None:
        """Zero situations file (or empty file) must yield INCONCLUSIVE status."""
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("", encoding="utf-8")

        skills = {
            "triage-tool": SkillAsset(
                name="triage-tool", distinctive_strings=("prune-list",)
            )
        }
        report, records = evaluate_situation_set(
            empty_file, skills=skills, threshold=0.80
        )

        assert report.total_situations == 0
        assert report.matched_turns == 0
        assert report.true_positives == 0
        assert report.false_positives == 0
        assert report.false_negatives == 0
        assert report.precision == 0.0
        assert report.recall == 0.0
        assert report.status == "INCONCLUSIVE"
        assert len(records) == 0

    def test_underpowered_sample_size_inconclusive(self, tmp_path: Path) -> None:
        """n = 49 matched turns (< 50) must return INCONCLUSIVE even with 100% precision."""
        situations_file = tmp_path / "n49.jsonl"
        with open(situations_file, "w", encoding="utf-8") as f:
            for i in range(49):
                f.write(
                    json.dumps(
                        {
                            "id": f"sit_{i}",
                            "prompt": "Run prune-list now",
                            "expected_skills": ["triage-tool"],
                        }
                    )
                    + "\n"
                )

        skills = {
            "triage-tool": SkillAsset(
                name="triage-tool", distinctive_strings=("prune-list",)
            )
        }
        report, _ = evaluate_situation_set(
            situations_file, skills=skills, threshold=0.80
        )
        assert report.matched_turns == 49
        assert report.precision == 1.00
        assert report.status == "INCONCLUSIVE"

    def test_boundary_n50_exact_threshold_transitions(self, tmp_path: Path) -> None:
        """n = 50 boundary: precision = 0.80 PASS vs 0.78 FAIL."""
        # 1. 40 TP, 10 FP -> 40/50 = 0.8000 -> PASS
        pass_file = tmp_path / "pass_50.jsonl"
        with open(pass_file, "w", encoding="utf-8") as f:
            for i in range(40):
                f.write(
                    json.dumps(
                        {
                            "id": f"tp_{i}",
                            "prompt": "Run prune-list",
                            "expected_skills": ["triage-tool"],
                        }
                    )
                    + "\n"
                )
            for i in range(10):
                f.write(
                    json.dumps(
                        {
                            "id": f"fp_{i}",
                            "prompt": "Run prune-list",
                            "expected_skills": ["other"],
                        }
                    )
                    + "\n"
                )

        skills = {
            "triage-tool": SkillAsset(
                name="triage-tool", distinctive_strings=("prune-list",)
            )
        }
        report_pass, _ = evaluate_situation_set(
            pass_file, skills=skills, threshold=0.80
        )
        assert report_pass.matched_turns == 50
        assert report_pass.true_positives == 40
        assert report_pass.false_positives == 10
        assert report_pass.precision == 0.80
        assert report_pass.status == "PASS"

        # 2. 39 TP, 11 FP -> 39/50 = 0.7800 -> FAIL
        fail_file = tmp_path / "fail_50.jsonl"
        with open(fail_file, "w", encoding="utf-8") as f:
            for i in range(39):
                f.write(
                    json.dumps(
                        {
                            "id": f"tp_{i}",
                            "prompt": "Run prune-list",
                            "expected_skills": ["triage-tool"],
                        }
                    )
                    + "\n"
                )
            for i in range(11):
                f.write(
                    json.dumps(
                        {
                            "id": f"fp_{i}",
                            "prompt": "Run prune-list",
                            "expected_skills": ["other"],
                        }
                    )
                    + "\n"
                )

        report_fail, _ = evaluate_situation_set(
            fail_file, skills=skills, threshold=0.80
        )
        assert report_fail.matched_turns == 50
        assert report_fail.true_positives == 39
        assert report_fail.false_positives == 11
        assert report_fail.precision == 0.78
        assert report_fail.status == "FAIL"

    def test_precision_boundary_0799_vs_0801(self, tmp_path: Path) -> None:
        """Test fine boundary precision around 0.80: 0.799 FAIL vs 0.801 PASS."""
        # 1. 799 / 1000 = 0.799 -> FAIL
        f799 = tmp_path / "sit_799.jsonl"
        with open(f799, "w", encoding="utf-8") as f:
            for i in range(799):
                f.write(
                    json.dumps(
                        {
                            "id": f"tp_{i}",
                            "prompt": "prune-list",
                            "expected_skills": ["triage-tool"],
                        }
                    )
                    + "\n"
                )
            for i in range(201):
                f.write(
                    json.dumps(
                        {"id": f"fp_{i}", "prompt": "prune-list", "expected_skills": []}
                    )
                    + "\n"
                )

        skills = {
            "triage-tool": SkillAsset(
                name="triage-tool", distinctive_strings=("prune-list",)
            )
        }
        r799, _ = evaluate_situation_set(f799, skills=skills, threshold=0.80)
        assert r799.matched_turns == 1000
        assert math.isclose(r799.precision, 0.799, abs_tol=1e-6)
        assert r799.status == "FAIL"

        # 2. 801 / 1000 = 0.801 -> PASS
        f801 = tmp_path / "sit_801.jsonl"
        with open(f801, "w", encoding="utf-8") as f:
            for i in range(801):
                f.write(
                    json.dumps(
                        {
                            "id": f"tp_{i}",
                            "prompt": "prune-list",
                            "expected_skills": ["triage-tool"],
                        }
                    )
                    + "\n"
                )
            for i in range(199):
                f.write(
                    json.dumps(
                        {"id": f"fp_{i}", "prompt": "prune-list", "expected_skills": []}
                    )
                    + "\n"
                )

        r801, _ = evaluate_situation_set(f801, skills=skills, threshold=0.80)
        assert r801.matched_turns == 1000
        assert math.isclose(r801.precision, 0.801, abs_tol=1e-6)
        assert r801.status == "PASS"

    def test_multi_label_tp_fp_fn_accuracy(self, tmp_path: Path) -> None:
        """Complex situation benchmark with multiple expected and detected skills."""
        sit_file = tmp_path / "multilabel.jsonl"
        skills = {
            "skill_a": SkillAsset(name="skill_a", distinctive_strings=("alpha_token",)),
            "skill_b": SkillAsset(name="skill_b", distinctive_strings=("beta_token",)),
            "skill_c": SkillAsset(name="skill_c", distinctive_strings=("gamma_token",)),
        }

        records_data = [
            # Sit 1: expected {a, b}, detected {a, b} -> TP=2, FP=0, FN=0
            {
                "id": "s1",
                "prompt": "alpha_token and beta_token",
                "expected_skills": ["skill_a", "skill_b"],
            },
            # Sit 2: expected {a}, detected {a, c} -> TP=1, FP=1 (c), FN=0
            {
                "id": "s2",
                "prompt": "alpha_token and gamma_token",
                "expected_skills": ["skill_a"],
            },
            # Sit 3: expected {b, c}, detected {b} -> TP=1, FP=0, FN=1 (c)
            {
                "id": "s3",
                "prompt": "beta_token only",
                "expected_skills": ["skill_b", "skill_c"],
            },
            # Sit 4: expected {a}, detected {} -> TP=0, FP=0, FN=1 (a)
            {"id": "s4", "prompt": "unrelated content", "expected_skills": ["skill_a"]},
            # Sit 5: expected {}, detected {c} -> TP=0, FP=1 (c), FN=0
            {"id": "s5", "prompt": "gamma_token extra", "expected_skills": []},
        ]

        with open(sit_file, "w", encoding="utf-8") as f:
            for item in records_data:
                f.write(json.dumps(item) + "\n")

        report, eval_records = evaluate_situation_set(
            sit_file, skills=skills, threshold=0.50
        )

        # Expected totals across all 5 situations:
        # s1: tp=2, fp=0, fn=0
        # s2: tp=1, fp=1, fn=0
        # s3: tp=1, fp=0, fn=1
        # s4: tp=0, fp=0, fn=1
        # s5: tp=0, fp=1, fn=0
        # Total TP = 4, Total FP = 2, Total FN = 2
        # Matched turns (predictions) n = TP + FP = 6
        assert report.total_situations == 5
        assert report.matched_turns == 6
        assert report.true_positives == 4
        assert report.false_positives == 2
        assert report.false_negatives == 2
        assert math.isclose(report.precision, 4 / 6, abs_tol=1e-6)
        assert math.isclose(report.recall, 4 / 6, abs_tol=1e-6)

        # Per skill breakdowns:
        # skill_a: detected in s1, s2. expected in s1, s2, s4.
        #   s1: TP, s2: TP, s4: FN -> TP=2, FP=0, FN=1
        assert report.per_skill_stats["skill_a"]["tp"] == 2
        assert report.per_skill_stats["skill_a"]["fp"] == 0
        assert report.per_skill_stats["skill_a"]["fn"] == 1

        # skill_b: detected in s1, s3. expected in s1, s3.
        #   s1: TP, s3: TP -> TP=2, FP=0, FN=0
        assert report.per_skill_stats["skill_b"]["tp"] == 2
        assert report.per_skill_stats["skill_b"]["fp"] == 0
        assert report.per_skill_stats["skill_b"]["fn"] == 0

        # skill_c: detected in s2, s5. expected in s3.
        #   s2: FP, s3: FN, s5: FP -> TP=0, FP=2, FN=1
        assert report.per_skill_stats["skill_c"]["tp"] == 0
        assert report.per_skill_stats["skill_c"]["fp"] == 2
        assert report.per_skill_stats["skill_c"]["fn"] == 1


# ==============================================================================
# Suite 3: Opportunity Mining Stress Testing (mine_skill_opportunities)
# ==============================================================================


class TestMineSkillOpportunitiesAdversarial:
    """Stress-test mine_skill_opportunities on session transcripts and surface defects."""

    def test_transcript_event_attribute_error_bug_reproduction(
        self, tmp_path: Path
    ) -> None:
        """Verify mine_skill_opportunities runs safely without AttributeError on transcripts.

        Validates fix for TranscriptEvent dataclass access via ev.event_type and ev.raw_record.
        """
        proj_dir = tmp_path / "project_alpha"
        proj_dir.mkdir()
        sess_file = proj_dir / "sess1.jsonl"
        sess_file.write_text(
            json.dumps({"type": "user", "message": {"content": "Run prune-list now"}})
            + "\n",
            encoding="utf-8",
        )

        skills = {
            "triage-tool": SkillAsset(
                name="triage-tool", distinctive_strings=("prune-list",)
            )
        }

        report = mine_skill_opportunities(tmp_path, skills)
        assert "triage-tool" in report.skills
        assert report.skills["triage-tool"].opportunities == 1
        assert report.skills["triage-tool"].missed_opportunities == 1

    def test_transcript_schema_mismatch_adversarial_analysis(
        self, tmp_path: Path
    ) -> None:
        """Verify mine_skill_opportunities correctly parses nested Claude Code transcripts.

        Claude Code transcripts use:
          event_type == 'user' with message.content
          event_type == 'assistant' containing content blocks with type 'tool_use'
        """
        proj_dir = tmp_path / "project_beta"
        proj_dir.mkdir()
        sess_file = proj_dir / "sess2.jsonl"
        # Golden Claude Code transcript style
        sess_file.write_text(
            json.dumps(
                {"type": "user", "message": {"content": "Please run prune-list"}}
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
            + "\n",
            encoding="utf-8",
        )

        skills = {
            "triage-tool": SkillAsset(
                name="triage-tool", distinctive_strings=("prune-list",)
            )
        }

        report = mine_skill_opportunities(tmp_path, skills)
        assert "triage-tool" in report.skills
        stat = report.skills["triage-tool"]
        assert stat.opportunities == 1
        assert stat.invoked == 1
        assert stat.loaded_before_action == 1
        assert stat.missed_opportunities == 0


# ==============================================================================
# Suite 4: CLI Flags, Repeatability, and Config Safety
# ==============================================================================


class TestCliSkillCoverageAdversarial:
    """Stress-test cisternal skill-coverage CLI options, error handling, and host safety."""

    def test_cli_repeatable_manifest_options(self, tmp_path: Path) -> None:
        """Repeatable --manifest options should load and monitor skills from multiple manifests."""
        # Skill 1 and Manifest 1
        s1 = tmp_path / "skill1.md"
        s1.write_text(
            """---
name: skill-m1
description: First skill
covers_families: []
distinctive_strings:
  - distinctive_m1
---
## When to Use
Scope content here.
""",
            encoding="utf-8",
        )
        m1 = tmp_path / "manifest1.toml"
        m1.write_text(
            f"""[plugin]
name = "m1"
version = "0.1.0"

[[plugin.skills]]
name = "skill-m1"
path = "{s1}"
""",
            encoding="utf-8",
        )

        # Skill 2 and Manifest 2
        s2 = tmp_path / "skill2.md"
        s2.write_text(
            """---
name: skill-m2
description: Second skill
covers_families: []
distinctive_strings:
  - distinctive_m2
---
## When to Use
Scope content here.
""",
            encoding="utf-8",
        )
        m2 = tmp_path / "manifest2.toml"
        m2.write_text(
            f"""[plugin]
name = "m2"
version = "0.1.0"

[[plugin.skills]]
name = "skill-m2"
path = "{s2}"
""",
            encoding="utf-8",
        )

        monitored, unmonitored = load_monitored_skills(manifest_paths=[m1, m2])
        assert "skill-m1" in monitored
        assert "skill-m2" in monitored
        assert len(monitored) == 2

        # Verify CLI also accepts multiple --manifest options
        empty_projects = tmp_path / "empty_projects"
        empty_projects.mkdir()
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "skill-coverage",
                "--manifest",
                str(m1),
                "--manifest",
                str(m2),
                "--projects-dir",
                str(empty_projects),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert "skill-m1" in data["skills"]
        assert "skill-m2" in data["skills"]

    def test_cli_mining_transcripts_attribute_error_defect(
        self, tmp_path: Path
    ) -> None:
        """Verify cisternal skill-coverage runs successfully when transcripts exist in projects-dir."""
        proj_dir = tmp_path / "transcripts_dir" / "sample_slug"
        proj_dir.mkdir(parents=True)
        sess_file = proj_dir / "sess.jsonl"
        sess_file.write_text(
            json.dumps({"type": "user", "message": {"content": "Run prune-list now"}})
            + "\n",
            encoding="utf-8",
        )

        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--projects-dir",
                str(tmp_path / "transcripts_dir"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert "triage-tool" in res.stdout
        assert "opportunities=1" in res.stdout

    def test_cli_nonexistent_situations_file_graceful(self) -> None:
        """Running skill-coverage with a non-existent situations file fails gracefully."""
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                "nonexistent_situations_fixture_12345.jsonl",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert "Gate Status: INCONCLUSIVE" in res.stdout
        assert "Total situations: 0" in res.stdout

    def test_cli_situations_out_nested_directory_creation(self, tmp_path: Path) -> None:
        """--situations-out must create parent directories and emit valid JSONL records."""
        out_target = tmp_path / "deep" / "nested" / "dir" / "out.jsonl"
        assert not out_target.parent.exists()

        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                "tests/fixtures/situations/synthetic_situations.jsonl",
                "--situations-out",
                str(out_target),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert out_target.is_file()

        lines = [
            json.loads(line)
            for line in out_target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 80
        for record in lines:
            assert "id" in record
            assert "prompt" in record
            assert "expected_skills" in record
            assert "detected_skills" in record
            assert "tp" in record
            assert "fp" in record
            assert "fn" in record

    def test_cli_read_only_guarantee_no_config_mutation(self, tmp_path: Path) -> None:
        """MANDATORY SAFETY: Running skill-coverage MUST NEVER create or touch ~/.config/cisternal/config.toml."""
        fake_config_home = tmp_path / "fake_xdg_config"
        fake_config_home.mkdir()

        env = dict(os.environ)
        env["XDG_CONFIG_HOME"] = str(fake_config_home)
        # Ensure CISTERNAL_PLUGIN_MARKETPLACE is unset
        env.pop("CISTERNAL_PLUGIN_MARKETPLACE", None)

        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--situations",
                "tests/fixtures/situations/synthetic_situations.jsonl",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert res.returncode == 0

        # Assert no files were written to fake XDG_CONFIG_HOME
        created_files = list(fake_config_home.rglob("*"))
        assert created_files == [], (
            f"Read-only invariant violated: created {created_files}"
        )


# ==============================================================================
# Suite 5: Multi-Session Directory Accumulation Stress Tests
# ==============================================================================


class TestMineSkillOpportunitiesMultiSessionStressAdversarial:
    """Stress-test multi-session transcript discovery and metric accumulation across directories."""

    def test_multi_session_three_plus_sessions_varying_post_load(
        self, tmp_path: Path
    ) -> None:
        """Verify accumulation across 4 sessions with diverse post-load tool counts (3, 1, 0, 4)."""
        slug = tmp_path / "project_slug"
        slug.mkdir()

        # Session 1: 3 post-load calls
        (slug / "s1.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "execute prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file": "a.txt"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Write",
                                "input": {"file": "b.txt"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Session 2: 1 post-load call
        (slug / "s2.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "execute prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "git status"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Session 3: 0 post-load calls
        (slug / "s3.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "execute prune-list"}})
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

        # Session 4: 4 post-load calls
        (slug / "s4.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "execute prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cargo test"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cargo check"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cargo clippy"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "echo done"},
                            },
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
        assert stat.opportunities == 4
        assert stat.invoked == 4
        assert stat.loaded_before_action == 4
        assert stat.missed_opportunities == 0
        assert stat.post_load_tool_calls == 8  # 3 + 1 + 0 + 4 == 8

    def test_multi_session_spanning_multiple_slugs_and_nested_subdirectories(
        self, tmp_path: Path
    ) -> None:
        """Verify accumulation across distinct project slugs and nested subagent directories."""
        slug_a = tmp_path / "slug_alpha"
        slug_a.mkdir()
        (slug_a / "sess_a.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "triage prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cmd1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cmd2"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Claude Code subagents directory: <projects_root>/<slug>/<session_id>/subagents/*.jsonl
        subagent_dir = tmp_path / "slug_beta" / "sess_beta_123" / "subagents"
        subagent_dir.mkdir(parents=True)
        b_content = (
            json.dumps({"type": "user", "message": {"content": "triage prune-list"}})
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
                            },
                            *[
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": f"cmd_{i}"},
                                }
                                for i in range(5)
                            ],
                        ]
                    },
                }
            )
            + "\n"
        )
        (subagent_dir / "sess_b.jsonl").write_text(b_content, encoding="utf-8")

        slug_c = tmp_path / "slug_gamma"
        slug_c.mkdir()
        (slug_c / "sess_c.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "triage prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "final_cmd"},
                            },
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
        assert stat.opportunities == 3
        assert stat.invoked == 3
        assert stat.loaded_before_action == 3
        assert stat.missed_opportunities == 0
        assert stat.post_load_tool_calls == 8  # 2 + 5 + 1 == 8

    def test_multi_session_late_skill_loading_accumulation(
        self, tmp_path: Path
    ) -> None:
        """Verify post-load tool accumulation when skills are invoked after prior actions."""
        proj = tmp_path / "late_loading_proj"
        proj.mkdir()

        # s1: Bash before Skill, then 2 tools after Skill -> lba=0, post=2
        (proj / "s1.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "run prune-list"}})
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Skill",
                                "input": {"skill": "triage-tool"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "pwd"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file": "f.txt"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # s2: Bash before Skill, then 1 tool after Skill -> lba=0, post=1
        (proj / "s2.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "run prune-list"}})
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "whoami"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Skill",
                                "input": {"skill": "triage-tool"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "id"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # s3: Skill loaded immediately before any actions -> lba=1, post=3
        (proj / "s3.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "run prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c2"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c3"},
                            },
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
        assert stat.opportunities == 3
        assert stat.invoked == 3
        assert stat.loaded_before_action == 1  # Only s3 was loaded before action
        assert stat.missed_opportunities == 0
        assert stat.post_load_tool_calls == 6  # 2 + 1 + 3 == 6

    def test_multi_session_zero_opportunities_mixed_with_active_and_missed(
        self, tmp_path: Path
    ) -> None:
        """Verify accumulation when zero-opportunity and missed-opportunity sessions are mixed."""
        proj = tmp_path / "mixed_proj"
        proj.mkdir()

        # s_zero1: prompt without distinctive strings
        (proj / "s0_a.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "what time is it?"}})
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "date"},
                            }
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # s_active: 1 opportunity, loaded before action, 2 post-load calls
        (proj / "s_active.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "run prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "pwd"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # s_zero2: prompt without distinctive strings
        (proj / "s0_b.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "how does rust work?"}})
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cargo --version"},
                            }
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # s_missed: 1 opportunity, 3 tools called, Skill NEVER invoked -> missed=1, post=0
        (proj / "s_missed.jsonl").write_text(
            json.dumps(
                {"type": "user", "message": {"content": "please prune-list items"}}
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
                                "input": {"command": "cat a"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cat b"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cat c"},
                            },
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
        assert stat.invoked == 1
        assert stat.loaded_before_action == 1
        assert stat.missed_opportunities == 1
        assert stat.post_load_tool_calls == 2

    def test_multi_session_multiple_monitored_skills_interleaved(
        self, tmp_path: Path
    ) -> None:
        """Verify multi-session accumulation across multiple distinct monitored skills."""
        proj = tmp_path / "multi_skill_proj"
        proj.mkdir()

        # Session 1: Turn 1 (triage-tool post=2), Turn 2 (customizing-tools post=1)
        (proj / "s1.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "prune-list now"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cmd1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cmd2"},
                            },
                        ]
                    },
                }
            )
            + "\n"
            + json.dumps({"type": "user", "message": {"content": "need pyo3 bindings"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cmd3"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Session 2: Turn 1 (customizing-tools post=3), Turn 2 (triage-tool post=0)
        (proj / "s2.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "pyo3 module setup"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c2"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c3"},
                            },
                        ]
                    },
                }
            )
            + "\n"
            + json.dumps({"type": "user", "message": {"content": "another prune-list"}})
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

        # Session 3: Turn 1 (triage-tool post=1), Turn 2 (customizing-tools missed=1, post=0)
        (proj / "s3.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "prune-list audit"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "audit_cmd"},
                            },
                        ]
                    },
                }
            )
            + "\n"
            + json.dumps({"type": "user", "message": {"content": "pyo3 docs read"}})
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "curl_docs"},
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
                name="customizing-tools", distinctive_strings=("pyo3",)
            ),
        }
        report = mine_skill_opportunities(projects_dir=tmp_path, skills=skills)

        st_triage = report.skills["triage-tool"]
        assert st_triage.opportunities == 3
        assert st_triage.invoked == 3
        assert st_triage.loaded_before_action == 3
        assert st_triage.missed_opportunities == 0
        assert st_triage.post_load_tool_calls == 3  # 2 + 0 + 1 == 3

        st_custom = report.skills["customizing-tools"]
        assert st_custom.opportunities == 3
        assert st_custom.invoked == 2
        assert st_custom.loaded_before_action == 2
        assert st_custom.missed_opportunities == 1
        assert st_custom.post_load_tool_calls == 4  # 1 + 3 + 0 == 4

    def test_multi_session_corrupted_files_graceful_handling(
        self, tmp_path: Path
    ) -> None:
        """Verify invalid/corrupted files do not halt or break multi-session accumulation."""
        proj = tmp_path / "corrupt_proj"
        proj.mkdir()

        # Valid session 1 (post=2)
        (proj / "s1.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c2"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        # Corrupted / malformed files
        (proj / "s_empty.jsonl").write_text("", encoding="utf-8")
        (proj / "s_bad_json.jsonl").write_text(
            "NOT A JSON {{{ broken", encoding="utf-8"
        )

        # Valid session 2 (post=3)
        (proj / "s2.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c3"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c4"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c5"},
                            },
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
        assert stat.post_load_tool_calls == 5  # 2 + 3 == 5

    def test_cli_skill_coverage_multi_session_summary_table(
        self, tmp_path: Path
    ) -> None:
        """Verify cisternal skill-coverage CLI reports accumulated post-load counts in summary."""
        slug1 = tmp_path / "slug_1"
        slug1.mkdir()
        (slug1 / "s1.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c2"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        slug2 = tmp_path / "slug_2"
        slug2.mkdir()
        (slug2 / "s2.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "prune-list"}})
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
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "c3"},
                            },
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "cisternal.cli",
                "skill-coverage",
                "--manifest",
                ".praxia/manifest.toml",
                "--projects-dir",
                str(tmp_path),
                "--summary",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert "=== Cisternal Skill Opportunity Telemetry ===" in res.stdout
        assert "triage-tool" in res.stdout
        assert "opportunities=2" in res.stdout
        assert "invoked=2" in res.stdout
        assert "post_load_tool_calls=3" in res.stdout
