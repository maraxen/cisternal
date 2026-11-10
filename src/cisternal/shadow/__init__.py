"""Cisternal shadow-development pattern (spec 261109).

Exports:
- emit_verdict: Emit candidate feature output (shadow.verdict)
- emit_label: Emit ground truth label (shadow.label)
- emit_isolation: Emit actor isolation verification result (shadow.isolation)
"""

from __future__ import annotations

from cisternal.shadow.events import emit_isolation, emit_label, emit_verdict

__all__ = [
    "emit_verdict",
    "emit_label",
    "emit_isolation",
]
