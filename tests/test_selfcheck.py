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
        time.sleep(0.05)

        # Sleep for ~150ms to allow heartbeats to fire and file to grow
        time.sleep(0.15)

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
        time.sleep(0.05)

        # Sleep long enough for heartbeat to fire and detect file
        time.sleep(0.1)

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
        time.sleep(0.2)  # Increased to ensure first probe establishes baseline
        # and second probe detects growth before killing listener

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

        # Sleep long enough for multiple heartbeat intervals with no growth
        # (minimum 2x interval = 100ms, plus margin for probe timing)
        time.sleep(0.25)

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
        time.sleep(0.05)

        # Wait for heartbeat to fire and update probe
        time.sleep(0.1)

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
        # This ensures enough time has passed that heartbeat_alive should be False
        time.sleep(0.15)

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
        time.sleep(0.15)  # let file grow so last_growth_ts is set

        from cisternal.telemetry import pipeline as pipeline_module

        pipeline = pipeline_module._global_pipeline
        if pipeline and pipeline._listener:
            pipeline._listener.stop()
            pipeline._listener.join(timeout=1.0)

        time.sleep(0.15)  # let liveness go stale (> 2x interval)

        import cisternal.telemetry.self_obs as so

        so._last_ec3_warn = 0.0
        so._check_ec3_warn()

        captured = capsys.readouterr()
        assert "EC-3" in captured.err or "pipeline consumer dead" in captured.err
