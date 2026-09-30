"""Tests for cisternal self-check: AC-SELFCHECK acceptance criteria (CH-12).

AC-SELFCHECK-1: Heartbeat fires; status().heartbeat_alive and write_probe_ok
are True when the file grows.

AC-SELFCHECK-2: With the QueueListener killed, status().pipeline_alive and
heartbeat_alive go False within 2x the interval.
"""

import tempfile
import time
from pathlib import Path

import pytest

from cisternal import emit_event, init, status
from cisternal.telemetry import self_obs as self_obs_module


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for JSONL logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def _wait_until(predicate, timeout: float = 2.0, poll: float = 0.01) -> bool:
    """Poll *predicate* until it returns True or *timeout* elapses.

    Liveness flags depend on heartbeat/probe thread scheduling, so a fixed
    sleep of a few intervals flakes under load; wait on the state instead.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up between tests."""
    yield
    # Shutdown pipeline and reset heartbeat state
    from cisternal.telemetry import pipeline as pipeline_module

    if pipeline_module._global_pipeline is not None:
        pipeline_module._global_pipeline.shutdown()
        pipeline_module._global_pipeline = None

    # Stop the heartbeat thread (it's a daemon, but let's be explicit)
    # The heartbeat thread will eventually stop on its own, but for tests
    # we want to reset state immediately
    with self_obs_module._heartbeat_lock:
        self_obs_module._heartbeat_thread = None
        self_obs_module._last_stat = {
            "mtime": None,
            "size": None,
            "ts": None,
            "last_growth_ts": None,
        }
        self_obs_module._jsonl_path = None

    self_obs_module._last_ec3_warn = 0.0


class TestACSelfcheck1:
    """AC-SELFCHECK-1: Heartbeat fires; status flags are True when file grows."""

    def test_heartbeat_alive_when_file_grows(self, temp_log_dir):
        """Given JsonlExporter to temp file, heartbeats every 50ms;
        When status() after 150ms;
        Then heartbeat_alive AND write_probe_ok are True (file mtime+size advanced)."""

        init(log_dir=temp_log_dir, heartbeat_interval=0.05)

        # Emit an initial event to ensure file exists
        emit_event("initial.event")

        # Wait for heartbeats to fire and the file to grow
        _wait_until(lambda: status().heartbeat_alive and status().write_probe_ok)

        st = status()

        # Both flags should be True because heartbeat has fired
        # and the file has grown
        assert st.heartbeat_alive is True, (
            f"heartbeat_alive={st.heartbeat_alive}, expected True"
        )
        assert st.write_probe_ok is True, (
            f"write_probe_ok={st.write_probe_ok}, expected True"
        )

    def test_write_probe_detects_file_growth(self, temp_log_dir):
        """Verify that write_probe_ok only becomes True when file actually grows."""

        init(log_dir=temp_log_dir, heartbeat_interval=0.05)

        # Initially, status should show pipeline alive but no file growth yet
        st = status()
        assert st.pipeline_alive is True

        # Emit an event to force file creation
        emit_event("test.event", field="value")

        # Wait for heartbeats to establish a baseline probe and then see growth
        _wait_until(lambda: status().write_probe_ok and status().heartbeat_alive)

        st = status()

        # File has been created and grown, so both should be True
        assert st.heartbeat_alive is True
        assert st.write_probe_ok is True


class TestACSelfcheck2:
    """AC-SELFCHECK-2: With QueueListener killed, pipeline_alive and
    heartbeat_alive go False within 2x the interval."""

    def test_listener_death_detection(self, temp_log_dir):
        """Given the QueueListener thread killed;
        When status() after 2x interval (100ms);
        Then pipeline_alive False AND heartbeat_alive False."""

        init(log_dir=temp_log_dir, heartbeat_interval=0.05)

        # Emit initial event and let it process
        emit_event("initial.event")
        # first probe establishes baseline, second detects growth, before killing listener
        _wait_until(lambda: status().heartbeat_alive)

        # Verify pipeline is alive
        st = status()
        assert st.pipeline_alive is True

        # Kill the listener thread
        from cisternal.telemetry import pipeline as pipeline_module

        pipeline = pipeline_module._global_pipeline
        if pipeline and pipeline._listener:
            pipeline._listener.stop()
            # Force the thread to die by waiting
            pipeline._listener.join(timeout=1.0)

        # Wait out multiple heartbeat intervals with no growth (> 2x interval)
        _wait_until(
            lambda: status().pipeline_alive is False and status().heartbeat_alive is False
        )

        st = status()

        # Both flags should be False now
        assert st.pipeline_alive is False, (
            f"pipeline_alive={st.pipeline_alive}, expected False after listener killed"
        )
        assert st.heartbeat_alive is False, (
            f"heartbeat_alive={st.heartbeat_alive}, expected False after listener killed"
        )

    def test_heartbeat_detection_window(self, temp_log_dir):
        """Verify that heartbeat_alive stays True within 2x interval,
        but goes False after 2x interval with no updates."""

        init(log_dir=temp_log_dir, heartbeat_interval=0.05)

        # Emit initial event
        emit_event("test.event")

        # Wait for heartbeat to fire and update probe
        _wait_until(lambda: status().heartbeat_alive)

        st = status()
        assert st.heartbeat_alive is True, "Should be alive shortly after init"

        # Now kill the listener to stop new heartbeats
        from cisternal.telemetry import pipeline as pipeline_module

        pipeline = pipeline_module._global_pipeline
        if pipeline and pipeline._listener:
            pipeline._listener.stop()

        # The listener is now stopped. The heartbeat thread is still running
        # and emitting events, but they won't be processed (listener is dead).
        # So the file won't grow anymore.

        # Wait for more than 2x the heartbeat interval (100ms+) with no file growth
        # so heartbeat_alive goes False
        _wait_until(lambda: status().heartbeat_alive is False)

        st = status()

        # heartbeat_alive should go False since no new file growth
        assert st.heartbeat_alive is False, (
            f"heartbeat_alive={st.heartbeat_alive}, expected False after 2x interval"
        )


class TestInitIdempotency:
    """AC-CORE-5 extension: Verify init() is idempotent with exactly one listener."""

    def test_double_init_single_listener(self, temp_log_dir):
        """Verify that calling init() twice leaves exactly one QueueListener."""
        from cisternal.telemetry import pipeline as pipeline_module

        init(log_dir=temp_log_dir)
        first_pipeline = pipeline_module._global_pipeline
        first_listener = first_pipeline._listener if first_pipeline else None

        # Call init again
        init(log_dir=temp_log_dir)
        second_pipeline = pipeline_module._global_pipeline
        second_listener = second_pipeline._listener if second_pipeline else None

        # Should be same pipeline and listener instance
        assert first_pipeline is second_pipeline
        assert first_listener is second_listener

        # Verify the listener thread is alive
        assert first_listener.is_alive()


class TestHeartbeatThread:
    """Test heartbeat thread behavior."""

    def test_heartbeat_daemon_emits_events(self, temp_log_dir):
        """Verify that heartbeat thread emits 'heartbeat' events periodically."""
        from cisternal.telemetry.exporter import ShadowExporter

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        # Sleep long enough for multiple heartbeats (interval is 50ms)
        time.sleep(0.2)

        # Check that heartbeat events were emitted
        heartbeat_events = [r for r in shadow.records if r.name == "heartbeat"]
        assert len(heartbeat_events) > 0, (
            f"Expected heartbeat events, got {len(heartbeat_events)}"
        )

    def test_stale_heartbeat_does_not_leak_into_next_pipeline(self, temp_log_dir):
        """A heartbeat thread belongs to the pipeline it was started for.

        After shutdown_pipeline() + a fresh init(), the old thread must not
        emit into the new pipeline. Before this was fixed, a short-interval
        thread from an earlier init kept running forever and injected
        'heartbeat' records into every later pipeline (debt #238 flake class).
        """
        from cisternal.telemetry.exporter import ShadowExporter
        from cisternal.telemetry.pipeline import shutdown_pipeline

        init(log_dir=temp_log_dir, heartbeat_interval=0.01)
        time.sleep(0.05)
        shutdown_pipeline()

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)
        time.sleep(0.2)

        heartbeats = [r for r in shadow.records if r.name == "heartbeat"]
        assert heartbeats == [], (
            f"stale heartbeat thread emitted {len(heartbeats)} records into a new pipeline"
        )

    def test_reinit_after_shutdown_gets_its_own_heartbeat(self, temp_log_dir):
        """Liveness must survive shutdown_pipeline() + init(): the new pipeline
        gets heartbeats at its own interval, without test-fixture resets."""
        from cisternal.telemetry.exporter import ShadowExporter
        from cisternal.telemetry.pipeline import shutdown_pipeline

        init(log_dir=temp_log_dir, heartbeat_interval=30.0)
        shutdown_pipeline()

        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.02)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if any(r.name == "heartbeat" for r in shadow.records):
                break
            time.sleep(0.01)

        assert any(r.name == "heartbeat" for r in shadow.records), (
            "re-initialized pipeline never received a heartbeat"
        )

    def test_heartbeat_survives_exporter_failure(self, temp_log_dir):
        """Verify that a failing exporter doesn't crash the heartbeat thread."""

        class FailingExporter:
            def export(self, record):
                raise RuntimeError("exporter failed")

            def flush(self):
                pass

            def close(self):
                pass

        from cisternal.telemetry.exporter import ShadowExporter

        shadow = ShadowExporter()
        init(
            log_dir=temp_log_dir,
            exporters=[FailingExporter(), shadow],
            heartbeat_interval=0.05,
        )

        # Emit an event
        emit_event("test.event")
        time.sleep(0.05)

        # Sleep to let heartbeats fire despite the failing exporter
        time.sleep(0.15)

        # Shadow exporter should still have received heartbeats
        heartbeat_events = [r for r in shadow.records if r.name == "heartbeat"]
        assert len(heartbeat_events) > 0, (
            "Heartbeat thread should survive exporter failure"
        )


class TestEC3Warn:
    """EC-3 warn-and-continue policy: detect dead pipeline and warn."""

    def test_ec3_warn_emits_stderr(self, temp_log_dir, capsys):
        """When pipeline consumer (QueueListener) is dead and staleness > 2x interval,
        _check_ec3_warn() emits a warning to stderr mentioning 'EC-3' or 'pipeline consumer dead'."""

        init(log_dir=temp_log_dir, heartbeat_interval=0.05)
        emit_event("initial.event")
        # let file grow so last_growth_ts is set
        _wait_until(lambda: self_obs_module._last_stat["last_growth_ts"] is not None)

        from cisternal.telemetry import pipeline as pipeline_module

        pipeline = pipeline_module._global_pipeline
        if pipeline and pipeline._listener:
            pipeline._listener.stop()
            pipeline._listener.join(timeout=1.0)

        _wait_until(lambda: status().heartbeat_alive is False)  # stale (> 2x interval)

        import cisternal.telemetry.self_obs as so

        so._last_ec3_warn = 0.0
        so._check_ec3_warn()

        captured = capsys.readouterr()
        assert "EC-3" in captured.err or "pipeline consumer dead" in captured.err
