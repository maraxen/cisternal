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
