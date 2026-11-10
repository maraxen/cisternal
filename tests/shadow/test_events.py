"""Tests for cisternal.shadow telemetry events (AC-1).

Verifies emit_verdict, emit_label, and emit_isolation:
- Return boolean acceptance status (True if accepted, False if uninitialized/dropped).
- Preserve uninitialized library isolation without starting worker threads.
- Emit valid Record objects matching spec §3.1 schemas.
- Obey log level filtering and never-raise contract.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from cisternal.telemetry.exporter import ShadowExporter
from cisternal.telemetry.pipeline import shutdown_pipeline


@pytest.fixture(autouse=True)
def clean_pipeline() -> Any:
    """Ensure clean pipeline state before and after each test."""
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def test_emit_verdict_uninitialized_returns_false() -> None:
    """emit_verdict returns False when pipeline is uninitialized without starting threads."""
    import cisternal.shadow

    res = cisternal.shadow.emit_verdict(
        feature="test_feature",
        subject_key="subj:1",
        verdict={"decision": "pass"},
    )
    assert res is False
    assert cisternal.telemetry.pipeline.get_pipeline() is None


def test_emit_label_uninitialized_returns_false() -> None:
    """emit_label returns False when pipeline is uninitialized."""
    import cisternal.shadow

    res = cisternal.shadow.emit_label(
        feature="test_feature",
        subject_key="subj:1",
        label=True,
    )
    assert res is False
    assert cisternal.telemetry.pipeline.get_pipeline() is None


def test_emit_isolation_uninitialized_returns_false() -> None:
    """emit_isolation returns False when pipeline is uninitialized."""
    import cisternal.shadow

    res = cisternal.shadow.emit_isolation(
        feature="test_feature",
        writes_isolated=True,
        leaked_paths=[],
        enforced_by="tests/test_isolation.py::test_fn",
    )
    assert res is False
    assert cisternal.telemetry.pipeline.get_pipeline() is None


def _wait_for_records(
    spy: ShadowExporter, count: int, name: str | None = None, timeout: float = 2.0
) -> None:
    """Wait until spy collects at least count records (optionally matching name)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matching = [r for r in spy.records if name is None or r.name == name]
        if len(matching) >= count:
            return
        time.sleep(0.005)
    matching = [r for r in spy.records if name is None or r.name == name]
    pytest.fail(f"Expected {count} records matching {name}, got {len(matching)} within {timeout}s")


def test_emit_verdict_initialized() -> None:
    """emit_verdict enqueues valid shadow.verdict record with spec fields."""
    import cisternal.shadow

    spy = ShadowExporter()
    cisternal.init(exporters=[spy])

    t0 = time.time()
    ok = cisternal.shadow.emit_verdict(
        feature="bearings_charter_mapper",
        subject_key="run:01a79c37",
        verdict={"decision": "pass", "confidence": 0.92},
        stage="shadow",
        feature_version="0.2.0",
        inputs_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        extra_note="unit-test",
    )
    assert ok is True

    _wait_for_records(spy, 1, "shadow.verdict")
    shutdown_pipeline()

    assert len(spy.records) >= 1
    rec = next(r for r in spy.records if r.name == "shadow.verdict")
    assert rec.name == "shadow.verdict"
    assert rec.ts >= t0
    assert rec.fields["feature"] == "bearings_charter_mapper"
    assert rec.fields["subject_key"] == "run:01a79c37"
    assert rec.fields["stage"] == "shadow"
    assert rec.fields["feature_version"] == "0.2.0"
    assert rec.fields["verdict"] == {"decision": "pass", "confidence": 0.92}
    assert (
        rec.fields["inputs_sha256"]
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert rec.fields["extra_note"] == "unit-test"


def test_emit_label_valid_sources() -> None:
    """emit_label accepts standard provenance categories and enqueues valid records."""
    import cisternal.shadow

    spy = ShadowExporter()
    cisternal.init(exporters=[spy])

    sources = ["at_work", "owner_confirmed", "retrospective", "frozen_gold"]
    for src in sources:
        ok = cisternal.shadow.emit_label(
            feature="test_eval",
            subject_key=f"item:{src}",
            label="pass",
            label_source=src,
            labeller=f"user_{src}",
            metadata="sample",
        )
        assert ok is True

    _wait_for_records(spy, len(sources), "shadow.label")
    shutdown_pipeline()

    label_recs = [r for r in spy.records if r.name == "shadow.label"]
    assert len(label_recs) == len(sources)
    for rec, src in zip(label_recs, sources):
        assert rec.fields["feature"] == "test_eval"
        assert rec.fields["subject_key"] == f"item:{src}"
        assert rec.fields["label"] == "pass"
        assert rec.fields["label_source"] == src
        assert rec.fields["labeller"] == f"user_{src}"
        assert rec.fields["metadata"] == "sample"


def test_emit_isolation() -> None:
    """emit_isolation enqueues shadow.isolation record with confinement status."""
    import cisternal.shadow

    spy = ShadowExporter()
    cisternal.init(exporters=[spy])

    ok = cisternal.shadow.emit_isolation(
        feature="blast_radius_auto_clear",
        writes_isolated=False,
        leaked_paths=["/tmp/leak.txt", "/tmp/unexpected.log"],
        enforced_by="tests/shadow/test_isolation.py::test_feature_isolation",
    )
    assert ok is True

    _wait_for_records(spy, 1, "shadow.isolation")
    shutdown_pipeline()

    rec = next(r for r in spy.records if r.name == "shadow.isolation")
    assert rec.fields["feature"] == "blast_radius_auto_clear"
    assert rec.fields["writes_isolated"] is False
    assert rec.fields["leaked_paths"] == ["/tmp/leak.txt", "/tmp/unexpected.log"]
    assert rec.fields["enforced_by"] == "tests/shadow/test_isolation.py::test_feature_isolation"


def test_level_filtering() -> None:
    """Events below pipeline min_level return False and are dropped."""
    import cisternal.shadow

    spy = ShadowExporter()
    cisternal.init(exporters=[spy], level=logging.WARNING)

    # INFO is below WARNING -> dropped, returns False
    res_info = cisternal.shadow.emit_verdict(
        feature="test_level",
        subject_key="subj:info",
        verdict=True,
        level=logging.INFO,
    )
    assert res_info is False

    # ERROR is above WARNING -> accepted, returns True
    res_err = cisternal.shadow.emit_verdict(
        feature="test_level",
        subject_key="subj:err",
        verdict=True,
        level=logging.ERROR,
    )
    assert res_err is True

    shutdown_pipeline()

    recs = [r for r in spy.records if r.name == "shadow.verdict"]
    assert len(recs) == 1
    assert recs[0].fields["subject_key"] == "subj:err"
