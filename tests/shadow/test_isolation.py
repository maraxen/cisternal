"""Tests for cisternal.shadow.isolation and prove_isolation helper (AC-4).

Verifies:
- Clean execution: identical return values, identical live writes, shadow writes only to log -> passed=True.
- Divergence in return values -> live_output_identical=False, passed=False.
- Divergence in live filesystem outputs -> live_output_identical=False, passed=False.
- Leaked writes outside shadow_log_dir and live_roots -> leaked_paths populated, passed=False.
- Telemetry emission of shadow.isolation record.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

import cisternal
from cisternal.shadow.isolation import (
    prove_isolation,
)
from cisternal.telemetry.exporter import ShadowExporter
from cisternal.telemetry.pipeline import shutdown_pipeline


@pytest.fixture(autouse=True)
def clean_pipeline() -> Any:
    shutdown_pipeline()
    yield
    shutdown_pipeline()


def test_prove_isolation_clean_success(tmp_path: Path) -> None:
    """Live and shadow produce identical returns and identical file writes in live_roots."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()

    def live_actor() -> dict[str, Any]:
        out_file = live_dir / "result.txt"
        out_file.write_text("legitimate live computation", encoding="utf-8")
        return {"status": "ok", "count": 42}

    def shadow_actor() -> dict[str, Any]:
        out_file = live_dir / "result.txt"
        out_file.write_text("legitimate live computation", encoding="utf-8")
        # Allowed shadow write
        log_file = shadow_log / "events.jsonl"
        log_file.write_text('{"verdict": "pass"}\n', encoding="utf-8")
        return {"status": "ok", "count": 42}

    res = prove_isolation(
        live_actor,
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
    )

    assert res.passed is True
    assert res.live_output_identical is True
    assert res.leaked_paths == []
    assert res.actor_output == {"status": "ok", "count": 42}
    assert res.shadow_output == {"status": "ok", "count": 42}


def test_prove_isolation_detects_return_value_divergence(tmp_path: Path) -> None:
    """Return value divergence causes live_output_identical=False and passed=False."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()

    def live_actor() -> int:
        return 100

    def shadow_actor() -> int:
        return 101

    res = prove_isolation(
        live_actor,
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
    )

    assert res.passed is False
    assert res.live_output_identical is False


def test_prove_isolation_detects_filesystem_divergence_in_live_roots(tmp_path: Path) -> None:
    """File content divergence in live_roots causes live_output_identical=False and passed=False."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()

    def live_actor() -> str:
        (live_dir / "output.data").write_text("version 1", encoding="utf-8")
        return "done"

    def shadow_actor() -> str:
        (live_dir / "output.data").write_text("version 2 (mutated)", encoding="utf-8")
        return "done"

    res = prove_isolation(
        live_actor,
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
    )

    assert res.passed is False
    assert res.live_output_identical is False


def test_prove_isolation_detects_leaked_write_outside_log(tmp_path: Path) -> None:
    """Unauthorized write outside live_roots and shadow_log_dir is flagged in leaked_paths."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()

    leak_file = scratch_dir / "leak.txt"

    def live_actor() -> str:
        return "clean"

    def shadow_actor() -> str:
        # Unauthorized write to scratch_dir
        leak_file.write_text("unauthorized shadow side-effect", encoding="utf-8")
        return "clean"

    res = prove_isolation(
        live_actor,
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        check_roots=[scratch_dir],
    )

    assert res.passed is False
    assert leak_file.resolve() in [p.resolve() for p in res.leaked_paths]


def test_prove_isolation_emits_telemetry_event(tmp_path: Path) -> None:
    """prove_isolation emits shadow.isolation event when feature is provided."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()

    spy = ShadowExporter()
    cisternal.init(exporters=[spy])

    def live_actor() -> str:
        return "ok"

    def shadow_actor() -> str:
        return "ok"

    res = prove_isolation(
        live_actor,
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        feature="test_iso_telem",
        enforced_by="tests/shadow/test_isolation.py::test_prove_isolation_emits_telemetry_event",
    )
    assert res.passed is True

    # Allow worker thread to drain
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        matching = [r for r in spy.records if r.name == "shadow.isolation"]
        if len(matching) >= 1:
            break
        time.sleep(0.005)
    shutdown_pipeline()

    iso_records = [r for r in spy.records if r.name == "shadow.isolation"]
    assert len(iso_records) >= 1
    rec = iso_records[0]
    assert rec.fields["feature"] == "test_iso_telem"
    assert rec.fields["writes_isolated"] is True
    assert rec.fields["leaked_paths"] == []
    assert (
        rec.fields["enforced_by"]
        == "tests/shadow/test_isolation.py::test_prove_isolation_emits_telemetry_event"
    )
