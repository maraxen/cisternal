"""Tests for cisternal.shadow.scoring and 'cisternal shadow score' CLI (AC-2).

Verifies:
- Scorer Negative Control 1: Zero labels causes refusal with exit code 2.
- Scorer Negative Control 2: Zero positives handled gracefully without ZeroDivisionError.
- Scorer Positive Control: Known confusion matrix (40 TP, 10 FP, 5 FN, 45 TN) with Wilson CI bounds.
- Subject key joining with latest-timestamp resolution for verdicts.
- Label provenance precedence (frozen_gold > owner_confirmed > at_work > retrospective).
- Multi-process JSONL log streaming from records directory.
- CLI text and JSON output formats.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cisternal.cli import app
from cisternal.shadow.scoring import (
    ScoringRefusalError,
    score_feature,
)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Helper to write records to JSONL file."""
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_scorer_negative_control_zero_labels_refuses(tmp_path: Path) -> None:
    """Negative Control 1: If 0 labels exist, refuse with exit code 2 and exact message."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    v_file = records_dir / "events.test.1.jsonl"
    _write_jsonl(
        v_file,
        [
            {
                "name": "shadow.verdict",
                "ts": 100.0,
                "fields": {
                    "feature": "feat_a",
                    "subject_key": "subj:1",
                    "verdict": True,
                },
            }
        ],
    )

    with pytest.raises(ScoringRefusalError) as exc_info:
        score_feature("feat_a", records_dir=records_dir)

    msg = str(exc_info.value)
    assert "REFUSAL: feature 'feat_a' has 0 matching labels. Scoring requires at least 1 labeled subject." in msg
    assert exc_info.value.exit_code == 2

    # Verify CLI exits with code 2
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "score", "feat_a", "--records-dir", str(records_dir)])
    assert exit_info.value.code == 2


def test_scorer_negative_control_zero_positives_division_by_zero(tmp_path: Path) -> None:
    """Negative Control 2: Zero positives (20 TN) yields null metrics without ZeroDivisionError."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.zero_pos.jsonl"

    records: list[dict[str, Any]] = []
    for i in range(20):
        s_key = f"neg:{i}"
        records.append({
            "name": "shadow.verdict",
            "ts": 100.0 + i,
            "fields": {
                "feature": "feat_zero_pos",
                "subject_key": s_key,
                "verdict": False,
            },
        })
        records.append({
            "name": "shadow.label",
            "ts": 100.0 + i,
            "fields": {
                "feature": "feat_zero_pos",
                "subject_key": s_key,
                "label": False,
                "label_source": "frozen_gold",
            },
        })
    _write_jsonl(log_file, records)

    res = score_feature("feat_zero_pos", records_dir=records_dir)
    assert res.tp == 0
    assert res.fp == 0
    assert res.fn == 0
    assert res.tn == 20
    assert res.base_rate == 0.0
    assert res.precision is None
    assert res.precision_ci_lower is None
    assert res.precision_ci_upper is None
    assert res.recall is None
    assert res.recall_ci_lower is None
    assert res.recall_ci_upper is None
    assert res.fp_rate == 0.0
    assert res.precision_exceeds_base_rate is None


def test_scorer_positive_control_known_matrix(tmp_path: Path) -> None:
    """Positive Control: 40 TP, 10 FP, 5 FN, 45 TN produces exact metrics and Wilson CI."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.synth.jsonl"

    records: list[dict[str, Any]] = []
    idx = 0

    def add_cases(count: int, pred: bool, label: bool) -> None:
        nonlocal idx
        for _ in range(count):
            s_key = f"item:{idx}"
            records.append({
                "name": "shadow.verdict",
                "ts": float(idx),
                "fields": {
                    "feature": "synth_feature",
                    "subject_key": s_key,
                    "verdict": pred,
                },
            })
            records.append({
                "name": "shadow.label",
                "ts": float(idx),
                "fields": {
                    "feature": "synth_feature",
                    "subject_key": s_key,
                    "label": label,
                    "label_source": "frozen_gold",
                },
            })
            idx += 1

    add_cases(40, True, True)    # TP
    add_cases(10, True, False)   # FP
    add_cases(5, False, True)    # FN
    add_cases(45, False, False)  # TN

    _write_jsonl(log_file, records)

    res = score_feature("synth_feature", records_dir=records_dir, confidence=0.95)
    assert res.tp == 40
    assert res.fp == 10
    assert res.fn == 5
    assert res.tn == 45
    assert res.verdicts_total == 100
    assert res.labels_total == 100
    assert res.base_rate == pytest.approx(0.45, abs=1e-4)
    assert res.precision == pytest.approx(0.80, abs=1e-4)
    assert res.precision_ci_lower is not None and 0.66 < res.precision_ci_lower < 0.68
    assert res.precision_ci_upper is not None and 0.88 < res.precision_ci_upper < 0.90
    assert res.recall == pytest.approx(0.8889, abs=1e-3)
    assert res.recall_ci_lower is not None and 0.76 < res.recall_ci_lower < 0.77
    assert res.recall_ci_upper is not None and 0.94 < res.recall_ci_upper < 0.96
    assert res.precision_exceeds_base_rate is True


def test_join_subject_key_latest_timestamp(tmp_path: Path) -> None:
    """Latest timestamp wins when duplicate verdicts exist for a subject_key."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.timestamps.jsonl"

    records = [
        # Earlier verdict: True (ts=10.0)
        {
            "name": "shadow.verdict",
            "ts": 10.0,
            "fields": {"feature": "ts_feat", "subject_key": "subj:dup", "verdict": True},
        },
        # Later verdict: False (ts=20.0)
        {
            "name": "shadow.verdict",
            "ts": 20.0,
            "fields": {"feature": "ts_feat", "subject_key": "subj:dup", "verdict": False},
        },
        # Label: False
        {
            "name": "shadow.label",
            "ts": 15.0,
            "fields": {"feature": "ts_feat", "subject_key": "subj:dup", "label": False, "label_source": "at_work"},
        },
    ]
    _write_jsonl(log_file, records)

    res = score_feature("ts_feat", records_dir=records_dir)
    # Latest verdict False + label False -> TN
    assert res.tn == 1
    assert res.fp == 0
    assert res.tp == 0


def test_label_provenance_precedence(tmp_path: Path) -> None:
    """Provenance hierarchy: frozen_gold > owner_confirmed > at_work > retrospective."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.prov.jsonl"

    records = [
        {
            "name": "shadow.verdict",
            "ts": 10.0,
            "fields": {"feature": "prov_feat", "subject_key": "subj:1", "verdict": True},
        },
        # Earlier frozen_gold: True (ts=5.0)
        {
            "name": "shadow.label",
            "ts": 5.0,
            "fields": {"feature": "prov_feat", "subject_key": "subj:1", "label": True, "label_source": "frozen_gold"},
        },
        # Later at_work: False (ts=15.0)
        {
            "name": "shadow.label",
            "ts": 15.0,
            "fields": {"feature": "prov_feat", "subject_key": "subj:1", "label": False, "label_source": "at_work"},
        },
    ]
    _write_jsonl(log_file, records)

    res = score_feature("prov_feat", records_dir=records_dir)
    # frozen_gold overrides at_work even though earlier ts -> True label + True verdict -> TP
    assert res.tp == 1
    assert res.fp == 0


def test_multi_process_file_streaming(tmp_path: Path) -> None:
    """Aggregates multiple events.*.jsonl files in records-dir."""
    records_dir = tmp_path / "multi_logs"
    records_dir.mkdir()

    f1 = records_dir / "events.node1.101.jsonl"
    _write_jsonl(f1, [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "multi_feat", "subject_key": "item:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "multi_feat", "subject_key": "item:1", "label": True, "label_source": "at_work"}},
    ])

    f2 = records_dir / "events.node2.202.jsonl"
    _write_jsonl(f2, [
        {"name": "shadow.verdict", "ts": 2.0, "fields": {"feature": "multi_feat", "subject_key": "item:2", "verdict": False}},
        {"name": "shadow.label", "ts": 2.0, "fields": {"feature": "multi_feat", "subject_key": "item:2", "label": False, "label_source": "at_work"}},
    ])

    res = score_feature("multi_feat", records_dir=records_dir)
    assert res.tp == 1
    assert res.tn == 1
    assert res.verdicts_total == 2


def test_cli_score_text_and_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI score outputs human-readable table and structured JSON."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.cli.jsonl"
    _write_jsonl(log_file, [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "cli_feat", "subject_key": "s:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "cli_feat", "subject_key": "s:1", "label": True, "label_source": "at_work"}},
    ])

    # Text mode
    with pytest.raises(SystemExit) as exit_text:
        app(["shadow", "score", "cli_feat", "--records-dir", str(records_dir)])
    assert exit_text.value.code == 0
    out = capsys.readouterr().out
    assert "Feature: cli_feat" in out
    assert "Precision:" in out

    # JSON mode
    with pytest.raises(SystemExit) as exit_json:
        app(["shadow", "score", "cli_feat", "--records-dir", str(records_dir), "--json"])
    assert exit_json.value.code == 0
    json_out = capsys.readouterr().out
    data = json.loads(json_out)
    assert data["feature"] == "cli_feat"
    assert data["tp"] == 1
    assert data["precision"] == 1.0


def test_score_5_layer_resolution_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 4 (REV2-03): shadow score resolves CISTERNAL_TELEMETRY_LOG_DIR when --records-dir is omitted."""
    log_dir = tmp_path / "env_logs"
    log_dir.mkdir()
    log_file = log_dir / "events.jsonl"
    _write_jsonl(log_file, [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "env_feat", "subject_key": "s:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "env_feat", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])

    monkeypatch.setenv("CISTERNAL_TELEMETRY_LOG_DIR", str(log_dir))

    # Python API without records_dir
    res = score_feature("env_feat")
    assert res.tp == 1
    assert res.precision == 1.0

    # CLI without --records-dir
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "score", "env_feat"])
    assert exit_info.value.code == 0


def test_score_invalid_records_on_unmappable_complex_objects(tmp_path: Path) -> None:
    """Finding 7 (REV2-06): Non-primitive / unextracted objects increment invalid_records."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    _write_jsonl(log_file, [
        # Unextractable dictionary verdict (no known prediction keys)
        {
            "name": "shadow.verdict",
            "ts": 1.0,
            "fields": {
                "feature": "obj_feat",
                "subject_key": "s:1",
                "verdict": {"unknown_key": [1, 2, 3]},
            },
        },
        {
            "name": "shadow.label",
            "ts": 1.0,
            "fields": {
                "feature": "obj_feat",
                "subject_key": "s:1",
                "label": "pass",
                "label_source": "frozen_gold",
            },
        },
    ])

    res = score_feature("obj_feat", records_dir=records_dir, positive_label="pass")
    assert res.invalid_records == 1
    assert res.tp == 0
    assert res.fp == 0
    assert res.tn == 0
    assert res.fn == 0


def test_score_confidence_level_validation(tmp_path: Path) -> None:
    """Finding 9 (REV2-09): Confidence level must be in (0, 1)."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    _write_jsonl(log_file, [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "conf_feat", "subject_key": "s:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "conf_feat", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])

    with pytest.raises(ScoringRefusalError) as exc_1:
        score_feature("conf_feat", records_dir=records_dir, confidence=1.0)
    assert exc_1.value.exit_code == 2

    with pytest.raises(ScoringRefusalError) as exc_0:
        score_feature("conf_feat", records_dir=records_dir, confidence=0.0)
    assert exc_0.value.exit_code == 2

    with pytest.raises(SystemExit) as cli_exit:
        app(["shadow", "score", "conf_feat", "--records-dir", str(records_dir), "--confidence", "1.5"])
    assert cli_exit.value.code == 2


def test_score_iso8601_timestamps_and_flat_json_records(tmp_path: Path) -> None:
    """Finding 9 (REV1-04): Transparent reader unwrapping of ISO 8601 timestamps and flat JSON."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    log_file = records_dir / "events.jsonl"
    # Flat JSON without "fields" wrapper, and ISO 8601 timestamp string
    _write_jsonl(log_file, [
        {
            "name": "shadow.verdict",
            "ts": "2026-11-09T16:00:00Z",
            "feature": "flat_iso_feat",
            "subject_key": "s:1",
            "verdict": True,
        },
        {
            "name": "shadow.label",
            "ts": "2026-11-09T16:05:00Z",
            "feature": "flat_iso_feat",
            "subject_key": "s:1",
            "label": True,
            "label_source": "frozen_gold",
        },
    ])

    res = score_feature("flat_iso_feat", records_dir=records_dir)
    assert res.verdicts_total == 1
    assert res.labels_total == 1
    assert res.tp == 1
    assert res.precision == 1.0
    assert res.recall == 1.0


def test_self_labelling_verdict_record_with_label_field_refused(tmp_path: Path) -> None:
    """B2: a shadow.verdict record carrying a 'label' field is NOT a ground-truth label."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {
            "feature": "f", "subject_key": "s:1", "verdict": True, "label": True}},
    ])
    with pytest.raises(ScoringRefusalError) as exc_info:
        score_feature("f", records_dir=records_dir)
    assert exc_info.value.exit_code == 2


def test_nameless_flat_record_with_verdict_and_label_is_invalid(tmp_path: Path) -> None:
    """B2: a flat nameless record with both verdict and label keys is ambiguous -> invalid, not both."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.jsonl", [
        {"feature": "amb", "subject_key": "s:1", "verdict": True, "label": True, "ts": 1.0},
        {"name": "shadow.label", "ts": 1.0, "fields": {
            "feature": "amb", "subject_key": "s:2", "label": True, "label_source": "frozen_gold"}},
        {"name": "shadow.verdict", "ts": 1.0, "fields": {
            "feature": "amb", "subject_key": "s:2", "verdict": True}},
    ])
    res = score_feature("amb", records_dir=records_dir)
    assert res.labels_total == 1
    assert res.verdicts_total == 1
    assert res.tp == 1
    assert res.invalid_records == 1


def test_rotated_backup_files_are_joined(tmp_path: Path) -> None:
    """B3: RotatingFileHandler backups (*.jsonl.N) are read alongside *.jsonl."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.h.1.jsonl.1", [
        {"name": "shadow.label", "ts": 1.0, "fields": {
            "feature": "rot", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])
    _write_jsonl(records_dir / "events.h.1.jsonl", [
        {"name": "shadow.verdict", "ts": 2.0, "fields": {
            "feature": "rot", "subject_key": "s:1", "verdict": True}},
    ])
    res = score_feature("rot", records_dir=records_dir)
    assert res.labels_total == 1
    assert res.tp == 1


def test_no_timestamp_later_write_wins(tmp_path: Path) -> None:
    """L1: without ts, the later line wins (not the first); rotated backups are read oldest-first."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    # Flat records without ts: verdict False then True, both in one file (later line wins).
    _write_jsonl(records_dir / "events.jsonl", [
        {"feature": "nots", "subject_key": "s:1", "verdict": False},
        {"feature": "nots", "subject_key": "s:1", "verdict": True},
        {"name": "shadow.label", "ts": 1.0, "fields": {
            "feature": "nots", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])
    res = score_feature("nots", records_dir=records_dir)
    assert res.tp == 1
    assert res.fp == 0


def test_no_timestamp_rotated_backup_is_older(tmp_path: Path) -> None:
    """L1: the live file is newer than its .1 backup, so its no-ts verdict wins."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    _write_jsonl(records_dir / "events.h.1.jsonl.1", [
        {"feature": "rotn", "subject_key": "s:1", "verdict": True},
    ])
    _write_jsonl(records_dir / "events.h.1.jsonl", [
        {"feature": "rotn", "subject_key": "s:1", "verdict": False},
        {"name": "shadow.label", "ts": 1.0, "fields": {
            "feature": "rotn", "subject_key": "s:1", "label": False, "label_source": "frozen_gold"}},
    ])
    res = score_feature("rotn", records_dir=records_dir)
    assert res.tn == 1
    assert res.tp == 0


def test_malformed_lines_and_non_dict_records_are_counted_not_fatal(tmp_path: Path) -> None:
    """Crash holes: malformed JSON, non-dict JSON and list subject_key are counted, never raised."""
    records_dir = tmp_path / "logs"
    records_dir.mkdir()
    good = [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "mal", "subject_key": "s:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "mal", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "mal", "subject_key": ["not", "hashable"], "verdict": True}},
    ]
    lines = [json.dumps(r) for r in good] + ["{not json", "[1, 2]", "42"]
    (records_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = score_feature("mal", records_dir=records_dir)
    assert res.tp == 1
    assert res.malformed_lines == 3
    assert res.invalid_records == 1


def test_cli_score_resolution_provenance_printed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """L3: resolved log_dir provenance is printed exactly once, not doubled."""
    log_dir = tmp_path / "env_logs"
    log_dir.mkdir()
    _write_jsonl(log_dir / "events.jsonl", [
        {"name": "shadow.verdict", "ts": 1.0, "fields": {"feature": "pv", "subject_key": "s:1", "verdict": True}},
        {"name": "shadow.label", "ts": 1.0, "fields": {"feature": "pv", "subject_key": "s:1", "label": True, "label_source": "frozen_gold"}},
    ])
    monkeypatch.setenv("CISTERNAL_TELEMETRY_LOG_DIR", str(log_dir))
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "score", "pv"])
    assert exit_info.value.code == 0
    err = capsys.readouterr().err
    assert err.count("resolved log_dir from") == 1
    assert "resolved log_dir from resolved" not in err
