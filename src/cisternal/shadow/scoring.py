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
import re
from dataclasses import dataclass, field
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
    malformed_lines: int
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


# ---------------------------------------------------------------------------
# Shared join (spec §3.2): used by both `shadow score` and `shadow check`.
# ---------------------------------------------------------------------------

# Telemetry files: live `*.jsonl` plus RotatingFileHandler backups `*.jsonl.<N>`.
LOG_FILE_RE = re.compile(r"(?P<base>.+\.jsonl)(?:\.(?P<rot>\d+))?")
KNOWN_LABEL_SOURCES: tuple[str, ...] = tuple(PROVENANCE_RANKS)
VERDICT_NAME = "shadow.verdict"
LABEL_NAME = "shadow.label"
ISOLATION_NAME = "shadow.isolation"


@dataclass
class Collected:
    """Output of the single shared scan over telemetry files for one feature.

    verdicts: subject_key -> (ts, raw_verdict); latest ts wins (ties: later read wins).
    labels: subject_key -> (provenance_rank, ts, raw_label, source); only allowed sources
        are considered, selected by provenance then ts (ties: later read wins).
    label_records: count of label records for the feature from ANY source (refusal basis).
    labels_file_sources: every label_source seen in the explicit labels file, pre-filter.
    isolation_events: fields dicts of shadow.isolation records for the feature.
    malformed_lines: lines that are not JSON objects (counted, never fatal).
    unjoinable: records for the feature that cannot be joined (ambiguous nameless
        verdict+label record, or non-string subject_key); counted as invalid.
    """

    verdicts: dict[str, tuple[float, Any]] = field(default_factory=dict)
    labels: dict[str, tuple[int, float, Any, str]] = field(default_factory=dict)
    label_records: int = 0
    labels_file_sources: set[str] = field(default_factory=set)
    isolation_events: list[dict[str, Any]] = field(default_factory=list)
    malformed_lines: int = 0
    unjoinable: int = 0


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    fn: int
    tn: int
    invalid_records: int


@dataclass(frozen=True)
class Summary:
    tp: int
    fp: int
    fn: int
    tn: int
    base_rate: float
    precision: float | None
    precision_ci_lower: float | None
    precision_ci_upper: float | None
    recall: float | None
    recall_ci_lower: float | None
    recall_ci_upper: float | None
    fp_rate: float | None
    precision_exceeds_base_rate: bool | None


def _log_file_order_key(path: Path) -> tuple[str, int]:
    """Sort key: per base name, rotated backups oldest-first (.N .. .1), then the live file."""
    m = LOG_FILE_RE.fullmatch(path.name)
    assert m is not None
    return (m.group("base"), -int(m.group("rot") or 0))


def gather_files(
    records_dir: Path | str | None = None,
    *,
    verdicts_file: Path | str | None = None,
    labels_file: Path | str | None = None,
) -> list[Path]:
    """Ordered, de-duplicated (by resolved path) list of existing telemetry files."""
    files: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        if not p.is_file():
            return
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            files.append(p)

    if verdicts_file:
        _add(Path(verdicts_file))
    if labels_file:
        _add(Path(labels_file))
    if records_dir is not None:
        d = Path(records_dir)
        if d.is_dir():
            candidates = [f for f in d.iterdir() if f.is_file() and LOG_FILE_RE.fullmatch(f.name)]
            for f in sorted(candidates, key=_log_file_order_key):
                _add(f)
    return files


def collect_records(
    feature: str,
    files: list[Path],
    *,
    labels_file: Path | str | None = None,
    allowed_label_sources: set[str] | frozenset[str] | None = None,
    feature_version: str | None = None,
) -> Collected:
    """Single scan shared by `score` and `check`.

    Dispatch: a non-empty `name` decides the record kind strictly (shadow.verdict /
    shadow.label / shadow.isolation; other names are ignored). Field sniffing is used only
    for nameless flat records, where carrying both `verdict` and `label` is ambiguous.
    """
    out = Collected()
    labels_file_resolved = Path(labels_file).resolve() if labels_file else None

    for fpath in files:
        try:
            fh = fpath.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    out.malformed_lines += 1
                    continue
                if not isinstance(record, dict):
                    out.malformed_lines += 1
                    continue

                name, ts, fields = _unwrap_record(record)
                if fields.get("feature") != feature:
                    continue

                if name == ISOLATION_NAME:
                    out.isolation_events.append(fields)
                    continue

                if name:
                    if name not in (VERDICT_NAME, LABEL_NAME):
                        continue
                    kind = name
                else:
                    has_v = "verdict" in fields
                    has_l = "label" in fields
                    if has_v and has_l:
                        out.unjoinable += 1
                        continue
                    if has_v:
                        kind = VERDICT_NAME
                    elif has_l:
                        kind = LABEL_NAME
                    else:
                        continue

                s_key = fields.get("subject_key")
                if s_key is None or s_key == "":
                    continue
                if not isinstance(s_key, str):
                    out.unjoinable += 1
                    continue

                if kind == VERDICT_NAME:
                    if feature_version is not None:
                        fv = fields.get("feature_version")
                        if fv is None or str(fv) != feature_version:
                            continue
                    # Later line wins on equal ts (read order is deterministic).
                    if s_key not in out.verdicts or ts >= out.verdicts[s_key][0]:
                        out.verdicts[s_key] = (ts, fields.get("verdict"))
                else:
                    out.label_records += 1
                    source = str(fields.get("label_source", "at_work"))
                    if labels_file_resolved is not None and fpath.resolve() == labels_file_resolved:
                        out.labels_file_sources.add(source)
                    if allowed_label_sources is not None and source not in allowed_label_sources:
                        continue
                    rank = PROVENANCE_RANKS.get(source, 0)
                    cur = out.labels.get(s_key)
                    if cur is None or (rank, ts) >= (cur[0], cur[1]):
                        out.labels[s_key] = (rank, ts, fields.get("label"), source)
    return out


def confusion(
    verdicts: dict[str, tuple[float, Any]],
    labels: dict[str, tuple[int, float, Any, str]],
    positive_label: Any,
) -> Confusion:
    """Confusion counts over subject keys present in both maps."""
    tp = fp = fn = tn = invalid = 0
    for sk in sorted(set(verdicts) & set(labels)):
        _, raw_verdict = verdicts[sk]
        _, _, raw_label, _ = labels[sk]

        is_valid_pred, pred_val = _extract_prediction(raw_verdict)
        if not is_valid_pred:
            invalid += 1
            continue
        pred_ok, is_pred_pos = _map_to_binary(pred_val, positive_label)
        lbl_ok, is_lbl_pos = _map_to_binary(raw_label, positive_label)
        if not pred_ok or not lbl_ok:
            invalid += 1
            continue

        if is_pred_pos and is_lbl_pos:
            tp += 1
        elif is_pred_pos and not is_lbl_pos:
            fp += 1
        elif not is_pred_pos and is_lbl_pos:
            fn += 1
        else:
            tn += 1
    return Confusion(tp=tp, fp=fp, fn=fn, tn=tn, invalid_records=invalid)


def summarize(conf: Confusion, confidence: float) -> Summary:
    """Base rate, precision/recall with Wilson CIs, FPR. Zero denominators yield None."""
    tp, fp, fn, tn = conf.tp, conf.fp, conf.fn, conf.tn
    n_labeled = tp + fp + fn + tn
    base_rate = (tp + fn) / n_labeled if n_labeled > 0 else 0.0

    precision: float | None = None
    p_low: float | None = None
    p_high: float | None = None
    if tp + fp > 0:
        precision = tp / (tp + fp)
        p_low, p_high = compute_wilson_interval(tp, tp + fp, confidence)

    recall: float | None = None
    r_low: float | None = None
    r_high: float | None = None
    if tp + fn > 0:
        recall = tp / (tp + fn)
        r_low, r_high = compute_wilson_interval(tp, tp + fn, confidence)

    fp_rate: float | None = fp / (fp + tn) if fp + tn > 0 else None
    exceeds: bool | None = (p_low > base_rate) if p_low is not None else None

    return Summary(
        tp=tp, fp=fp, fn=fn, tn=tn, base_rate=base_rate,
        precision=precision, precision_ci_lower=p_low, precision_ci_upper=p_high,
        recall=recall, recall_ci_lower=r_low, recall_ci_upper=r_high,
        fp_rate=fp_rate, precision_exceeds_base_rate=exceeds,
    )


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
        records_dir: Directory containing events.*.jsonl (and rotated *.jsonl.N) files.
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
                exit_code=exc.exit_code,
            ) from exc

    files = gather_files(records_dir, verdicts_file=verdicts_file, labels_file=labels_file)
    coll = collect_records(feature, files, labels_file=labels_file)

    # Negative Control 1: Refusal on zero labels
    if coll.label_records == 0:
        raise ScoringRefusalError(
            f"REFUSAL: feature '{feature}' has 0 matching labels. Scoring requires at least 1 labeled subject.",
            exit_code=2,
        )

    conf = confusion(coll.verdicts, coll.labels, positive_label)
    summary = summarize(conf, confidence)
    unlabelled = sum(1 for sk in coll.verdicts if sk not in coll.labels)

    return ScoringResult(
        feature=feature,
        verdicts_total=len(coll.verdicts),
        labels_total=len(coll.labels),
        unlabelled_verdicts=unlabelled,
        invalid_records=conf.invalid_records + coll.unjoinable,
        malformed_lines=coll.malformed_lines,
        tp=summary.tp,
        fp=summary.fp,
        tn=summary.tn,
        fn=summary.fn,
        base_rate=summary.base_rate,
        precision=summary.precision,
        precision_ci_lower=summary.precision_ci_lower,
        precision_ci_upper=summary.precision_ci_upper,
        recall=summary.recall,
        recall_ci_lower=summary.recall_ci_lower,
        recall_ci_upper=summary.recall_ci_upper,
        fp_rate=summary.fp_rate,
        precision_exceeds_base_rate=summary.precision_exceeds_base_rate,
        confidence=confidence,
    )
