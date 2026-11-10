"""Adversarial stress-testing suite for Milestone M4 Iteration 2.

Authored by challenger_m4_it2_2 to stress-test:
1. In-process CLI execution across exit codes 0, 1, 2 and hermetic capture:
   - Exit code 0 on --situations, --json, --situations-out, --summary.
   - Exit code 1 on precision gate failure (< threshold).
   - Exit code 2 on invalid --baseline-ref in assets validate.
   - Isolation and hermetic capture: no stdout/stderr leaks across consecutive in-process runs.
   - System PATH independence: runs cleanly without external 'cisternal' or 'uv' in PATH.
2. Marketplace plugin discovery in src/cisternal/usage/coverage.py:
   - Nested <marketplace>/plugins/<name>/ layout.
   - Sidecar .claude-plugin/cisternal-source.json with relative manifest reference.
   - Sidecar with inline skills_meta.
   - Direct loose skills/<skill>/SKILL.md frontmatter parsing.
   - Priority fallback when manifest ref is invalid or JSON is corrupted.
   - Fallback flat directory layout <marketplace>/<name>/.
   - Filtering of .claude-plugin and plugins container directories.
   - Complete config sandbox immutability ($XDG_CONFIG_HOME remains untampered).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cisternal.cli import app
from cisternal.usage.coverage import load_monitored_skills


# ==============================================================================
# Suite 1: In-Process CLI Execution & Exit Code Conformance
# ==============================================================================


class TestInProcessCliExecutionAdversarial:
    """Stress-test cisternal in-process CLI execution across exit codes 0, 1, 2."""

    def test_cli_exit_0_situations_summary(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit code 0 with human-readable summary table."""
        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--threshold",
                    "0.80",
                    "--summary",
                ]
            )
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "=== Cisternal Skill Coverage Evaluation ===" in captured.out
        assert "Matched turns (n): 60" in captured.out
        assert "Gate Status: PASS" in captured.out
        assert "Precision (p_hat): 1.0000" in captured.out
        assert "export-trust:" in captured.out
        assert "triage-tool:" in captured.out

    def test_cli_exit_0_situations_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit code 0 with machine-readable JSON."""
        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--json",
                ]
            )
        assert exc.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_situations"] == 80
        assert data["matched_turns"] == 60
        assert data["true_positives"] == 60
        assert data["false_positives"] == 0
        assert data["precision"] == 1.0
        assert data["status"] == "PASS"
        assert "triage-tool" in data["per_skill_stats"]
        assert data["per_skill_stats"]["triage-tool"]["tp"] >= 1

    def test_cli_exit_0_situations_out_standalone_and_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit code 0 with --situations-out and --json simultaneously."""
        out_file = tmp_path / "deep" / "nested" / "evaluated_situations.jsonl"
        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--situations-out",
                    str(out_file),
                    "--json",
                ]
            )
        assert exc.value.code == 0
        assert out_file.is_file()
        lines = [
            json.loads(line)
            for line in out_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 80
        assert lines[0]["id"] == "sit_export_trust_01"
        assert "detected_skills" in lines[0]
        assert "expected_skills" in lines[0]

        # Ensure stdout was also valid JSON
        captured = capsys.readouterr()
        json_data = json.loads(captured.out)
        assert json_data["status"] == "PASS"

    def test_cli_exit_0_inconclusive_gate_does_not_fail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When matched turns n < 50, gate status is INCONCLUSIVE and exit code must be 0."""
        small_file = tmp_path / "small_situations.jsonl"
        with open(small_file, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(
                    json.dumps(
                        {
                            "id": f"small_{i}",
                            "prompt": "Run prune-list now",
                            "expected_skills": ["triage-tool"],
                        }
                    )
                    + "\n"
                )

        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    str(small_file),
                    "--threshold",
                    "0.80",
                ]
            )
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Gate Status: INCONCLUSIVE" in captured.out
        assert "Matched turns (n): 10" in captured.out

    def test_cli_exit_1_precision_gate_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit code 1 raised when precision falls below threshold (p_hat < 0.80)."""
        fail_file = tmp_path / "fail_situations.jsonl"
        with open(fail_file, "w", encoding="utf-8") as f:
            # 60 situations where trigger matches triage-tool but expected is something else
            for i in range(60):
                f.write(
                    json.dumps(
                        {
                            "id": f"fail_{i}",
                            "prompt": "Please run prune-list to check servers",
                            "expected_skills": ["unrelated-skill"],
                        }
                    )
                    + "\n"
                )

        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    str(fail_file),
                    "--threshold",
                    "0.80",
                ]
            )
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Gate Status: FAIL" in captured.out
        assert "Precision (p_hat): 0.0000" in captured.out

    def test_cli_exit_1_precision_gate_failure_with_json_and_situations_out(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When gate fails under --json and --situations-out, both artifacts are produced before exit 1."""
        fail_file = tmp_path / "fail_input.jsonl"
        out_file = tmp_path / "fail_output.jsonl"
        with open(fail_file, "w", encoding="utf-8") as f:
            for i in range(55):
                f.write(
                    json.dumps(
                        {
                            "id": f"fail_rec_{i}",
                            "prompt": "Run prune-list now",
                            "expected_skills": ["nonexistent-skill"],
                        }
                    )
                    + "\n"
                )

        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    str(fail_file),
                    "--threshold",
                    "0.80",
                    "--situations-out",
                    str(out_file),
                    "--json",
                ]
            )
        assert exc.value.code == 1
        assert out_file.is_file()
        records = [
            json.loads(line)
            for line in out_file.read_text(encoding="utf-8").splitlines()
        ]
        assert len(records) == 55

        captured = capsys.readouterr()
        doc = json.loads(captured.out)
        assert doc["status"] == "FAIL"
        assert doc["precision"] == 0.0

    def test_cli_exit_2_invalid_baseline_ref_variants(
        self, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        """assets validate --baseline-ref exits 2 on various invalid ref arguments."""
        invalid_refs = [
            "nonexistent_branch_xyz_12345",
            "..invalid..git..ref..",
            "HEAD~999999",
            "   ",
        ]
        for ref in invalid_refs:
            caplog.clear()
            _ = capsys.readouterr()
            with caplog.at_level(logging.ERROR, logger="cisternal.cli"):
                with pytest.raises(SystemExit) as exc:
                    app(
                        [
                            "assets",
                            "validate",
                            "--manifest",
                            ".praxia/manifest.toml",
                            "--baseline-ref",
                            ref,
                        ]
                    )
                assert exc.value.code == 2
            err_msg = caplog.text + capsys.readouterr().err
            assert "invalid baseline ref" in err_msg, (
                f"Expected error log for ref {ref!r}"
            )

    def test_cli_in_process_hermetic_isolation_no_leak_across_runs(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        """Sequential in-process executions must not leak stdout, stderr, or state."""
        fail_file = tmp_path / "fail.jsonl"
        with open(fail_file, "w", encoding="utf-8") as f:
            for i in range(50):
                f.write(
                    json.dumps(
                        {
                            "id": f"f_{i}",
                            "prompt": "prune-list",
                            "expected_skills": ["wrong"],
                        }
                    )
                    + "\n"
                )

        # Run 1: exit 0 summary
        with pytest.raises(SystemExit) as exc1:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--summary",
                ]
            )
        assert exc1.value.code == 0
        cap1 = capsys.readouterr()
        assert "Gate Status: PASS" in cap1.out
        assert cap1.err == ""

        # Run 2: exit 0 json
        with pytest.raises(SystemExit) as exc2:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--json",
                ]
            )
        assert exc2.value.code == 0
        cap2 = capsys.readouterr()
        # Verify NO leftover table from Run 1
        assert "=== Cisternal Skill Coverage Evaluation ===" not in cap2.out
        doc2 = json.loads(cap2.out)
        assert doc2["status"] == "PASS"

        # Run 3: exit 1 failure
        with pytest.raises(SystemExit) as exc3:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    str(fail_file),
                ]
            )
        assert exc3.value.code == 1
        cap3 = capsys.readouterr()
        assert "Gate Status: FAIL" in cap3.out

        # Run 4: exit 2 invalid baseline ref
        with caplog.at_level(logging.ERROR, logger="cisternal.cli"):
            with pytest.raises(SystemExit) as exc4:
                app(
                    [
                        "assets",
                        "validate",
                        "--manifest",
                        ".praxia/manifest.toml",
                        "--baseline-ref",
                        "invalid_ref_isolation_test",
                    ]
                )
            assert exc4.value.code == 2
        cap4 = capsys.readouterr()
        assert "invalid baseline ref" in (caplog.text + cap4.err)

        # Run 5: return to exit 0 clean
        with pytest.raises(SystemExit) as exc5:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--json",
                ]
            )
        assert exc5.value.code == 0
        cap5 = capsys.readouterr()
        doc5 = json.loads(cap5.out)
        assert doc5["status"] == "PASS"

    def test_cli_path_independence_no_external_cisternal_dependency(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """In-process app() execution must NOT depend on 'cisternal' or 'uv' in PATH."""
        # Restrict PATH to standard system binaries (/usr/bin:/bin)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        with pytest.raises(SystemExit) as exc:
            app(
                [
                    "skill-coverage",
                    "--manifest",
                    ".praxia/manifest.toml",
                    "--situations",
                    "tests/fixtures/situations/synthetic_situations.jsonl",
                    "--json",
                ]
            )
        assert exc.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "PASS"
        assert data["matched_turns"] == 60


# ==============================================================================
# Suite 2: Marketplace Plugin Discovery Stress Testing
# ==============================================================================


class TestMarketplaceDiscoveryAdversarial:
    """Stress-test marketplace plugin discovery, fallback layouts, and sandbox immutability."""

    def test_marketplace_nested_plugins_all_three_mechanisms(
        self, tmp_path: Path
    ) -> None:
        """Stress-test <marketplace>/plugins/<name>/ with all 3 acquisition mechanisms:

        - Plugin A: .claude-plugin/cisternal-source.json with relative manifest
        - Plugin B: .claude-plugin/cisternal-source.json with inline skills_meta
        - Plugin C: loose skills/<skill>/SKILL.md frontmatter parsing
        """
        m_root = tmp_path / "marketplace_nested"
        plugins_dir = m_root / "plugins"

        # Plugin A: Manifest reference
        p_a = plugins_dir / "plugin_manifest_ref"
        p_a_meta = p_a / ".claude-plugin"
        p_a_meta.mkdir(parents=True)
        manifest_rel = Path("custom_manifest.toml")
        (p_a_meta / "cisternal-source.json").write_text(
            json.dumps({"manifest": str(manifest_rel)}), encoding="utf-8"
        )
        skill_a_file = p_a / "skills" / "skill_a.md"
        skill_a_file.parent.mkdir(parents=True)
        skill_a_file.write_text(
            """---
name: skill-manifest-ref
description: Skill loaded via relative manifest
covers_families:
  - analytics
distinctive_strings:
  - manifest-ref-trigger
---
# Skill A
Content here.
""",
            encoding="utf-8",
        )
        (p_a / manifest_rel).write_text(
            f"""[plugin]
name = "plugin_manifest_ref"
version = "0.1.0"

[[plugin.skills]]
name = "skill-manifest-ref"
path = "{skill_a_file}"
""",
            encoding="utf-8",
        )

        # Plugin B: Inline skills_meta
        p_b = plugins_dir / "plugin_inline_meta"
        p_b_meta = p_b / ".claude-plugin"
        p_b_meta.mkdir(parents=True)
        (p_b_meta / "cisternal-source.json").write_text(
            json.dumps(
                {
                    "skills_meta": {
                        "skill-inline-monitored": {
                            "covers_families": ["database"],
                            "distinctive_strings": [
                                "inline-db-trigger",
                                "query-engine",
                            ],
                        },
                        "skill-inline-unmonitored": {
                            "covers_families": [],
                            "distinctive_strings": [],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        # Plugin C: Loose SKILL.md
        p_c = plugins_dir / "plugin_loose_skills"
        s_c_monitored = p_c / "skills" / "skill-loose-monitored"
        s_c_monitored.mkdir(parents=True)
        (s_c_monitored / "SKILL.md").write_text(
            """---
name: skill-loose-monitored
description: Loose skill with distinctive strings
covers_families:
  - monitoring
distinctive_strings:
  - loose-skill-trigger
---
## When to Use
Trigger details.
""",
            encoding="utf-8",
        )
        s_c_unmonitored = p_c / "skills" / "skill-loose-unmonitored"
        s_c_unmonitored.mkdir(parents=True)
        (s_c_unmonitored / "SKILL.md").write_text(
            """---
name: skill-loose-unmonitored
description: Loose skill lacking distinctive strings
---
## When to Use
Trigger details.
""",
            encoding="utf-8",
        )

        monitored, unmonitored = load_monitored_skills(marketplace_dir=m_root)

        # Assert monitored skills from all 3 plugins
        assert "skill-manifest-ref" in monitored
        assert monitored["skill-manifest-ref"].distinctive_strings == (
            "manifest-ref-trigger",
        )
        assert monitored["skill-manifest-ref"].covers_families == ("analytics",)

        assert "skill-inline-monitored" in monitored
        assert monitored["skill-inline-monitored"].distinctive_strings == (
            "inline-db-trigger",
            "query-engine",
        )
        assert monitored["skill-inline-monitored"].covers_families == ("database",)

        assert "skill-loose-monitored" in monitored
        assert monitored["skill-loose-monitored"].distinctive_strings == (
            "loose-skill-trigger",
        )
        assert monitored["skill-loose-monitored"].covers_families == ("monitoring",)

        # Assert unmonitored skills from plugins B and C
        unmon_map = {u.name: u for u in unmonitored}
        assert "skill-inline-unmonitored" in unmon_map
        assert (
            unmon_map["skill-inline-unmonitored"].reason
            == "missing distinctive_strings"
        )
        assert "skill-loose-unmonitored" in unmon_map
        assert (
            unmon_map["skill-loose-unmonitored"].reason == "missing distinctive_strings"
        )

    def test_marketplace_fallback_priority_on_broken_sidecar(
        self, tmp_path: Path
    ) -> None:
        """When cisternal-source.json has broken manifest or malformed JSON, fall back to loose SKILL.md."""
        m_root = tmp_path / "marketplace_fallback_broken"
        plugins_dir = m_root / "plugins"

        # Plugin with nonexistent manifest reference, but valid loose skill
        p1 = plugins_dir / "plugin_broken_manifest_ref"
        p1_meta = p1 / ".claude-plugin"
        p1_meta.mkdir(parents=True)
        (p1_meta / "cisternal-source.json").write_text(
            json.dumps({"manifest": "nonexistent_manifest.toml"}), encoding="utf-8"
        )
        p1_skill = p1 / "skills" / "recovered-skill-1"
        p1_skill.mkdir(parents=True)
        (p1_skill / "SKILL.md").write_text(
            """---
name: recovered-skill-1
distinctive_strings:
  - recovered-trigger-1
---
# Recovered
""",
            encoding="utf-8",
        )

        # Plugin with malformed (corrupt) JSON in cisternal-source.json
        p2 = plugins_dir / "plugin_corrupt_json"
        p2_meta = p2 / ".claude-plugin"
        p2_meta.mkdir(parents=True)
        (p2_meta / "cisternal-source.json").write_text(
            "{ corrupt json :: invalid syntax }}}", encoding="utf-8"
        )
        p2_skill = p2 / "skills" / "recovered-skill-2"
        p2_skill.mkdir(parents=True)
        (p2_skill / "SKILL.md").write_text(
            """---
name: recovered-skill-2
distinctive_strings:
  - recovered-trigger-2
---
# Recovered 2
""",
            encoding="utf-8",
        )

        monitored, _ = load_monitored_skills(marketplace_dir=m_root)
        assert "recovered-skill-1" in monitored
        assert monitored["recovered-skill-1"].distinctive_strings == (
            "recovered-trigger-1",
        )
        assert "recovered-skill-2" in monitored
        assert monitored["recovered-skill-2"].distinctive_strings == (
            "recovered-trigger-2",
        )

    def test_marketplace_fallback_flat_directory_structure(
        self, tmp_path: Path
    ) -> None:
        """When plugins/ subdir is absent, fall back to <marketplace>/<plugin_name>/."""
        m_root = tmp_path / "flat_marketplace"
        p_flat = m_root / "direct_plugin"
        s_flat = p_flat / "skills" / "flat-discovered-skill"
        s_flat.mkdir(parents=True)
        (s_flat / "SKILL.md").write_text(
            """---
name: flat-discovered-skill
distinctive_strings:
  - flat-discovered-trigger
---
# Flat Discovered
""",
            encoding="utf-8",
        )

        monitored, _ = load_monitored_skills(marketplace_dir=m_root)
        assert "flat-discovered-skill" in monitored
        assert monitored["flat-discovered-skill"].distinctive_strings == (
            "flat-discovered-trigger",
        )

    def test_marketplace_container_directory_and_file_filtering(
        self, tmp_path: Path
    ) -> None:
        """Container directories (.claude-plugin, plugins) and files must be filtered out."""
        m_root = tmp_path / "marketplace_containers"
        plugins_dir = m_root / "plugins"
        plugins_dir.mkdir(parents=True)

        # Subdirectory named '.claude-plugin' inside plugins/
        container_meta = plugins_dir / ".claude-plugin"
        container_meta.mkdir()
        (container_meta / "SKILL.md").write_text("---", encoding="utf-8")

        # Subdirectory named 'plugins' inside plugins/
        nested_plugins = plugins_dir / "plugins"
        nested_plugins.mkdir()

        # Non-directory files in plugins/
        (plugins_dir / "README.md").write_text(
            "Marketplace documentation", encoding="utf-8"
        )
        (plugins_dir / ".DS_Store").write_text("binary garbage", encoding="utf-8")

        # A valid plugin beside them
        valid_p = plugins_dir / "valid_plugin"
        v_skill = valid_p / "skills" / "valid-skill"
        v_skill.mkdir(parents=True)
        (v_skill / "SKILL.md").write_text(
            """---
name: valid-skill
distinctive_strings:
  - valid-trigger
---
# Valid
""",
            encoding="utf-8",
        )

        monitored, unmonitored = load_monitored_skills(marketplace_dir=m_root)
        assert "valid-skill" in monitored
        # Zero skills extracted from .claude-plugin, plugins, or README.md
        for name in list(monitored.keys()) + [u.name for u in unmonitored]:
            assert name not in {".claude-plugin", "plugins", "README.md", ".DS_Store"}

    def test_marketplace_unconfigured_creates_zero_config_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running load_monitored_skills with unconfigured marketplace must NEVER create config files."""
        fake_xdg_config = tmp_path / "xdg_config_immutability_test"
        fake_xdg_config.mkdir()

        monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_xdg_config))
        monkeypatch.delenv("CISTERNAL_PLUGIN_MARKETPLACE", raising=False)

        # Test with nonexistent directory
        monitored1, _ = load_monitored_skills(marketplace_dir=tmp_path / "nonexistent")
        assert len(monitored1) >= 1  # default manifest skills
        assert list(fake_xdg_config.rglob("*")) == []

        # Test with None (relying purely on marketplace_root_source unconfigured default)
        monitored2, _ = load_monitored_skills(marketplace_dir=None)
        assert len(monitored2) >= 1
        assert list(fake_xdg_config.rglob("*")) == []
