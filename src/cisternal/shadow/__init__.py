"""Cisternal shadow-development pattern (spec 261109).

Exports:
- emit_verdict: Emit candidate feature output (shadow.verdict)
- emit_label: Emit ground truth label (shadow.label)
- emit_isolation: Emit actor isolation verification result (shadow.isolation)
- score_feature: Score verdicts against labels with Wilson CI
"""

from __future__ import annotations

from cisternal.shadow.events import emit_isolation, emit_label, emit_verdict
from cisternal.shadow.scoring import (
    ScoringRefusalError,
    ScoringResult,
    compute_wilson_interval,
    score_feature,
)

__all__ = [
    "emit_verdict",
    "emit_label",
    "emit_isolation",
    "score_feature",
    "compute_wilson_interval",
    "ScoringResult",
    "ScoringRefusalError",
]
