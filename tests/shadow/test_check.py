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
    resolve_enforcer_symbol,
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

    # Env var "none" (or empty) disables resolution entirely: fail closed, exit 3,
    # no fall-through to pyproject.toml (spec §3.7)
    monkeypatch.setenv("CISTERNAL_MODE_STATE_DIR", "none")
    with pytest.raises(ResolutionError) as disabled_exc:
        resolve_mode_state_dir(cli_arg=None, repo_root=worktree, user_config_file=cist_config)
    assert disabled_exc.value.exit_code == 3

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
    toml_path = tmp_path / "feat.toml"
    toml_path.write_text("""
[feature]
name = "cli_check_feat"
version = "0.1.0"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
writes_isolated_enforced_by = "cisternal.shadow.isolation::prove_isolation"
[scoring]
positive_label = true
[promotion]
target_stage = "advisory"
min_verdicts = 5
min_labels = 5
min_precision = 0.70
allowed_label_sources = ["frozen_gold"]
threshold_basis = "pre-registered calibration"
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    recs: list[dict[str, Any]] = []
    # Passing isolation evidence (B1): fail-closed gate needs a clean shadow.isolation event.
    recs.append({"name": "shadow.isolation", "ts": 0.5, "fields": {
        "feature": "cli_check_feat", "writes_isolated": True, "leaked_paths": [],
        "enforced_by": "cisternal.shadow.isolation::prove_isolation"}})
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


def test_check_zero_verdicts_refusal_exit_2(tmp_path: Path) -> None:
    """Finding 1 (REV1-01 / REV2-01): 0 verdicts with 5 labels raises Exit 2 refusal."""
    toml_path = tmp_path / "zero_v.toml"
    toml_path.write_text("""
[feature]
name = "zero_v_feat"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
threshold_basis = "pre-registered calibration"
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    recs = [
        {
            "name": "shadow.label",
            "ts": float(i),
            "fields": {
                "feature": "zero_v_feat",
                "subject_key": f"s:{i}",
                "label": True,
                "label_source": "frozen_gold",
            },
        }
        for i in range(5)
    ]
    _write_jsonl(log_file, recs)

    with pytest.raises(GateCheckError) as exc_info:
        check_mode_state(toml_path, records_dir=records_dir)
    assert exc_info.value.exit_code == 2
    assert "0 matching verdicts" in str(exc_info.value)

    # CLI check also exits with code 2
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "check", str(toml_path), "--records-dir", str(records_dir)])
    assert exit_info.value.code == 2


def test_check_base_rate_safety_undefined_precision_blocks(tmp_path: Path) -> None:
    """Finding 2 (REV1-02): Undefined precision blocks promotion via base rate safety."""
    toml_path = tmp_path / "always_neg.toml"
    toml_path.write_text("""
[feature]
name = "always_neg_feat"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
min_verdicts = 5
min_labels = 5
threshold_basis = "pre-registered calibration"
""")

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    # Candidate predicts False for all 5 subjects, but labels are True (TP=0, FP=0)
    recs = []
    for i in range(5):
        recs.append({
            "name": "shadow.verdict",
            "ts": float(i),
            "fields": {
                "feature": "always_neg_feat",
                "subject_key": f"s:{i}",
                "verdict": False,
            },
        })
        recs.append({
            "name": "shadow.label",
            "ts": float(i),
            "fields": {
                "feature": "always_neg_feat",
                "subject_key": f"s:{i}",
                "label": True,
                "label_source": "frozen_gold",
            },
        })
    _write_jsonl(log_file, recs)

    res = check_mode_state(toml_path, records_dir=records_dir)
    assert res.promotion_permitted is False
    assert res.exit_code == 1
    assert "precision_lower_bound_below_base_rate" in res.blocking_reasons

    # Also verify disjoint subject keys
    disjoint_dir = tmp_path / "disjoint_logs"
    disjoint_dir.mkdir()
    d_recs = [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "always_neg_feat", "subject_key": "v:1", "verdict": True}},
        {"name": "shadow.verdict", "ts": 2.0, "fields": {"feature": "always_neg_feat", "subject_key": "v:2", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "always_neg_feat", "subject_key": "l:1", "label": True, "label_source": "frozen_gold"}},
        {"name": "shadow.label", "ts": 2.0, "fields": {"feature": "always_neg_feat", "subject_key": "l:2", "label": True, "label_source": "frozen_gold"}},
    ]
    _write_jsonl(disjoint_dir / "events.jsonl", d_recs)
    res_disjoint = check_mode_state(toml_path, records_dir=disjoint_dir)
    assert res_disjoint.promotion_permitted is False
    assert "precision_lower_bound_below_base_rate" in res_disjoint.blocking_reasons


def test_check_mode_state_toml_missing_required_keys_exit_3(tmp_path: Path) -> None:
    """Finding 5 (REV1-03): Missing required keys in mode-state TOML raises exit code 3."""
    bad_toml = tmp_path / "missing_name.toml"
    bad_toml.write_text("""
[feature]
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
threshold_basis = "test"
""")
    with pytest.raises(GateCheckError) as exc_info:
        load_mode_state(bad_toml)
    assert exc_info.value.exit_code == 3
    assert "[feature] name" in str(exc_info.value)

    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "check", str(bad_toml)])
    assert exit_info.value.code == 3


def test_check_missing_threshold_basis(tmp_path: Path) -> None:
    """Finding 8 (REV2-07): Missing threshold_basis adds blocking reason."""
    enforcer = tmp_path / "audit.py"
    enforcer.write_text("def run(): return True\n")
    toml_path = tmp_path / "no_thresh.toml"
    toml_path.write_text(f"""
[feature]
name = "no_thresh_feat"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
writes_isolated_enforced_by = "{enforcer}::run"
[promotion]
target_stage = "advisory"
min_verdicts = 1
min_labels = 1
""")
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "no_thresh_feat", "subject_key": "s:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "no_thresh_feat", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])
    res = check_mode_state(toml_path, records_dir=records_dir)
    assert res.promotion_permitted is False
    assert "missing_threshold_basis" in res.blocking_reasons


def test_check_labels_file_and_unpermitted_label_sources(tmp_path: Path) -> None:
    """Finding 8 (REV2-07): --labels-file with disallowed sources records unpermitted_label_sources_present."""
    enforcer = tmp_path / "audit.py"
    enforcer.write_text("def run(): return True\n")
    toml_path = tmp_path / "src_test.toml"
    toml_path.write_text(f"""
[feature]
name = "src_feat"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
writes_isolated_enforced_by = "{enforcer}::run"
[promotion]
target_stage = "advisory"
allowed_label_sources = ["frozen_gold"]
threshold_basis = "pre-registered calibration"
""")
    v_file = tmp_path / "verdicts.jsonl"
    _write_jsonl(v_file, [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "src_feat", "subject_key": "s:1", "verdict": True}},
    ])
    l_file = tmp_path / "labels.jsonl"
    _write_jsonl(l_file, [
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "src_feat", "subject_key": "s:1", "label": True, "label_source": "retrospective"}},
    ])

    res = check_mode_state(
        toml_path,
        verdicts_file=v_file,
        labels_file=l_file,
        confidence=0.95,
    )
    assert res.promotion_permitted is False
    assert any("unpermitted_label_sources_present:retrospective" in r for r in res.blocking_reasons)

    # CLI check with --labels-file and --verdicts-file and --confidence
    with pytest.raises(SystemExit) as exit_info:
        app([
            "shadow",
            "check",
            str(toml_path),
            "--verdicts-file",
            str(v_file),
            "--labels-file",
            str(l_file),
            "--confidence",
            "0.99",
        ])
    assert exit_info.value.code == 1


_PERMISSIVE_PROMO = """
[promotion]
target_stage = "advisory"
min_verdicts = 1
min_labels = 1
allowed_label_sources = ["frozen_gold"]
threshold_basis = "pre-registered calibration"
"""


def _pair_records(feature: str, n: int, *, source: str = "frozen_gold") -> list[dict[str, Any]]:
    """n clean pairs where verdict == label (TP/TN only)."""
    recs: list[dict[str, Any]] = []
    for i in range(n):
        val = i % 2 == 0
        recs.append({"name": "shadow.verdict", "ts": float(i), "fields": {
            "feature": feature, "subject_key": f"s:{i}", "verdict": val}})
        recs.append({"name": "shadow.label", "ts": float(i), "fields": {
            "feature": feature, "subject_key": f"s:{i}", "label": val, "label_source": source}})
    return recs


def test_b1_vacuous_isolation_gate_fails_closed(tmp_path: Path) -> None:
    """B1: writes_isolated=false, no enforcer, clean pairs -> blocked with all isolation reasons."""
    toml_path = tmp_path / "vac.toml"
    toml_path.write_text("""
[feature]
name = "vac"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = false
[promotion]
target_stage = "advisory"
min_verdicts = 100
min_labels = 100
allowed_label_sources = ["frozen_gold"]
threshold_basis = "pre-registered calibration"
""")
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", _pair_records("vac", 120))
    res = check_mode_state(toml_path, records_dir=records_dir)
    assert res.promotion_permitted is False
    assert "writes_isolated_declared_false" in res.blocking_reasons
    assert "enforcer_missing" in res.blocking_reasons
    assert "no_isolation_evidence" in res.blocking_reasons


def test_b1_isolation_evidence_required_even_with_enforcer(tmp_path: Path) -> None:
    """B1: declared-isolated with an enforcer but no shadow.isolation event is blocked."""
    toml_path = tmp_path / "noev.toml"
    toml_path.write_text("""
[feature]
name = "noev"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
writes_isolated_enforced_by = "cisternal.shadow.isolation::prove_isolation"
[promotion]
target_stage = "advisory"
min_verdicts = 1
min_labels = 1
allowed_label_sources = ["frozen_gold"]
threshold_basis = "pre-registered calibration"
""")
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", _pair_records("noev", 10))
    res = check_mode_state(toml_path, records_dir=records_dir)
    assert res.promotion_permitted is False
    assert res.blocking_reasons == ["no_isolation_evidence"]


_RAW_MODE: dict[str, Any] = {
    "feature": {"name": "raw"},
    "ladder": {"current_stage": "shadow"},
    "shadow": {
        "writes_isolated": True,
        "writes_isolated_enforced_by": "cisternal.shadow.isolation::prove_isolation",
    },
    "promotion": {"target_stage": "advisory", "threshold_basis": "pre-registered"},
}


@pytest.mark.parametrize(
    "promo_extra",
    [{"min_verdicts": "5"}, {"min_verdict": 5000}, {"allowed_label_sources": "frozen_gold"}],
)
def test_evaluate_gate_revalidates_raw_dict(tmp_path: Path, promo_extra: dict[str, Any]) -> None:
    """API callers passing a raw dict get the same B6/M2 checks as load_mode_state."""
    from cisternal.shadow.mode_state import evaluate_gate

    mode = json.loads(json.dumps(_RAW_MODE))
    mode["promotion"].update(promo_extra)
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", _pair_records("raw", 10))
    with pytest.raises(GateCheckError) as exc_info:
        evaluate_gate(mode, records_dir)
    assert exc_info.value.exit_code == 3


def test_isolation_evidence_must_come_from_configured_enforcer(tmp_path: Path) -> None:
    """A clean shadow.isolation event from a different enforcer is not evidence."""
    from cisternal.shadow.mode_state import evaluate_gate

    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    recs = _pair_records("raw", 10)
    recs.append({"name": "shadow.isolation", "ts": 99.0, "fields": {
        "feature": "raw", "writes_isolated": True, "leaked_paths": [],
        "enforced_by": "tests/other.py::unrelated"}})
    _write_jsonl(records_dir / "events.jsonl", recs)
    res = evaluate_gate(json.loads(json.dumps(_RAW_MODE)), records_dir)
    assert "no_isolation_evidence" in res.blocking_reasons


def test_non_callable_enforcer_is_unimportable(tmp_path: Path) -> None:
    assert resolve_enforcer_symbol("cisternal.shadow.scoring::PROVENANCE_RANKS", repo_root=tmp_path) is None


def test_typo_and_unknown_keys_fail_exit_3(tmp_path: Path) -> None:
    """B6: unknown keys/tables are a configuration error, never a silent pass."""
    base = """
[feature]
name = "typo"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
threshold_basis = "t"
"""
    for extra in ("min_verdict = 5000\n", "min_precison = 0.999\n"):
        p = tmp_path / "typo.toml"
        p.write_text(base + extra)
        with pytest.raises(GateCheckError) as exc_info:
            load_mode_state(p)
        assert exc_info.value.exit_code == 3
    p2 = tmp_path / "table.toml"
    p2.write_text(base + "\n[surprise]\nx = 1\n")
    with pytest.raises(GateCheckError) as exc_info2:
        load_mode_state(p2)
    assert exc_info2.value.exit_code == 3
    assert "surprise" in str(exc_info2.value)


def test_wrong_numeric_types_fail_exit_3(tmp_path: Path) -> None:
    """M2: type-checked numerics (string rate, bool count, out-of-range rate, negative count)."""
    base = """
[feature]
name = "types"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
threshold_basis = "t"
"""
    for extra in ('min_precision = "0.9"\n', "min_verdicts = true\n", "min_recall = 1.5\n", "min_labels = -1\n"):
        p = tmp_path / "types.toml"
        p.write_text(base + extra)
        with pytest.raises(GateCheckError) as exc_info:
            load_mode_state(p)
        assert exc_info.value.exit_code == 3, extra


def test_unknown_allowed_label_source_fails_exit_3(tmp_path: Path) -> None:
    """M2: allowed_label_sources must be a subset of the four known sources."""
    p = tmp_path / "src.toml"
    p.write_text("""
[feature]
name = "src"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
allowed_label_sources = ["owner_confirmed", "gut_feeling"]
threshold_basis = "t"
""")
    with pytest.raises(GateCheckError) as exc_info:
        load_mode_state(p)
    assert exc_info.value.exit_code == 3
    assert "gut_feeling" in str(exc_info.value)


def test_m1_disallowed_source_filtered_before_selection(tmp_path: Path) -> None:
    """M1: a disallowed frozen_gold label must not displace owner_confirmed when only owner_confirmed is allowed."""
    toml_path = tmp_path / "m1.toml"
    toml_path.write_text("""
[feature]
name = "m1"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
allowed_label_sources = ["owner_confirmed"]
threshold_basis = "t"
""")
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    recs: list[dict[str, Any]] = []
    for i in range(40):
        recs.append({"name": "shadow.verdict", "ts": float(i), "fields": {"feature": "m1", "subject_key": f"s:{i}", "verdict": True}})
        recs.append({"name": "shadow.label", "ts": float(i), "fields": {"feature": "m1", "subject_key": f"s:{i}", "label": True, "label_source": "owner_confirmed"}})
        recs.append({"name": "shadow.label", "ts": float(i), "fields": {"feature": "m1", "subject_key": f"s:{i}", "label": False, "label_source": "frozen_gold"}})
    _write_jsonl(records_dir / "events.jsonl", recs)
    res = check_mode_state(toml_path, records_dir=records_dir)
    assert res.metrics["labels_total"] == 40
    assert res.metrics["tp"] == 40


def test_m4_enforcer_outside_repo_root_rejected(tmp_path: Path) -> None:
    """M4: absolute paths outside the repo root and `..` escapes are rejected."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "outside.py").write_text("def audit(): return True\n")
    (repo / "inside.py").write_text("def audit(): return True\n")

    assert resolve_enforcer_symbol(f"{tmp_path / 'outside.py'}::audit", repo_root=repo) is None
    assert resolve_enforcer_symbol("../outside.py::audit", repo_root=repo) is None
    assert callable(resolve_enforcer_symbol("inside.py::audit", repo_root=repo))


def test_m4_module_name_unique_per_path(tmp_path: Path) -> None:
    """M4: two same-stem files in different directories load as distinct modules."""
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    (repo / "b").mkdir()
    (repo / "a" / "enf.py").write_text("def f(): return 'a'\n")
    (repo / "b" / "enf.py").write_text("def f(): return 'b'\n")
    fa = resolve_enforcer_symbol("a/enf.py::f", repo_root=repo)
    fb = resolve_enforcer_symbol("b/enf.py::f", repo_root=repo)
    assert fa is not None and fb is not None
    assert fa() == "a"
    assert fb() == "b"


def test_feature_version_filters_verdicts(tmp_path: Path) -> None:
    """[promotion] feature_version: verdicts of another version do not count."""
    toml_path = tmp_path / "fv.toml"
    toml_path.write_text("""
[feature]
name = "fv"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
[promotion]
target_stage = "advisory"
feature_version = "v2"
threshold_basis = "t"
""")
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "fv", "subject_key": "s:1", "verdict": True, "feature_version": "v1"}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "fv", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])
    with pytest.raises(GateCheckError) as exc_info:
        check_mode_state(toml_path, records_dir=records_dir)
    assert exc_info.value.exit_code == 2
    assert "0 matching verdicts" in str(exc_info.value)


def test_check_cli_prints_provenance_once_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """L3: check prints the log_dir provenance line to stderr exactly once."""
    toml_path = tmp_path / "prov.toml"
    toml_path.write_text("""
[feature]
name = "prov"
[ladder]
current_stage = "shadow"
[shadow]
writes_isolated = true
writes_isolated_enforced_by = "cisternal.shadow.isolation::prove_isolation"
[promotion]
target_stage = "advisory"
min_verdicts = 1
min_labels = 1
allowed_label_sources = ["frozen_gold"]
threshold_basis = "pre-registered calibration"
""")
    log_dir = tmp_path / "env_logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", _pair_records("prov", 4) + [
        {"name": "shadow.isolation", "ts": 0.5, "fields": {"feature": "prov", "writes_isolated": True, "leaked_paths": []}}])
    monkeypatch.setenv("CISTERNAL_TELEMETRY_LOG_DIR", str(log_dir))
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "check", str(toml_path)])
    assert exit_info.value.code in (0, 1)
    err = capsys.readouterr().err
    assert err.count("resolved log_dir from") == 1
