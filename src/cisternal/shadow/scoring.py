"""Scoring engine for shadow features (spec §3.2).

Performs structured joins across shadow.verdict and shadow.label records by subject_key:
- Transparent unwrapping of native cisternal envelopes and flat JSON records.
- Latest-timestamp resolution for verdicts.
- Provenance hierarchy for labels (frozen_gold > owner_confirmed > at_work > retrospective).
- Closed-form Wilson score confidence intervals in pure stdlib math.
- Zero-denominator handling without ZeroDivisionError.
- Refusal on zero labels with exit code 2.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROVENANCE_RANKS: dict[str, int] = {
    "frozen_gold": 4,
    "owner_confirmed": 3,
    "at_work": 2,
    "retrospective": 1,
}


class ScoringRefusalError(RuntimeError):
    """Refusal to score due to empty ground truth or invalid preconditions."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class ScoringResult:
    """Computed evaluation metrics for a feature."""

    feature: str
    verdicts_total: int
    labels_total: int
    unlabelled_verdicts: int
    invalid_records: int
    tp: int
    fp: int
    tn: int
    fn: int
    base_rate: float
    precision: float | None
    precision_ci_lower: float | None
    precision_ci_upper: float | None
    recall: float | None
    recall_ci_lower: float | None
    recall_ci_upper: float | None
    fp_rate: float | None
    precision_exceeds_base_rate: bool | None
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary suitable for JSON serialization."""
        return dataclasses.asdict(self)


def _normal_quantile(p: float) -> float:
    """Acklam's inverse standard normal CDF approximation.

    Returns z such that Phi(z) = p, with absolute error < 1.15e-9 for 0 < p < 1.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be strictly in (0, 1), got {p}")

    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549738039626414e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
        ) / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def compute_wilson_interval(
    k: int, n: int, confidence: float = 0.95
) -> tuple[float, float]:
    """Compute Wilson score confidence interval for binomial proportion k/n."""
    if n <= 0:
        raise ValueError(f"n must be > 0, got {n}")
    if k < 0 or k > n:
        raise ValueError(f"k must be in [0, n], got k={k}, n={n}")

    p_val = 1.0 - (1.0 - confidence) / 2.0
    z = _normal_quantile(p_val)
    z2 = z * z

    p_tilde = (k + z2 / 2.0) / (n + z2)
    radicand = (k * (n - k) / n) + (z2 / 4.0)
    w = (z / (n + z2)) * math.sqrt(radicand)

    lower = max(0.0, p_tilde - w)
    upper = min(1.0, p_tilde + w)
    return lower, upper


def _normalize_ts(ts: Any) -> float:
    """Normalize timestamp from float, int, or ISO 8601 string to epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return float(ts)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    return 0.0


def _unwrap_record(line_dict: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
    """Unwrap a JSON record, supporting native Record envelopes and flat dicts."""
    name = str(line_dict.get("name", ""))
    ts = _normalize_ts(line_dict.get("ts", 0.0))
    fields = line_dict.get("fields", line_dict)
    if not isinstance(fields, dict):
        fields = line_dict
    return name, ts, fields


def _extract_prediction(verdict_val: Any) -> tuple[bool, Any]:
    """Extract candidate prediction value from verdict payload per spec §3.1.1.

    Returns:
        (is_valid, extracted_value)
    """
    if isinstance(verdict_val, dict):
        for key in ("prediction", "decision", "verdict", "value"):
            if key in verdict_val:
                return True, verdict_val[key]
        return False, None
    elif isinstance(verdict_val, (bool, int, float, str)):
        return True, verdict_val
    return False, None


def _map_to_binary(val: Any, positive_label: Any) -> tuple[bool, bool]:
    """Map val to binary boolean (Positive/Negative) relative to positive_label per CHAL-R2-01.

    Returns:
        (is_mappable, is_positive)
    """
    if isinstance(positive_label, bool):
        if isinstance(val, bool):
            return True, (val is positive_label)
        elif isinstance(val, (int, float)):
            return True, (bool(val) is positive_label)
        elif isinstance(val, str):
            clean = val.strip().lower()
            if positive_label is True:
                if clean in ("true", "1", "yes", "pass", "clean"):
                    return True, True
                elif clean in ("false", "0", "no", "fail", "drifted"):
                    return True, False
            else:
                if clean in ("false", "0", "no", "fail", "drifted"):
                    return True, True
                elif clean in ("true", "1", "yes", "pass", "clean"):
                    return True, False
            return False, False
        return False, False
    else:
        # String or primitive positive_label
        if not isinstance(val, (str, int, float, bool)):
            return False, False
        pos_str = str(positive_label).strip().lower()
        if isinstance(val, bool):
            val_str = "true" if val else "false"
        else:
            val_str = str(val).strip().lower()
        return True, (val_str == pos_str)


def score_feature(
    feature: str,
    *,
    records_dir: Path | None = None,
    verdicts_file: Path | None = None,
    labels_file: Path | None = None,
    positive_label: Any = True,
    confidence: float = 0.95,
) -> ScoringResult:
    """Score a shadow feature across telemetry streams.

    Args:
        feature: Unique slug of the feature to evaluate.
        records_dir: Directory containing events.*.jsonl files.
        verdicts_file: Specific verdicts JSONL file override.
        labels_file: Specific labels JSONL file override.
        positive_label: Ground truth positive class definition.
        confidence: Confidence level for Wilson score intervals (default 0.95).

    Returns:
        ScoringResult dataclass containing confusion matrix and Wilson intervals.

    Raises:
        ScoringRefusalError: If 0 matching labels exist for the feature (exit code 2).
    """
    if confidence <= 0.0 or confidence >= 1.0:
        raise ScoringRefusalError(
            f"Confidence level must be strictly between 0.0 and 1.0, got {confidence}",
            exit_code=2,
        )

    # 5-layer resolution fallback if no telemetry input is specified
    if records_dir is None and verdicts_file is None and labels_file is None:
        from cisternal.shadow.resolution import ResolutionError, resolve_log_dir
        try:
            res_log = resolve_log_dir(cli_arg=None)
            records_dir = res_log.path
        except ResolutionError as exc:
            raise ScoringRefusalError(
                f"Resolution error: {exc}",
                exit_code=2,
            ) from exc
    files_to_read: list[Path] = []
    if verdicts_file:
        files_to_read.append(Path(verdicts_file))
    if labels_file:
        files_to_read.append(Path(labels_file))
    if records_dir:
        p = Path(records_dir)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.name.endswith(".jsonl"):
                    if f not in files_to_read:
                        files_to_read.append(f)

    # Subject maps:
    # verdicts: subject_key -> (timestamp, raw_verdict)
    # labels: subject_key -> (provenance_rank, timestamp, raw_label, label_source)
    verdicts: dict[str, tuple[float, Any]] = {}
    labels: dict[str, tuple[int, float, Any, str]] = {}

    for fpath in files_to_read:
        if not fpath.is_file():
            continue
        try:
            with fpath.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record_dict = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    name, ts, fields = _unwrap_record(record_dict)
                    feat = fields.get("feature")
                    if feat != feature:
                        continue

                    s_key = fields.get("subject_key")
                    if not s_key:
                        continue

                    if name == "shadow.verdict" or "verdict" in fields:
                        raw_v = fields.get("verdict")
                        if s_key not in verdicts or ts > verdicts[s_key][0]:
                            verdicts[s_key] = (ts, raw_v)

                    if name == "shadow.label" or "label" in fields:
                        raw_lbl = fields.get("label")
                        source = str(fields.get("label_source", "at_work"))
                        rank = PROVENANCE_RANKS.get(source, 0)
                        if s_key not in labels:
                            labels[s_key] = (rank, ts, raw_lbl, source)
                        else:
                            curr_rank, curr_ts, _, _ = labels[s_key]
                            if (rank > curr_rank) or (rank == curr_rank and ts > curr_ts):
                                labels[s_key] = (rank, ts, raw_lbl, source)
        except OSError:
            continue

    # Negative Control 1: Refusal on zero labels
    if not labels:
        raise ScoringRefusalError(
            f"REFUSAL: feature '{feature}' has 0 matching labels. Scoring requires at least 1 labeled subject.",
            exit_code=2,
        )

    verdicts_total = len(verdicts)
    labels_total = len(labels)
    unlabelled_verdicts = sum(1 for sk in verdicts if sk not in labels)
    invalid_records = 0

    tp = 0
    fp = 0
    fn = 0
    tn = 0

    # Join on subject_key where both verdict and label exist
    common_keys = set(verdicts.keys()) & set(labels.keys())
    for sk in common_keys:
        _, raw_verdict = verdicts[sk]
        _, _, raw_label, _ = labels[sk]

        is_valid_pred, pred_val = _extract_prediction(raw_verdict)
        if not is_valid_pred:
            invalid_records += 1
            continue

        pred_ok, is_pred_pos = _map_to_binary(pred_val, positive_label)
        lbl_ok, is_lbl_pos = _map_to_binary(raw_label, positive_label)

        if not pred_ok or not lbl_ok:
            invalid_records += 1
            continue

        if is_pred_pos and is_lbl_pos:
            tp += 1
        elif is_pred_pos and not is_lbl_pos:
            fp += 1
        elif not is_pred_pos and is_lbl_pos:
            fn += 1
        else:
            tn += 1

    n_labeled = tp + fp + fn + tn
    base_rate = (tp + fn) / n_labeled if n_labeled > 0 else 0.0

    # Precision & Wilson CI
    if tp + fp > 0:
        precision = tp / (tp + fp)
        p_low, p_high = compute_wilson_interval(tp, tp + fp, confidence)
        precision_ci_lower: float | None = p_low
        precision_ci_upper: float | None = p_high
    else:
        precision = None
        precision_ci_lower = None
        precision_ci_upper = None

    # Recall & Wilson CI
    if tp + fn > 0:
        recall = tp / (tp + fn)
        r_low, r_high = compute_wilson_interval(tp, tp + fn, confidence)
        recall_ci_lower: float | None = r_low
        recall_ci_upper: float | None = r_high
    else:
        recall = None
        recall_ci_lower = None
        recall_ci_upper = None

    # False Positive Rate
    if fp + tn > 0:
        fp_rate: float | None = fp / (fp + tn)
    else:
        fp_rate = None

    # Comparison against Base Rate
    if precision_ci_lower is not None:
        precision_exceeds_base_rate: bool | None = precision_ci_lower > base_rate
    else:
        precision_exceeds_base_rate = None

    return ScoringResult(
        feature=feature,
        verdicts_total=verdicts_total,
        labels_total=labels_total,
        unlabelled_verdicts=unlabelled_verdicts,
        invalid_records=invalid_records,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        base_rate=base_rate,
        precision=precision,
        precision_ci_lower=precision_ci_lower,
        precision_ci_upper=precision_ci_upper,
        recall=recall,
        recall_ci_lower=recall_ci_lower,
        recall_ci_upper=recall_ci_upper,
        fp_rate=fp_rate,
        precision_exceeds_base_rate=precision_exceeds_base_rate,
        confidence=confidence,
    )
