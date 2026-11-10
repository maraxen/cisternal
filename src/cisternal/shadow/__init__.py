"""Cisternal shadow-development pattern (spec 261109).

Exports:
- emit_verdict: Emit candidate feature output (shadow.verdict)
- emit_label: Emit ground truth label (shadow.label)
- emit_isolation: Emit actor isolation verification result (shadow.isolation)
- score_feature: Score verdicts against labels with Wilson CI
- check_mode_state: Read-only gate evaluation against mode-state TOML
"""

from __future__ import annotations

from cisternal.shadow.events import emit_isolation, emit_label, emit_verdict
from cisternal.shadow.mode_state import (
    CheckResult,
    GateCheckError,
    check_mode_state,
    evaluate_gate,
    load_mode_state,
)
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
    "check_mode_state",
    "load_mode_state",
    "evaluate_gate",
    "CheckResult",
    "GateCheckError",
]
