"""Tests for mode-state TOML parsing, 5-layer resolution, and 'cisternal shadow check' (AC-3).

Verifies:
- 5-layer resolution hierarchy (CLI arg > env var > pyproject.toml > user config > off).
- Malformed TOML fails loudly with exit code 3.
- Dynamic enforcer import (<file_path>::<symbol_name> and module fallback).
- Gate Check Negative Control 4: Multi-failure non-short-circuiting accumulating into blocking_reasons.
- Gate Check Positive Control 5: All criteria met produces promotion_permitted: true and exit code 0.
- Empty telemetry refuses with exit code 2.
- CLI check text and JSON output formats.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cisternal.cli import app
from cisternal.shadow.mode_state import (
    GateCheckError,
    check_mode_state,
    load_mode_state,
)
from cisternal.shadow.resolution import (
    ResolutionError,
    resolve_mode_state_dir,
)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_5_layer_resolution_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """5-layer hierarchy: CLI > Env > pyproject.toml > User config > Off."""
    cli_dir = tmp_path / "layer1_cli"
    cli_dir.mkdir()
    env_dir = tmp_path / "layer2_env"
    env_dir.mkdir()
    pyproj_dir = tmp_path / "layer3_pyproj"
    pyproj_dir.mkdir()
    user_dir = tmp_path / "layer4_user"
    user_dir.mkdir()

    # Create dummy pyproject.toml
    worktree = tmp_path / "repo"
    worktree.mkdir()
    pyproject = worktree / "pyproject.toml"
    pyproject.write_text(
        f'[tool.cisternal.shadow]\nmode_state_dir = "{pyproj_dir}"\n'
        f'[tool.cisternal.telemetry]\nlog_dir = "{pyproj_dir}"\n'
    )

    # Create dummy user config
    xdg_config = tmp_path / "config"
    xdg_config.mkdir()
    cist_config = xdg_config / "cisternal" / "config.toml"
    cist_config.parent.mkdir(parents=True)
    cist_config.write_text(
        f'[shadow]\nmode_state_dir = "{user_dir}"\n'
        f'[telemetry]\nlog_dir = "{user_dir}"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))

    # Layer 5: Fallback off when everything is unset
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.delenv("CISTERNAL_MODE_STATE_DIR", raising=False)
    monkeypatch.delenv("CISTERNAL_TELEMETRY_LOG_DIR", raising=False)
    monkeypatch.delenv("CISTERNAL_LOG_DIR", raising=False)
    # With empty repo and non-existent user config
    with pytest.raises(ResolutionError) as exc_info:
        resolve_mode_state_dir(cli_arg=None, repo_root=empty_dir, user_config_file=empty_dir / "nonexistent.toml")
    assert "Layer 5 (off)" in str(exc_info.value)

    # Layer 4: User config wins when layers 1-3 absent
    res_l4 = resolve_mode_state_dir(cli_arg=None, repo_root=None, user_config_file=cist_config)
    assert res_l4.path == user_dir
    assert "user config" in res_l4.provenance

    # Layer 3: pyproject.toml wins over user config
    res_l3 = resolve_mode_state_dir(cli_arg=None, repo_root=worktree, user_config_file=cist_config)
    assert res_l3.path == pyproj_dir
    assert "pyproject.toml" in res_l3.provenance

    # Layer 2: Env var wins over pyproject.toml
    monkeypatch.setenv("CISTERNAL_MODE_STATE_DIR", str(env_dir))
    res_l2 = resolve_mode_state_dir(cli_arg=None, repo_root=worktree, user_config_file=cist_config)
    assert res_l2.path == env_dir
    assert "environment variable" in res_l2.provenance

    # Env var empty string or "none" disables Layer 2
    monkeypatch.setenv("CISTERNAL_MODE_STATE_DIR", "none")
    res_l2_none = resolve_mode_state_dir(cli_arg=None, repo_root=worktree, user_config_file=cist_config)
    assert res_l2_none.path == pyproj_dir

    # Layer 1: CLI arg wins over all
    res_l1 = resolve_mode_state_dir(cli_arg=cli_dir, repo_root=worktree, user_config_file=cist_config)
    assert res_l1.path == cli_dir
    assert "CLI argument" in res_l1.provenance


def test_malformed_toml_fails_loudly_exit_3(tmp_path: Path) -> None:
    """Malformed TOML fails immediately with exit code 3."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text("[feature\nname = unquoted_invalid_syntax = 123")

    with pytest.raises(GateCheckError) as exc_info:
        load_mode_state(bad_toml)
    assert exc_info.value.exit_code == 3

    # Check CLI exit code 3
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "check", str(bad_toml)])
    assert exit_info.value.code == 3


def test_enforcer_symbol_resolution(tmp_path: Path) -> None:
    """Enforcer symbol loads from repo file or flags unimportable."""
    enforcer_file = tmp_path / "enforcer.py"
    enforcer_file.write_text("def my_audit():\n    return True\n")

    # Valid symbol
    from cisternal.shadow.mode_state import resolve_enforcer_symbol

    fn = resolve_enforcer_symbol(f"{enforcer_file}::my_audit", repo_root=tmp_path)
    assert callable(fn)
    assert fn() is True

    # Missing symbol
    fn_missing = resolve_enforcer_symbol("tests/non_existent.py::my_audit", repo_root=tmp_path)
    assert fn_missing is None


def test_gate_check_negative_control_non_short_circuiting(tmp_path: Path) -> None:
    """Negative Control 4: Multi-failure accumulates without short-circuiting (exit code 1)."""
    mode_dir = tmp_path / "modes"
    mode_dir.mkdir()
    toml_path = mode_dir / "test_neg.toml"
    toml_path.write_text("""
[feature]
name = "test_neg"
description = "Negative control feature"
version = "0.1.0"

[ladder]
current_stage = "shadow"

[shadow]
traffic_fraction = 1.0
writes_isolated = true
writes_isolated_enforced_by = "tests/does_not_exist.py::symbol"

[scoring]
positive_label = true

[promotion]
target_stage = "advisory"
min_verdicts = 10
min_labels = 15
allowed_label_sources = ["frozen_gold", "owner_confirmed", "at_work"]
min_precision = 0.85
min_precision_lower_bound = 0.70
min_recall = 0.80
min_recall_lower_bound = 0.65
max_fp_rate = 0.05
isolation_violations_max = 0
threshold_basis = "negative control"
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.neg.jsonl"

    # Actual metrics:
    # 10 labeled items: 6 TP, 2 FP, 2 FN, 0 TN -> Precision = 6/8 = 0.75, Recall = 6/8 = 0.75
    records: list[dict[str, Any]] = []
    idx = 0
    for _ in range(6):  # TP
        records.append({"name": "shadow.verdict", "ts": float(idx), "fields": {"feature": "test_neg", "subject_key": f"s:{idx}", "verdict": True}})
        records.append({"name": "shadow.label", "ts": float(idx), "fields": {"feature": "test_neg", "subject_key": f"s:{idx}", "label": True, "label_source": "frozen_gold"}})
        idx += 1
    for _ in range(2):  # FP
        records.append({"name": "shadow.verdict", "ts": float(idx), "fields": {"feature": "test_neg", "subject_key": f"s:{idx}", "verdict": True}})
        records.append({"name": "shadow.label", "ts": float(idx), "fields": {"feature": "test_neg", "subject_key": f"s:{idx}", "label": False, "label_source": "frozen_gold"}})
        idx += 1
    for _ in range(2):  # FN
        records.append({"name": "shadow.verdict", "ts": float(idx), "fields": {"feature": "test_neg", "subject_key": f"s:{idx}", "verdict": False}})
        records.append({"name": "shadow.label", "ts": float(idx), "fields": {"feature": "test_neg", "subject_key": f"s:{idx}", "label": True, "label_source": "frozen_gold"}})
        idx += 1
    _write_jsonl(log_file, records)

    res = check_mode_state(toml_path, records_dir=records_dir)
    assert res.promotion_permitted is False
    assert res.exit_code == 1

    # Check that failures accumulated non-short-circuiting
    reasons_str = " ".join(res.blocking_reasons)
    assert "enforcer_unimportable:tests/does_not_exist.py::symbol" in reasons_str
    assert "insufficient_labels:10/15" in reasons_str
    assert "precision_deficit" in reasons_str
    assert "precision_lower_bound_deficit" in reasons_str


def test_gate_check_positive_control_all_met(tmp_path: Path) -> None:
    """Positive Control 5: All criteria met produces promotion_permitted: true and exit code 0."""
    enforcer_file = tmp_path / "enforcer.py"
    enforcer_file.write_text("def test_iso(): return True\n")

    mode_dir = tmp_path / "modes"
    mode_dir.mkdir()
    toml_path = mode_dir / "test_pos.toml"
    toml_path.write_text(f"""
[feature]
name = "test_pos"
description = "Positive control feature"
version = "0.1.0"

[ladder]
current_stage = "shadow"

[shadow]
traffic_fraction = 1.0
writes_isolated = true
writes_isolated_enforced_by = "{enforcer_file}::test_iso"

[scoring]
positive_label = true

[promotion]
target_stage = "advisory"
min_verdicts = 50
min_labels = 50
allowed_label_sources = ["frozen_gold"]
min_precision = 0.80
min_precision_lower_bound = 0.70
min_recall = 0.80
min_recall_lower_bound = 0.70
max_fp_rate = 0.15
isolation_violations_max = 0
threshold_basis = "positive control"
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.pos.jsonl"

    # Synthetic: 45 TP, 5 FP, 5 FN, 45 TN (N=100)
    # Precision: 45/50 = 0.90 [Wilson 95% CI: 0.787 .. 0.956]
    # Recall: 45/50 = 0.90 [Wilson 95% CI: 0.787 .. 0.956]
    # Base rate: 50/100 = 0.50
    # FP rate: 5/50 = 0.10 <= 0.15
    records: list[dict[str, Any]] = []
    idx = 0
    def add_cases(cnt: int, pred: bool, lbl: bool) -> None:
        nonlocal idx
        for _ in range(cnt):
            records.append({"name": "shadow.verdict", "ts": float(idx), "fields": {"feature": "test_pos", "subject_key": f"s:{idx}", "verdict": pred}})
            records.append({"name": "shadow.label", "ts": float(idx), "fields": {"feature": "test_pos", "subject_key": f"s:{idx}", "label": lbl, "label_source": "frozen_gold"}})
            idx += 1

    add_cases(45, True, True)
    add_cases(5, True, False)
    add_cases(5, False, True)
    add_cases(45, False, False)

    # Add a passing shadow.isolation event
    records.append({
        "name": "shadow.isolation",
        "ts": 1000.0,
        "fields": {
            "feature": "test_pos",
            "writes_isolated": True,
            "leaked_paths": [],
            "enforced_by": f"{enforcer_file}::test_iso",
        },
    })
    _write_jsonl(log_file, records)

    res = check_mode_state(toml_path, records_dir=records_dir, repo_root=tmp_path)
    assert res.promotion_permitted is True
    assert res.blocking_reasons == []
    assert res.exit_code == 0


def test_refusal_on_empty_telemetry_exit_2(tmp_path: Path) -> None:
    """Exit code 2 when 0 matching telemetry exists."""
    toml_path = tmp_path / "feat.toml"
    toml_path.write_text("""
[feature]
name = "empty_feat"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
min_verdicts = 10
min_labels = 10
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        app(["shadow", "check", str(toml_path), "--records-dir", str(records_dir)])
    assert exc_info.value.code == 2


def test_cli_check_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI check --json matches schema §3.3.2."""
    enforcer_file = tmp_path / "enf.py"
    enforcer_file.write_text("def audit(): return True\n")

    toml_path = tmp_path / "feat.toml"
    toml_path.write_text(f"""
[feature]
name = "cli_check_feat"
version = "0.1.0"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
writes_isolated_enforced_by = "{enforcer_file}::audit"
[scoring]
positive_label = true
[promotion]
target_stage = "advisory"
min_verdicts = 5
min_labels = 5
min_precision = 0.70
allowed_label_sources = ["frozen_gold"]
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    recs: list[dict[str, Any]] = []
    # 5 TP cases
    for i in range(5):
        recs.append({"name": "shadow.verdict", "ts": float(i), "fields": {"feature": "cli_check_feat", "subject_key": f"s:{i}", "verdict": True}})
        recs.append({"name": "shadow.label", "ts": float(i), "fields": {"feature": "cli_check_feat", "subject_key": f"s:{i}", "label": True, "label_source": "frozen_gold"}})
    # 5 TN cases so base rate = 5/10 = 0.50, and precision CI lower (0.5655) > 0.50
    for i in range(5, 10):
        recs.append({"name": "shadow.verdict", "ts": float(i), "fields": {"feature": "cli_check_feat", "subject_key": f"s:{i}", "verdict": False}})
        recs.append({"name": "shadow.label", "ts": float(i), "fields": {"feature": "cli_check_feat", "subject_key": f"s:{i}", "label": False, "label_source": "frozen_gold"}})
    _write_jsonl(log_file, recs)

    with pytest.raises(SystemExit) as exc_info:
        app(["shadow", "check", str(toml_path), "--records-dir", str(records_dir), "--json"])
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["feature"] == "cli_check_feat"
    assert data["current_stage"] == "shadow"
    assert data["target_stage"] == "advisory"
    assert data["promotion_permitted"] is True
    assert data["blocking_reasons"] == []
    assert "metrics" in data
    assert data["metrics"]["tp"] == 5
    assert data["metrics"]["precision"] == 1.0
