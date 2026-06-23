"""AC-M9-2: job_span() HPC context helper tests."""

from __future__ import annotations

import time

import pytest

from cisterna import init, job_span
from cisterna.telemetry.exporter import ShadowExporter


@pytest.fixture
def temp_log_dir(tmp_path):
    return tmp_path


@pytest.fixture(autouse=True)
def cleanup():
    yield
    from cisterna.telemetry import pipeline as pm
    import cisterna.telemetry.self_obs as so_mod

    if pm._global_pipeline:
        pm._global_pipeline.shutdown()
        pm._global_pipeline = None

    with so_mod._heartbeat_lock:
        so_mod._heartbeat_thread = None
        so_mod._last_stat = {
            "mtime": None,
            "size": None,
            "ts": None,
            "last_growth_ts": None,
        }
        so_mod._jsonl_path = None

    so_mod._last_ec3_warn = 0.0


class TestJobSpan:
    def test_job_span_sets_task_id_from_myx_job_id(self, temp_log_dir, monkeypatch) -> None:
        monkeypatch.setenv("MYX_JOB_ID", "slurm-12345")
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        with job_span("slurm.run", remote="hpc"):
            time.sleep(0.01)

        time.sleep(0.05)
        span_records = [r for r in shadow.records if r.name.startswith("slurm.run.")]
        assert len(span_records) >= 2
        assert all(r.task_id == "slurm-12345" for r in span_records)

    def test_job_span_falls_back_to_bth_task_id(self, temp_log_dir, monkeypatch) -> None:
        monkeypatch.delenv("MYX_JOB_ID", raising=False)
        monkeypatch.setenv("BTH_TASK_ID", "bth-task-99")
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        with job_span("rsync.push"):
            pass

        time.sleep(0.05)
        start = next(r for r in shadow.records if r.name == "rsync.push.start")
        assert start.task_id == "bth-task-99"

    def test_job_span_sets_run_uuid_from_env(self, temp_log_dir, monkeypatch) -> None:
        monkeypatch.setenv("MYX_RUN_UUID", "run-abc")
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow])

        with job_span("cluster.step"):
            pass

        time.sleep(0.05)
        end = next(r for r in shadow.records if r.name == "cluster.step.end")
        assert end.run_uuid == "run-abc"
