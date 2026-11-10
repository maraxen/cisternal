"""Mode-state TOML configuration parsing and promotion gate checking (spec §3.3).

Evaluates candidate features against pre-registered stage gates:
- Strict schema validation: unknown tables/keys, wrong types and unknown label sources
  fail loudly (exit code 3); nothing is silently ignored.
- Non-short-circuiting gate evaluation accumulating all deficits in blocking_reasons.
- Fail-closed isolation gate: declared isolation, an enforcer and clean isolation
  evidence are all required for promotion.
- Dynamic enforcer symbol resolution (<relative_file_path>::<symbol_name>), restricted
  to files inside the repository root.
- Read-only immutability contract (never mutates configuration or git).

The telemetry join is shared with `shadow score` (cisternal.shadow.scoring).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import importlib.util
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
    KNOWN_LABEL_SOURCES,
    collect_records,
    confusion,
    gather_files,
    summarize,
)

VALID_STAGES: tuple[str, ...] = ("off", "shadow", "advisory", "enforce")
REQUIRED_TABLES: tuple[str, ...] = ("feature", "ladder", "shadow", "promotion")
DEFAULT_ALLOWED_LABEL_SOURCES: tuple[str, ...] = ("frozen_gold", "owner_confirmed", "at_work")

# Per-table allowed keys (spec §3.3.1). Any other table or key is a configuration error.
ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "feature": frozenset({"name", "description", "version"}),
    "ladder": frozenset({"current_stage"}),
    "shadow": frozenset({"traffic_fraction", "writes_isolated", "writes_isolated_enforced_by"}),
    "scoring": frozenset({"positive_label"}),
    "promotion": frozenset({
        "target_stage",
        "min_verdicts",
        "min_labels",
        "allowed_label_sources",
        "min_precision",
        "min_precision_lower_bound",
        "min_recall",
        "min_recall_lower_bound",
        "max_fp_rate",
        "isolation_violations_max",
        "threshold_basis",
        "feature_version",
    }),
}
_COUNT_KEYS = ("min_verdicts", "min_labels", "isolation_violations_max")
_RATE_KEYS = (
    "min_precision",
    "min_precision_lower_bound",
    "min_recall",
    "min_recall_lower_bound",
    "max_fp_rate",
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
    # Human-readable log_dir resolution provenance (CLI stderr only; not in to_dict).
    log_dir_provenance: str | None = None

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


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_count(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _validate_mode_data(data: dict[str, Any], where: str) -> None:
    """Strict schema validation (spec §3.3.1). Raises GateCheckError(exit 3)."""

    def fail(msg: str) -> GateCheckError:
        return GateCheckError(f"Mode-state TOML at {where}: {msg}", exit_code=3)

    for table, value in data.items():
        if table not in ALLOWED_KEYS:
            raise fail(f"unknown table [{table}]")
        if not isinstance(value, dict):
            raise fail(f"[{table}] must be a table")
        for key in value:
            if key not in ALLOWED_KEYS[table]:
                raise fail(f"unknown key [{table}] {key}")

    missing = [sec for sec in REQUIRED_TABLES if sec not in data]
    if missing:
        raise fail(f"missing required tables: {', '.join(missing)}")

    feat = data["feature"]
    if not isinstance(feat.get("name"), str) or not feat.get("name", "").strip():
        raise fail("missing required non-empty string key: [feature] name")
    for key in ("description", "version"):
        if key in feat and not isinstance(feat[key], str):
            raise fail(f"[feature] {key} must be a string")

    ladder = data["ladder"]
    if ladder.get("current_stage") not in VALID_STAGES:
        raise fail(f"missing or invalid required key [ladder] current_stage (must be one of {VALID_STAGES})")

    shadow = data["shadow"]
    if not isinstance(shadow.get("writes_isolated"), bool):
        raise fail("missing required boolean key: [shadow] writes_isolated")
    if "traffic_fraction" in shadow:
        tf = shadow["traffic_fraction"]
        if not _is_number(tf) or not 0.0 <= tf <= 1.0:
            raise fail("[shadow] traffic_fraction must be a number in [0, 1]")
    if "writes_isolated_enforced_by" in shadow and not isinstance(shadow["writes_isolated_enforced_by"], str):
        raise fail("[shadow] writes_isolated_enforced_by must be a string")

    if "scoring" in data:
        pl = data["scoring"].get("positive_label", True)
        if not isinstance(pl, (bool, int, float, str)):
            raise fail("[scoring] positive_label must be a bool, number or string")

    promo = data["promotion"]
    if promo.get("target_stage") not in VALID_STAGES:
        raise fail(f"missing or invalid required key [promotion] target_stage (must be one of {VALID_STAGES})")
    for key in _COUNT_KEYS:
        if key in promo and not _is_count(promo[key]):
            raise fail(f"[promotion] {key} must be a non-negative integer")
    for key in _RATE_KEYS:
        if key in promo and (not _is_number(promo[key]) or not 0.0 <= promo[key] <= 1.0):
            raise fail(f"[promotion] {key} must be a number in [0, 1]")
    if "allowed_label_sources" in promo:
        srcs = promo["allowed_label_sources"]
        if not isinstance(srcs, list) or not all(isinstance(s, str) for s in srcs):
            raise fail("[promotion] allowed_label_sources must be a list of strings")
        unknown = sorted(s for s in srcs if s not in KNOWN_LABEL_SOURCES)
        if unknown:
            raise fail(
                f"[promotion] allowed_label_sources contains unknown source(s) {unknown} "
                f"(must be a subset of {list(KNOWN_LABEL_SOURCES)})"
            )
    for key in ("threshold_basis", "feature_version"):
        if key in promo and not isinstance(promo[key], str):
            raise fail(f"[promotion] {key} must be a string")


def load_mode_state(path: Path | str) -> dict[str, Any]:
    """Load and validate mode-state TOML file per spec §3.3.1.

    Args:
        path: Path to mode-state TOML configuration.

    Returns:
        Parsed dictionary.

    Raises:
        GateCheckError: If file is missing, malformed, or fails schema validation (exit 3).
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

    _validate_mode_data(data, str(p))
    return data


def resolve_enforcer_symbol(
    symbol_str: str,
    repo_root: Path | None = None,
) -> Callable[..., Any] | None:
    """Resolve an enforcer test symbol formatted as <file_path>::<symbol_name>.

    An existing file is loaded via importlib.util.spec_from_file_location, but only when it
    resolves inside repo_root; paths outside it (absolute or via `..`) are rejected (None).
    A path that does not exist as a file falls back to module import.

    Returns:
        Callable attribute, or None if unimportable or rejected.
    """
    if "::" not in symbol_str:
        return None

    path_part, sym_part = symbol_str.split("::", 1)
    root = (repo_root or find_repo_root() or Path.cwd()).resolve()
    candidate = Path(path_part)
    file_path = (candidate if candidate.is_absolute() else root / candidate).resolve()

    if file_path.is_file():
        if not file_path.is_relative_to(root):
            return None
        try:
            digest = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:16]
            mod_name = f"_cisternal_enforcer_{digest}"
            spec = importlib.util.spec_from_file_location(mod_name, file_path)
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(mod_name, None)
                raise
            fn = getattr(mod, sym_part, None)
            return fn if callable(fn) else None
        except Exception:
            return None

    # Fallback to module import (file does not exist on disk)
    try:
        mod = importlib.import_module(path_part)
        fn = getattr(mod, sym_part, None)
        return fn if callable(fn) else None
    except Exception:
        return None


def evaluate_gate(
    mode_data: dict[str, Any],
    records_dir: Path | None = None,
    *,
    verdicts_file: Path | None = None,
    labels_file: Path | None = None,
    repo_root: Path | None = None,
    confidence: float = 0.95,
) -> CheckResult:
    """Evaluate promotion readiness of a feature against telemetry records.

    Implements non-short-circuiting gate evaluation per spec §3.3.2.

    ``mode_data`` is re-validated here (unknown keys, types, ranges → GateCheckError
    exit 3), so API callers passing a raw dict get the same checks as
    ``load_mode_state``.
    """
    _validate_mode_data(mode_data, "<mode_data passed to evaluate_gate>")
    if confidence <= 0.0 or confidence >= 1.0:
        raise GateCheckError(
            f"Confidence level must be strictly between 0.0 and 1.0, got {confidence}",
            exit_code=2,
        )

    feat_cfg = mode_data.get("feature", {})
    feature = str(feat_cfg.get("name", ""))
    current_stage = str(mode_data.get("ladder", {}).get("current_stage", "off"))
    shadow_cfg = mode_data.get("shadow", {})
    scoring_cfg = mode_data.get("scoring", {})
    positive_label = scoring_cfg.get("positive_label", True)
    promotion = mode_data.get("promotion", {})
    target_stage = str(promotion.get("target_stage", "advisory"))
    allowed_sources = set(promotion.get("allowed_label_sources", list(DEFAULT_ALLOWED_LABEL_SOURCES)))

    # Shared scan. Disallowed label sources are filtered BEFORE provenance selection (M1).
    files = gather_files(records_dir, verdicts_file=verdicts_file, labels_file=labels_file)
    coll = collect_records(
        feature,
        files,
        labels_file=labels_file,
        allowed_label_sources=allowed_sources,
        feature_version=promotion.get("feature_version"),
    )
    verdicts = coll.verdicts
    labels = coll.labels

    # Refusal on empty telemetry. The label refusal looks at ANY-source label presence;
    # disallowed-only labels are blocked below (insufficient_labels), not refused.
    if not verdicts and coll.label_records == 0:
        loc = records_dir or verdicts_file or labels_file
        raise GateCheckError(
            f"REFUSAL: 0 verdicts and 0 labels found for feature '{feature}' in {loc}",
            exit_code=2,
        )
    if not verdicts:
        loc = records_dir or verdicts_file
        raise GateCheckError(
            f"REFUSAL: feature '{feature}' has 0 matching verdicts in {loc}. Gate check requires at least 1 verdict record.",
            exit_code=2,
        )
    if coll.label_records == 0:
        raise GateCheckError(
            f"REFUSAL: feature '{feature}' has 0 matching labels. Gate check requires at least 1 labeled subject.",
            exit_code=2,
        )

    blocking_reasons: list[str] = []

    # Check threshold_basis per spec §3.3.1 and REV2-07
    threshold_basis = promotion.get("threshold_basis")
    if not threshold_basis or not str(threshold_basis).strip():
        blocking_reasons.append("missing_threshold_basis")

    # 1. Isolation integrity (fail closed; spec §3.3.2)
    if shadow_cfg.get("writes_isolated") is not True:
        blocking_reasons.append("writes_isolated_declared_false")

    enforcer_symbol = shadow_cfg.get("writes_isolated_enforced_by")
    if not enforcer_symbol:
        blocking_reasons.append("enforcer_missing")
    else:
        fn = resolve_enforcer_symbol(str(enforcer_symbol), repo_root=repo_root)
        if fn is None:
            blocking_reasons.append(f"enforcer_unimportable:{enforcer_symbol}")

    isolation_events = coll.isolation_events
    isolation_violations_count = sum(
        1
        for iso in isolation_events
        if iso.get("writes_isolated") is False or bool(iso.get("leaked_paths"))
    )
    # Clean evidence must come from the configured enforcer, not any isolation event.
    has_clean_evidence = any(
        iso.get("writes_isolated") is True
        and isinstance(iso.get("leaked_paths"), list)
        and len(iso["leaked_paths"]) == 0
        and (not enforcer_symbol or iso.get("enforced_by") == enforcer_symbol)
        for iso in isolation_events
    )
    if not has_clean_evidence:
        blocking_reasons.append("no_isolation_evidence")

    max_iso_violations = promotion.get("isolation_violations_max", 0)
    if isolation_violations_count > max_iso_violations:
        blocking_reasons.append("isolation_violation_detected")

    # 2. Sample size gates
    verdicts_total = len(verdicts)
    min_verdicts = promotion.get("min_verdicts")
    if min_verdicts is not None and verdicts_total < min_verdicts:
        blocking_reasons.append(f"insufficient_verdicts:{verdicts_total}/{min_verdicts}")

    if labels_file is not None:
        disallowed = sorted({s for s in coll.labels_file_sources if s not in allowed_sources})
        if disallowed:
            blocking_reasons.append(f"unpermitted_label_sources_present:{','.join(disallowed)}")

    labels_total = len(labels)
    min_labels = promotion.get("min_labels")
    if min_labels is not None and labels_total < min_labels:
        blocking_reasons.append(f"insufficient_labels:{labels_total}/{min_labels}")

    # 3. Shared join and confusion metrics
    conf = confusion(verdicts, labels, positive_label)
    s = summarize(conf, confidence)
    precision = s.precision
    precision_ci_lower = s.precision_ci_lower
    recall = s.recall
    recall_ci_lower = s.recall_ci_lower
    fp_rate = s.fp_rate
    base_rate = s.base_rate

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
    if precision_ci_lower is None or precision_ci_lower <= base_rate:
        if "precision_lower_bound_below_base_rate" not in blocking_reasons:
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
        "tp": s.tp,
        "fp": s.fp,
        "tn": s.tn,
        "fn": s.fn,
        "base_rate": base_rate,
        "precision": round(precision, 4) if precision is not None else None,
        "precision_ci_lower": round(precision_ci_lower, 4) if precision_ci_lower is not None else None,
        "precision_ci_upper": round(s.precision_ci_upper, 4) if s.precision_ci_upper is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "recall_ci_lower": round(recall_ci_lower, 4) if recall_ci_lower is not None else None,
        "recall_ci_upper": round(s.recall_ci_upper, 4) if s.recall_ci_upper is not None else None,
        "fp_rate": round(fp_rate, 4) if fp_rate is not None else None,
        "isolation_violations": isolation_violations_count,
        "invalid_records": conf.invalid_records + coll.unjoinable,
        "malformed_lines": coll.malformed_lines,
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
    verdicts_file: Path | None = None,
    labels_file: Path | None = None,
    mode_state_dir: Path | None = None,
    repo_root: Path | None = None,
    confidence: float = 0.95,
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

    # Resolve log_dir via 5-layer hierarchy if records_dir and overrides not explicitly passed
    provenance: str | None = None
    if records_dir is None and verdicts_file is None and labels_file is None:
        res_log = resolve_log_dir(cli_arg=None, repo_root=root)
        effective_records_dir = res_log.path
        provenance = res_log.provenance
    elif records_dir is not None:
        effective_records_dir = Path(records_dir).resolve()
        provenance = f"resolved log_dir from CLI argument ({effective_records_dir})"
    else:
        effective_records_dir = None

    result = evaluate_gate(
        mode_data,
        effective_records_dir,
        verdicts_file=verdicts_file,
        labels_file=labels_file,
        repo_root=root,
        confidence=confidence,
    )
    return dataclasses.replace(result, log_dir_provenance=provenance)
