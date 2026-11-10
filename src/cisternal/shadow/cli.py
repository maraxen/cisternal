"""Cisternal shadow CLI commands (spec §3.2).

Provides:
- shadow score <feature>: Join and score verdicts against labels with Wilson CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import cyclopts

from cisternal.shadow.mode_state import GateCheckError, check_mode_state
from cisternal.shadow.resolution import ResolutionError
from cisternal.shadow.scoring import ScoringRefusalError, score_feature

shadow_app = cyclopts.App(
    name="shadow",
    help="Shadow-development lifecycle commands (score, check).",
    version_flags=[],
)


@shadow_app.command(name="score")
def shadow_score(
    feature: str,
    *,
    records_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--records-dir"],
            help="Directory containing events.*.jsonl files.",
        ),
    ] = None,
    verdicts_file: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--verdicts-file"],
            help="Specific verdicts JSONL file override.",
        ),
    ] = None,
    labels_file: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--labels-file"],
            help="Specific labels JSONL file override.",
        ),
    ] = None,
    positive_label: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--positive-label"],
            help="Positive label definition (default: true).",
        ),
    ] = None,
    confidence: Annotated[
        float,
        cyclopts.Parameter(
            name=["--confidence"],
            help="Confidence level for Wilson intervals (default: 0.95).",
        ),
    ] = 0.95,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON report.",
        ),
    ] = False,
) -> None:
    """Score shadow verdicts against ground truth labels."""
    resolved_pos: Any = True
    if positive_label is not None:
        low = positive_label.strip().lower()
        if low in ("true", "1", "yes", "pass", "clean"):
            resolved_pos = True
        elif low in ("false", "0", "no", "fail", "drifted"):
            resolved_pos = False
        else:
            resolved_pos = positive_label

    try:
        result = score_feature(
            feature=feature,
            records_dir=records_dir,
            verdicts_file=verdicts_file,
            labels_file=labels_file,
            positive_label=resolved_pos,
            confidence=confidence,
        )
    except ScoringRefusalError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc

    if json_output:
        print(json.dumps(result.to_dict(), indent=2))
        return

    # Text report
    prec_str = (
        f"{result.precision:.4f} [Wilson {confidence*100:.0f}% CI: {result.precision_ci_lower:.4f} .. {result.precision_ci_upper:.4f}]"
        if result.precision is not None and result.precision_ci_lower is not None and result.precision_ci_upper is not None
        else "n/a (no positive predictions)"
    )
    rec_str = (
        f"{result.recall:.4f} [Wilson {confidence*100:.0f}% CI: {result.recall_ci_lower:.4f} .. {result.recall_ci_upper:.4f}]"
        if result.recall is not None and result.recall_ci_lower is not None and result.recall_ci_upper is not None
        else "n/a (no positive labels)"
    )
    fpr_str = f"{result.fp_rate:.4f}" if result.fp_rate is not None else "n/a (no negative labels)"
    exceeds_str = (
        "Yes" if result.precision_exceeds_base_rate is True
        else ("No" if result.precision_exceeds_base_rate is False else "n/a")
    )

    print(f"Feature: {result.feature}")
    print(f"  Verdicts Total:      {result.verdicts_total} (Unlabelled: {result.unlabelled_verdicts})")
    print(f"  Labels Total:        {result.labels_total} (Invalid Records: {result.invalid_records})")
    print(f"  Confusion Matrix:    TP={result.tp}, FP={result.fp}, TN={result.tn}, FN={result.fn}")
    print(f"  Base Rate:           {result.base_rate:.4f}")
    print(f"  Precision:           {prec_str}")
    print(f"  Recall:              {rec_str}")
    print(f"  False Positive Rate: {fpr_str}")
    print(f"  Precision > BaseRate: {exceeds_str}")


@shadow_app.command(name="check")
def shadow_check(
    feature_or_path: str,
    *,
    records_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--records-dir"],
            help="Directory containing events.*.jsonl files.",
        ),
    ] = None,
    mode_state_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--mode-state-dir"],
            help="Directory containing mode-state TOML files.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON report.",
        ),
    ] = False,
) -> None:
    """Evaluate promotion readiness of a shadow feature (read-only)."""
    try:
        result = check_mode_state(
            feature_or_path=feature_or_path,
            records_dir=records_dir,
            mode_state_dir=mode_state_dir,
        )
    except (GateCheckError, ResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc

    if json_output:
        print(json.dumps(result.to_dict(), indent=2))
        raise SystemExit(result.exit_code)

    # Human-readable report
    status_str = "PERMITTED" if result.promotion_permitted else "BLOCKED"
    print(f"Feature: {result.feature} (Stage: {result.current_stage} -> Target: {result.target_stage})")
    print(f"  Promotion Status: {status_str} (Exit Code: {result.exit_code})")
    if result.blocking_reasons:
        print("  Blocking Reasons:")
        for reason in result.blocking_reasons:
            print(f"    - {reason}")
    else:
        print("  Blocking Reasons: none")

    m = result.metrics
    print("  Metrics:")
    print(f"    Verdicts Total: {m.get('verdicts_total')} | Labels Total: {m.get('labels_total')}")
    print(f"    Confusion Matrix: TP={m.get('tp')}, FP={m.get('fp')}, TN={m.get('tn')}, FN={m.get('fn')}")
    print(f"    Base Rate: {m.get('base_rate')}")
    print(f"    Precision: {m.get('precision')} [CI: {m.get('precision_ci_lower')} .. {m.get('precision_ci_upper')}]")
    print(f"    Recall:    {m.get('recall')} [CI: {m.get('recall_ci_lower')} .. {m.get('recall_ci_upper')}]")
    print(f"    FP Rate:   {m.get('fp_rate')}")
    print(f"    Isolation Violations: {m.get('isolation_violations')}")

    raise SystemExit(result.exit_code)
