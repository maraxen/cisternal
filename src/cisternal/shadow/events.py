"""Shadow telemetry events emission (spec §3.1).

Provides non-blocking emit functions for:
- shadow.verdict: candidate feature outputs
- shadow.label: ground-truth labels with provenance
- shadow.isolation: actor isolation audit verification results
"""

from __future__ import annotations

import dataclasses
import logging
import sys
import time
from typing import Any

from cisternal.telemetry.context import _build_record
from cisternal.telemetry.pipeline import _normalize_level, get_pipeline


def _emit_shadow_record(name: str, level: int | str | None, fields: dict[str, Any]) -> bool:
    """Emit a shadow record through the telemetry pipeline.

    Returns:
        True means the record was enqueued, not written. False if the
        pipeline is uninitialized, shut down, full, or the event is below
        min_level. Never raises.
    """
    try:
        pipeline = get_pipeline()
        if pipeline is None:
            return False

        severity = _normalize_level(level)
        if severity is None:
            severity = logging.INFO

        min_level = getattr(pipeline, "min_level", None)
        if min_level is not None and severity < min_level:
            return False

        record = _build_record(name, ts=time.time(), **fields)
        if record is None:
            return False

        if severity != record.severity:
            record = dataclasses.replace(record, severity=severity)

        old_emitted = pipeline.events_emitted
        pipeline.emit(record)
        return pipeline.events_emitted > old_emitted
    except Exception as exc:
        print(f"[cisternal] emit shadow record ({name!r}) failed: {exc}", file=sys.stderr)
        return False


def emit_verdict(
    feature: str,
    subject_key: str,
    verdict: dict[str, Any] | bool | str | int,
    *,
    stage: str = "shadow",
    feature_version: str = "0.1.0",
    inputs_sha256: str = "",
    level: int | str | None = None,
    **extra_fields: Any,
) -> bool:
    """Emit a shadow.verdict event for a feature evaluation.

    Args:
        feature: Unique feature identifier slug.
        subject_key: Item correlation key (<entity_type>:<id>).
        verdict: Candidate output payload (dict, bool, str, or int).
        stage: Current lifecycle ladder stage (off, shadow, advisory, enforce).
        feature_version: Version identifier or content hash of candidate logic.
        inputs_sha256: SHA-256 hash of the exact input payload fed to the feature.
        level: Optional log level severity override.
        **extra_fields: Additional domain metadata attached to payload fields.

    Returns:
        True means the record was enqueued, not written. False otherwise.
        Never raises.
    """
    fields: dict[str, Any] = {
        "feature": feature,
        "subject_key": subject_key,
        "verdict": verdict,
        "stage": stage,
        "feature_version": feature_version,
        "inputs_sha256": inputs_sha256,
        **extra_fields,
    }
    return _emit_shadow_record("shadow.verdict", level, fields)


def emit_label(
    feature: str,
    subject_key: str,
    label: Any,
    *,
    label_source: str = "at_work",
    labeller: str = "agent",
    level: int | str | None = None,
    **extra_fields: Any,
) -> bool:
    """Emit a shadow.label event attaching ground truth to a subject_key.

    Args:
        feature: Unique feature identifier slug matching the verdict.
        subject_key: Item correlation key matching the verdict.
        label: Ground truth label value.
        label_source: Provenance category (at_work, owner_confirmed, retrospective, frozen_gold).
        labeller: Identifier of agent or user who authored the label.
        level: Optional log level severity override.
        **extra_fields: Additional domain metadata attached to payload fields.

    Returns:
        True means the record was enqueued, not written. False otherwise.
        Never raises.
    """
    fields: dict[str, Any] = {
        "feature": feature,
        "subject_key": subject_key,
        "label": label,
        "label_source": label_source,
        "labeller": labeller,
        **extra_fields,
    }
    return _emit_shadow_record("shadow.label", level, fields)


def emit_isolation(
    feature: str,
    writes_isolated: bool,
    leaked_paths: list[str],
    enforced_by: str,
    *,
    level: int | str | None = None,
    **extra_fields: Any,
) -> bool:
    """Emit a shadow.isolation audit event recording actor side-effect confinement.

    Args:
        feature: Unique feature identifier slug.
        writes_isolated: True if live output was identical and no writes leaked.
        leaked_paths: List of file paths written or modified outside allowed dirs.
        enforced_by: Enforcer test symbol (<relative_path>::<symbol_name>).
        level: Optional log level severity override.
        **extra_fields: Additional domain metadata attached to payload fields.

    Returns:
        True means the record was enqueued, not written. False otherwise.
        Never raises.
    """
    fields: dict[str, Any] = {
        "feature": feature,
        "writes_isolated": writes_isolated,
        "leaked_paths": leaked_paths,
        "enforced_by": enforced_by,
        **extra_fields,
    }
    return _emit_shadow_record("shadow.isolation", level, fields)
