"""Mode-state TOML configuration parsing and promotion gate checking (spec §3.3).

Evaluates candidate features against pre-registered stage gates:
- Strict schema validation failing loudly on malformed TOML (exit code 3).
- Non-short-circuiting gate evaluation accumulating all deficits in blocking_reasons.
- Dynamic enforcer symbol resolution (<relative_file_path>::<symbol_name>).
- Read-only immutability contract (never mutates configuration or git).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cisternal.shadow.resolution import (
    find_repo_root,
    resolve_log_dir,
    resolve_mode_state_dir,
)
from cisternal.shadow.scoring import (
    PROVENANCE_RANKS,
    _extract_prediction,
    _map_to_binary,
    _unwrap_record,
    compute_wilson_interval,
)


class GateCheckError(RuntimeError):
    """Exception raised on configuration error, refusal, or gate failure."""

    def __init__(self, message: str, exit_code: int = 3) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class CheckResult:
    """Report payload from evaluating a feature's promotion gates."""

    feature: str
    current_stage: str
    target_stage: str
    promotion_permitted: bool
    blocking_reasons: list[str]
    metrics: dict[str, Any]
    exit_code: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize evaluation result to dictionary matching spec §3.3.2."""
        return {
            "feature": self.feature,
            "current_stage": self.current_stage,
            "target_stage": self.target_stage,
            "promotion_permitted": self.promotion_permitted,
            "blocking_reasons": self.blocking_reasons,
            "metrics": self.metrics,
        }


def load_mode_state(path: Path | str) -> dict[str, Any]:
    """Load and validate mode-state TOML file per spec §3.3.1.

    Args:
        path: Path to mode-state TOML configuration.

    Returns:
        Parsed dictionary.

    Raises:
        GateCheckError: If file is missing or contains invalid TOML syntax (exit 3).
    """
    p = Path(path).resolve()
    if not p.is_file():
        raise GateCheckError(f"Mode-state file not found at {p}", exit_code=3)

    try:
        content = p.read_text(encoding="utf-8")
        data = tomllib.loads(content)
    except Exception as exc:
        raise GateCheckError(
            f"Failed to parse mode-state TOML at {p}: {exc}",
            exit_code=3,
        ) from exc

    required_sections = ("feature", "ladder", "shadow", "promotion")
    missing = [sec for sec in required_sections if sec not in data]
    if missing:
        raise GateCheckError(
            f"Mode-state TOML at {p} missing required tables: {', '.join(missing)}",
            exit_code=3,
        )

    return data


def resolve_enforcer_symbol(
    symbol_str: str,
    repo_root: Path | None = None,
) -> Callable[..., Any] | None:
    """Resolve an enforcer test symbol formatted as <file_path>::<symbol_name>.

    Resolves relative to repo_root via importlib.util.spec_from_file_location,
    falling back to module import.

    Returns:
        Callable attribute, or None if unimportable.
    """
    if "::" not in symbol_str:
        return None

    path_part, sym_part = symbol_str.split("::", 1)
    root = repo_root or find_repo_root() or Path.cwd()
    file_path = (root / path_part).resolve() if not Path(path_part).is_absolute() else Path(path_part)

    if file_path.is_file():
        try:
            mod_name = f"_cisternal_enforcer_{file_path.stem}"
            spec = importlib.util.spec_from_file_location(mod_name, file_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                return getattr(mod, sym_part, None)
        except Exception:
            return None

    # Fallback to module import
    try:
        mod = importlib.import_module(path_part)
        return getattr(mod, sym_part, None)
    except Exception:
        return None


def evaluate_gate(
    mode_data: dict[str, Any],
    records_dir: Path,
    *,
    repo_root: Path | None = None,
    confidence: float = 0.95,
) -> CheckResult:
    """Evaluate promotion readiness of a feature against telemetry records.

    Implements non-short-circuiting gate evaluation per spec §3.3.2.
    """
    feat_cfg = mode_data.get("feature", {})
    feature = str(feat_cfg.get("name", ""))
    current_stage = str(mode_data.get("ladder", {}).get("current_stage", "off"))
    shadow_cfg = mode_data.get("shadow", {})
    scoring_cfg = mode_data.get("scoring", {})
    positive_label = scoring_cfg.get("positive_label", True)
    promotion = mode_data.get("promotion", {})
    target_stage = str(promotion.get("target_stage", "advisory"))

    # Scan telemetry records
    files_to_read: list[Path] = []
    if records_dir.is_dir():
        for f in sorted(records_dir.iterdir()):
            if f.is_file() and f.name.endswith(".jsonl"):
                files_to_read.append(f)

    verdicts: dict[str, tuple[float, Any]] = {}
    labels: dict[str, tuple[int, float, Any, str]] = {}
    isolation_events: list[dict[str, Any]] = []

    for fpath in files_to_read:
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
                    if fields.get("feature") != feature:
                        continue

                    if name == "shadow.isolation":
                        isolation_events.append(fields)
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

    # Refusal on empty telemetry
    if not verdicts and not labels:
        raise GateCheckError(
            f"REFUSAL: 0 verdicts and 0 labels found for feature '{feature}' in {records_dir}",
            exit_code=2,
        )
    if not labels:
        raise GateCheckError(
            f"REFUSAL: feature '{feature}' has 0 matching labels. Gate check requires at least 1 labeled subject.",
            exit_code=2,
        )

    blocking_reasons: list[str] = []

    # 1. Isolation check
    enforcer_symbol = shadow_cfg.get("writes_isolated_enforced_by")
    if enforcer_symbol:
        fn = resolve_enforcer_symbol(enforcer_symbol, repo_root=repo_root)
        if fn is None:
            blocking_reasons.append(f"enforcer_unimportable:{enforcer_symbol}")

    isolation_violations_count = 0
    for iso in isolation_events:
        if iso.get("writes_isolated") is False or (iso.get("leaked_paths") and len(iso.get("leaked_paths")) > 0):
            isolation_violations_count += 1

    max_iso_violations = promotion.get("isolation_violations_max", 0)
    if isolation_violations_count > max_iso_violations:
        blocking_reasons.append("isolation_violation_detected")

    # 2. Sample size gates
    verdicts_total = len(verdicts)
    min_verdicts = promotion.get("min_verdicts")
    if min_verdicts is not None and verdicts_total < min_verdicts:
        blocking_reasons.append(f"insufficient_verdicts:{verdicts_total}/{min_verdicts}")

    allowed_sources = set(promotion.get("allowed_label_sources", ["frozen_gold", "owner_confirmed", "at_work"]))
    # Filter labels to allowed sources
    filtered_labels = {
        sk: data for sk, data in labels.items()
        if data[3] in allowed_sources
    }
    labels_total = len(filtered_labels)
    min_labels = promotion.get("min_labels")
    if min_labels is not None and labels_total < min_labels:
        blocking_reasons.append(f"insufficient_labels:{labels_total}/{min_labels}")

    # 3. Join and calculate confusion metrics
    tp = 0
    fp = 0
    fn = 0
    tn = 0
    common_keys = set(verdicts.keys()) & set(filtered_labels.keys())

    for sk in common_keys:
        _, raw_v = verdicts[sk]
        _, _, raw_l, _ = filtered_labels[sk]

        is_valid_pred, pred_val = _extract_prediction(raw_v)
        if not is_valid_pred:
            continue
        pred_ok, is_pred_pos = _map_to_binary(pred_val, positive_label)
        lbl_ok, is_lbl_pos = _map_to_binary(raw_l, positive_label)
        if not pred_ok or not lbl_ok:
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

    # FPR
    if fp + tn > 0:
        fp_rate: float | None = fp / (fp + tn)
    else:
        fp_rate = None

    # 4. Precision gates
    min_prec = promotion.get("min_precision")
    if min_prec is not None:
        if precision is None:
            blocking_reasons.append("precision_undefined_no_positive_predictions")
        elif precision < min_prec:
            blocking_reasons.append(f"precision_deficit:{precision:.2f}/{min_prec:.2f}")

    min_prec_lower = promotion.get("min_precision_lower_bound")
    if min_prec_lower is not None:
        if precision_ci_lower is None:
            if "precision_undefined_no_positive_predictions" not in blocking_reasons:
                blocking_reasons.append("precision_undefined_no_positive_predictions")
        elif precision_ci_lower < min_prec_lower:
            blocking_reasons.append(
                f"precision_lower_bound_deficit:{precision_ci_lower:.2f}/{min_prec_lower:.2f}"
            )

    # 5. Recall gates
    min_rec = promotion.get("min_recall")
    if min_rec is not None:
        if recall is None:
            blocking_reasons.append("recall_undefined_no_positive_labels")
        elif recall < min_rec:
            blocking_reasons.append(f"recall_deficit:{recall:.2f}/{min_rec:.2f}")

    min_rec_lower = promotion.get("min_recall_lower_bound")
    if min_rec_lower is not None:
        if recall_ci_lower is None:
            if "recall_undefined_no_positive_labels" not in blocking_reasons:
                blocking_reasons.append("recall_undefined_no_positive_labels")
        elif recall_ci_lower < min_rec_lower:
            blocking_reasons.append(
                f"recall_lower_bound_deficit:{recall_ci_lower:.2f}/{min_rec_lower:.2f}"
            )

    # 6. Base rate comparison
    if precision_ci_lower is not None:
        if precision_ci_lower <= base_rate:
            blocking_reasons.append("precision_lower_bound_below_base_rate")

    # 7. False positive rate
    max_fpr = promotion.get("max_fp_rate")
    if max_fpr is not None:
        if fp_rate is None:
            blocking_reasons.append("fpr_undefined_no_negative_labels")
        elif fp_rate > max_fpr:
            blocking_reasons.append(f"fpr_exceeded:{fp_rate:.2f}/{max_fpr:.2f}")

    promotion_permitted = (len(blocking_reasons) == 0)
    exit_code = 0 if promotion_permitted else 1

    metrics = {
        "verdicts_total": verdicts_total,
        "labels_total": labels_total,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "base_rate": base_rate,
        "precision": round(precision, 4) if precision is not None else None,
        "precision_ci_lower": round(precision_ci_lower, 4) if precision_ci_lower is not None else None,
        "precision_ci_upper": round(precision_ci_upper, 4) if precision_ci_upper is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "recall_ci_lower": round(recall_ci_lower, 4) if recall_ci_lower is not None else None,
        "recall_ci_upper": round(recall_ci_upper, 4) if recall_ci_upper is not None else None,
        "fp_rate": round(fp_rate, 4) if fp_rate is not None else None,
        "isolation_violations": isolation_violations_count,
    }

    return CheckResult(
        feature=feature,
        current_stage=current_stage,
        target_stage=target_stage,
        promotion_permitted=promotion_permitted,
        blocking_reasons=blocking_reasons,
        metrics=metrics,
        exit_code=exit_code,
    )


def check_mode_state(
    feature_or_path: str | Path,
    *,
    records_dir: Path | None = None,
    mode_state_dir: Path | None = None,
    repo_root: Path | None = None,
) -> CheckResult:
    """Resolve paths, parse mode-state, and evaluate promotion gates."""
    raw = str(feature_or_path)
    root = repo_root or find_repo_root()

    # Determine TOML file path
    if Path(raw).is_file() or raw.endswith(".toml"):
        toml_path = Path(raw).resolve()
    else:
        # Resolve mode_state_dir via 5-layer hierarchy
        res = resolve_mode_state_dir(cli_arg=mode_state_dir, repo_root=root)
        candidate = res.path / f"{raw}.toml"
        if not candidate.is_file():
            raise GateCheckError(
                f"Mode-state TOML not found for feature '{raw}' in {res.path}",
                exit_code=3,
            )
        toml_path = candidate

    mode_data = load_mode_state(toml_path)

    # Resolve log_dir via 5-layer hierarchy if records_dir not explicitly passed
    if records_dir is None:
        res_log = resolve_log_dir(cli_arg=None, repo_root=root)
        effective_records_dir = res_log.path
    else:
        effective_records_dir = Path(records_dir).resolve()

    return evaluate_gate(mode_data, effective_records_dir, repo_root=root)
