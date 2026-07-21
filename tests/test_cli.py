"""Tests for cisternal CLI adapter: AC-CLI acceptance criteria."""

import time
from pathlib import Path
import tempfile

import pytest

from cisternal import init
from cisternal.adapters.cli import timed_command
from cisternal.telemetry.exporter import ShadowExporter


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for JSONL logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def cleanup_pipeline():
    """Clean up pipeline between tests."""
    yield
    # Shutdown any existing pipeline
    from cisternal.telemetry import pipeline as pipeline_module
    from cisternal.telemetry import self_obs as self_obs_module

    if pipeline_module._global_pipeline is not None:
        pipeline_module._global_pipeline.shutdown()
        pipeline_module._global_pipeline = None

    # Reset heartbeat state
    with self_obs_module._heartbeat_lock:
        self_obs_module._heartbeat_thread = None
        self_obs_module._last_stat = {
            "mtime": None,
            "size": None,
            "ts": None,
            "last_growth_ts": None,
        }
        self_obs_module._jsonl_path = None


class TestACCli1:
    """AC-CLI-1: timed_command decorator emits cli.cmd_start and cli.cmd_end."""

    def test_timed_command_basic(self, temp_log_dir):
        """Given a function decorated with @timed_command(); When called; Then cli.cmd_start and cli.cmd_end appear."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @timed_command()
        def my_command():
            return "success"

        result = my_command()
        time.sleep(0.1)  # Allow async export

        assert result == "success"

        # Filter out heartbeats
        cli_records = [r for r in shadow.records if r.name.startswith("cli.")]
        assert len(cli_records) >= 2, (
            f"Expected cli.cmd_start and cli.cmd_end, got {[r.name for r in cli_records]}"
        )

        # Check cmd_start
        start_records = [r for r in cli_records if r.name == "cli.cmd_start"]
        assert len(start_records) >= 1
        assert start_records[0].fields["cmd"] == "my_command"

        # Check cmd_end
        end_records = [r for r in cli_records if r.name == "cli.cmd_end"]
        assert len(end_records) >= 1
        assert end_records[0].fields["cmd"] == "my_command"
        assert "duration_ms" in end_records[0].fields
        assert end_records[0].fields["ok"] is True

    def test_timed_command_with_custom_name(self, temp_log_dir):
        """Given @timed_command("custom_name"); When called; Then cmd field matches custom_name."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @timed_command("custom_cmd")
        def some_function():
            return 42

        result = some_function()
        time.sleep(0.1)

        assert result == 42

        cli_records = [r for r in shadow.records if r.name.startswith("cli.")]
        start_records = [r for r in cli_records if r.name == "cli.cmd_start"]
        end_records = [r for r in cli_records if r.name == "cli.cmd_end"]

        assert len(start_records) >= 1
        assert start_records[0].fields["cmd"] == "custom_cmd"
        assert len(end_records) >= 1
        assert end_records[0].fields["cmd"] == "custom_cmd"

    def test_timed_command_exception_reraises(self, temp_log_dir):
        """Given @timed_command(); When function raises; Then cli.cmd_end emitted with ok=False and exception re-raised."""
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=0.05)

        @timed_command()
        def failing_command():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_command()

        time.sleep(0.1)

        cli_records = [r for r in shadow.records if r.name.startswith("cli.")]
        start_records = [r for r in cli_records if r.name == "cli.cmd_start"]
        end_records = [r for r in cli_records if r.name == "cli.cmd_end"]

        assert len(start_records) >= 1
        assert start_records[0].fields["cmd"] == "failing_command"

        assert len(end_records) >= 1
        assert end_records[0].fields["cmd"] == "failing_command"
        assert end_records[0].fields["ok"] is False
        assert end_records[0].fields["exc_type"] == "ValueError"
