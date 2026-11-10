"""Tests for cisternal usage derived-data directory resolver and atomic JSONL writer."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import pytest

from cisternal.usage.paths import (
    MAX_FILE_SIZE_BYTES,
    MAX_RECORD_LINE_BYTES,
    TRUNCATION_MARKER,
    atomic_append_jsonl,
    resolve_sessions_dir,
)


def _concurrency_worker(args: tuple[str, int, int]) -> int:
    path_str, worker_id, count = args
    path = Path(path_str)
    success = 0
    for i in range(count):
        rec = {
            "worker": worker_id,
            "seq": i,
            "message": f"Worker {worker_id} iteration {i} payload " + "x" * 200,
        }
        if atomic_append_jsonl(path, rec):
            success += 1
    return success


def _user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> Path:
    """Point XDG_CONFIG_HOME at tmp and write ``sessions_dir = value`` (layer 4)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    config = tmp_path / "cfg" / "cisternal" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'sessions_dir = "{value}"\n', encoding="utf-8")
    return config


class TestResolveSessionsDir:
    """Test the 5-layer precedence resolver for derived session directories."""

    def test_layer1_explicit_arg_overrides_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        explicit = tmp_path / "explicit_dir"
        monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", str(tmp_path / "env_dir"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_dir"))

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "toml_dir"\n', encoding="utf-8"
        )

        resolved, layer = resolve_sessions_dir(data_dir=explicit, project_dir=tmp_path)
        assert resolved == explicit.resolve()
        assert layer == "argument"

    @pytest.mark.parametrize("off_val", ["off", "OFF", "", "   ", "  off  "])
    def test_layer1_explicit_arg_off(self, off_val: str, tmp_path: Path) -> None:
        resolved, layer = resolve_sessions_dir(data_dir=off_val, project_dir=tmp_path)
        assert resolved is None
        assert layer == "off"

    def test_layer2_env_var_wins_over_pyproject_and_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_dir = tmp_path / "env_sessions"
        monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", str(env_dir))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "toml_sessions"\n', encoding="utf-8"
        )

        resolved, layer = resolve_sessions_dir(data_dir=None, project_dir=tmp_path)
        assert resolved == env_dir.resolve()
        assert layer == "$CISTERNAL_SESSIONS_DIR"

    @pytest.mark.parametrize("off_val", ["off", "OFF", "", "  off  "])
    def test_layer2_env_var_off(
        self, off_val: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", off_val)
        resolved, layer = resolve_sessions_dir(data_dir=None, project_dir=tmp_path)
        assert resolved is None
        assert layer == "off"

    def test_layer3_cli_mode_pyproject_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "custom_sessions"\n', encoding="utf-8"
        )

        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=False, project_dir=tmp_path
        )
        assert resolved == (tmp_path / "custom_sessions").resolve()
        assert layer.startswith("[tool.cisternal]")
        assert str(pyproject) in layer

    def test_layer3_cli_mode_pyproject_walkup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = ".sessions"\n', encoding="utf-8"
        )

        nested_dir = tmp_path / "src" / "pkg" / "nested"
        nested_dir.mkdir(parents=True)

        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=False, project_dir=nested_dir
        )
        assert resolved == (tmp_path / ".sessions").resolve()
        assert layer.startswith("[tool.cisternal]")

    def test_layer3_pyproject_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "off"\n', encoding="utf-8"
        )

        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=False, project_dir=tmp_path
        )
        assert resolved is None
        assert layer == "off"

    def test_layer3_hook_mode_with_claude_project_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        real_project = tmp_path / "real_project"
        real_project.mkdir()
        real_pyproject = real_project / "pyproject.toml"
        real_pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "real_sessions"\n', encoding="utf-8"
        )

        decoy_dir = tmp_path / "decoy_cwd"
        decoy_dir.mkdir()
        decoy_pyproject = decoy_dir / "pyproject.toml"
        decoy_pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "decoy_sessions"\n', encoding="utf-8"
        )

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(real_project))
        monkeypatch.chdir(decoy_dir)

        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=True, project_dir=None
        )
        assert resolved == (real_project / "real_sessions").resolve()
        assert str(real_pyproject) in layer

    def test_layer3_hook_mode_without_claude_project_dir_skips_layer3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        config = _user_config(tmp_path, monkeypatch, str(tmp_path / "xdg" / "cisternal" / "sessions"))

        decoy_dir = tmp_path / "decoy_cwd"
        decoy_dir.mkdir()
        decoy_pyproject = decoy_dir / "pyproject.toml"
        decoy_pyproject.write_text(
            '[tool.cisternal]\nsessions_dir = "decoy_sessions"\n', encoding="utf-8"
        )

        monkeypatch.chdir(decoy_dir)

        # In hook mode without $CLAUDE_PROJECT_DIR, Layer 3 MUST BE SKIPPED (GAP-26)
        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=True, project_dir=None
        )
        assert resolved == (tmp_path / "xdg" / "cisternal" / "sessions").resolve()
        assert layer == str(config)

    def test_layer3_malformed_pyproject_cli_raises_value_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("invalid = [toml syntax", encoding="utf-8")

        with pytest.raises(ValueError, match="invalid TOML"):
            resolve_sessions_dir(data_dir=None, is_hook=False, project_dir=tmp_path)

    def test_layer3_non_utf8_pyproject_cli_raises_value_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that in CLI mode, non-UTF-8 pyproject.toml raises a descriptive ValueError."""
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        pyproject = tmp_path / "pyproject.toml"
        # Write invalid UTF-8 bytes (ISO-8859-1 accented byte \xe9)
        pyproject.write_bytes(b'[tool.cisternal]\nsessions_dir = "\xe9"\n')

        with pytest.raises(ValueError, match="invalid TOML"):
            resolve_sessions_dir(data_dir=None, is_hook=False, project_dir=tmp_path)

    def test_layer3_malformed_pyproject_hook_fails_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        config = _user_config(tmp_path, monkeypatch, str(tmp_path / "xdg" / "cisternal" / "sessions"))

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("invalid = [toml syntax", encoding="utf-8")

        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=True, project_dir=None
        )
        assert resolved == (tmp_path / "xdg" / "cisternal" / "sessions").resolve()
        assert layer == str(config)

    def test_layer3_non_utf8_pyproject_hook_fails_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that in hook mode, non-UTF-8 pyproject.toml fails open to Layer 4 XDG default."""
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        config = _user_config(tmp_path, monkeypatch, str(tmp_path / "xdg" / "cisternal" / "sessions"))

        pyproject = tmp_path / "pyproject.toml"
        # Write invalid UTF-8 bytes (ISO-8859-1 accented byte \xe9)
        pyproject.write_bytes(b'[tool.cisternal]\nsessions_dir = "\xe9"\n')

        resolved, layer = resolve_sessions_dir(
            data_dir=None, is_hook=True, project_dir=None
        )
        assert resolved == (tmp_path / "xdg" / "cisternal" / "sessions").resolve()
        assert layer == str(config)

    def test_layer4_user_config_sessions_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        config = _user_config(tmp_path, monkeypatch, "relative/sessions")
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        resolved, layer = resolve_sessions_dir(project_dir=empty_dir)
        assert resolved == (config.parent / "relative" / "sessions").resolve()
        assert layer == str(config)

    def test_unconfigured_is_off_with_no_baked_in_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Derived-data dirs are configuration: nothing configured -> no path."""
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        for is_hook in (False, True):
            assert resolve_sessions_dir(is_hook=is_hook, project_dir=empty_dir) == (
                None,
                "unconfigured",
            )
        assert not (tmp_path / "state").exists()

    def test_layer4_user_config_off_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        _user_config(tmp_path, monkeypatch, "off")
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        assert resolve_sessions_dir(project_dir=empty_dir) == (None, "off")

    def test_layer4_malformed_user_config_raises_cli_fails_open_hook(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        config = tmp_path / "cfg" / "cisternal" / "config.toml"
        config.parent.mkdir(parents=True)
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        for text in ("sessions_dir = [broken", "sessions_dir = false\n"):
            config.write_text(text, encoding="utf-8")
            with pytest.raises(ValueError):
                resolve_sessions_dir(project_dir=empty_dir)
            assert resolve_sessions_dir(is_hook=True, project_dir=empty_dir) == (None, "off")


class TestAtomicAppendJsonl:
    """Test atomic single-line append, line truncation, and 1 MiB size cap."""

    def test_atomic_append_jsonl_normal_record(self, tmp_path: Path) -> None:
        log_file = tmp_path / "errors.jsonl"
        record = {
            "session_id": "s1",
            "tool": "bathos/run_sql",
            "message": "query error",
        }

        ok = atomic_append_jsonl(log_file, record)
        assert ok is True
        assert log_file.is_file()

        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["session_id"] == "s1"
        assert parsed["tool"] == "bathos/run_sql"
        assert parsed["message"] == "query error"

    def test_atomic_append_jsonl_truncation_marker_ascii(self, tmp_path: Path) -> None:
        log_file = tmp_path / "errors.jsonl"
        large_message = "A" * 10000
        record = {"tool": "bathos/run_sql", "message": large_message}

        ok = atomic_append_jsonl(log_file, record)
        assert ok is True

        content = log_file.read_bytes()
        assert len(content) <= MAX_RECORD_LINE_BYTES
        assert content.endswith(b"\n")

        line = content.decode("utf-8").strip()
        parsed = json.loads(line)
        assert parsed["tool"] == "bathos/run_sql"
        assert parsed["message"].endswith(TRUNCATION_MARKER)

    def test_atomic_append_jsonl_truncation_marker_unicode(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "errors.jsonl"
        large_message = "🔥🚀✨" * 2000
        record = {"tool": "bathos/run_sql", "message": large_message}

        ok = atomic_append_jsonl(log_file, record)
        assert ok is True

        content = log_file.read_bytes()
        assert len(content) <= MAX_RECORD_LINE_BYTES
        assert content.endswith(b"\n")

        line = content.decode("utf-8").strip()
        parsed = json.loads(line)
        assert parsed["tool"] == "bathos/run_sql"
        assert parsed["message"].endswith(TRUNCATION_MARKER)

    def test_atomic_append_jsonl_truncation_payload_field(self, tmp_path: Path) -> None:
        log_file = tmp_path / "errors.jsonl"
        record = {"tool": "myxcel/submit_job", "payload": "B" * 8000}

        ok = atomic_append_jsonl(log_file, record)
        assert ok is True

        content = log_file.read_bytes()
        assert len(content) <= MAX_RECORD_LINE_BYTES
        line = content.decode("utf-8").strip()
        parsed = json.loads(line)
        assert parsed["payload"].endswith(TRUNCATION_MARKER)

    def test_atomic_append_jsonl_truncation_short_message_large_unicode_payload(
        self, tmp_path: Path
    ) -> None:
        """Test truncation when message is short but payload contains large multi-byte Unicode.

        Asserts:
        - Result is <= 4096 bytes (MAX_RECORD_LINE_BYTES).
        - Raw bytes end with a newline (b"\\n").
        - Decodes as valid UTF-8 without UnicodeDecodeError.
        - Parses as valid JSON without JSONDecodeError.
        - Truncation marker is applied to the payload field.
        - Short message field is preserved untruncated.
        - Second append writes cleanly to a new line without line merging or corruption.
        """
        log_file = tmp_path / "errors.jsonl"
        record = {
            "session_id": "s1",
            "tool": "bathos/run_sql",
            "message": "short error",
            "payload": "🦊" * 2000,
        }

        ok = atomic_append_jsonl(log_file, record)
        assert ok is True
        assert log_file.is_file()

        raw_bytes = log_file.read_bytes()
        assert len(raw_bytes) <= MAX_RECORD_LINE_BYTES
        assert raw_bytes.endswith(b"\n"), "Serialized record must end with newline"

        # Verify UTF-8 validity
        decoded = raw_bytes.decode("utf-8")

        # Verify JSON validity
        parsed = json.loads(decoded)
        assert parsed["session_id"] == "s1"
        assert parsed["tool"] == "bathos/run_sql"
        assert parsed["message"] == "short error"
        assert parsed["payload"].endswith(TRUNCATION_MARKER)

        # Second append must append to a new line without corruption
        record2 = {
            "session_id": "s2",
            "tool": "bathos/query",
            "message": "clean second record",
        }
        ok2 = atomic_append_jsonl(log_file, record2)
        assert ok2 is True

        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"

        parsed2 = json.loads(lines[1])
        assert parsed2["session_id"] == "s2"
        assert parsed2["tool"] == "bathos/query"
        assert parsed2["message"] == "clean second record"

    def test_atomic_append_jsonl_both_fields_large_truncation(
        self, tmp_path: Path
    ) -> None:
        """When both message and payload exceed max_bytes, both truncate gracefully."""
        log_file = tmp_path / "errors.jsonl"
        rec = {
            "session_id": "s1",
            "tool": "bathos/run_sql",
            "message": "A" * 4100,
            "payload": "🦊" * 2000,
        }
        assert atomic_append_jsonl(log_file, rec) is True

        content = log_file.read_bytes()
        assert len(content) <= MAX_RECORD_LINE_BYTES
        assert content.endswith(b"\n")
        parsed = json.loads(content.decode("utf-8"))
        assert parsed["message"].endswith(TRUNCATION_MARKER)
        assert parsed["payload"].endswith(TRUNCATION_MARKER)

    def test_atomic_append_jsonl_non_string_overflow_fallback(
        self, tmp_path: Path
    ) -> None:
        """Records exceeding max_bytes with non-string data fallback to a safe summary record."""
        log_file = tmp_path / "errors.jsonl"
        rec = {
            "session_id": "s_huge",
            "tool": "bathos/heavy",
            "data": list(range(5000)),
        }
        assert atomic_append_jsonl(log_file, rec) is True

        content = log_file.read_bytes()
        assert len(content) <= MAX_RECORD_LINE_BYTES
        assert content.endswith(b"\n")
        parsed = json.loads(content.decode("utf-8"))
        assert parsed["error"] == "record_exceeds_max_line_bytes"
        assert parsed["session_id"] == "s_huge"
        assert parsed["tool"] == "bathos/heavy"

    def test_atomic_append_jsonl_size_cap_fail_open(self, tmp_path: Path) -> None:
        log_file = tmp_path / "errors.jsonl"
        # Pre-fill file with exactly MAX_FILE_SIZE_BYTES (1 MiB)
        log_file.write_bytes(b"x" * MAX_FILE_SIZE_BYTES)
        assert log_file.stat().st_size == MAX_FILE_SIZE_BYTES

        record = {"tool": "bathos/run_sql", "message": "should not be appended"}
        ok = atomic_append_jsonl(log_file, record)

        assert ok is False
        assert log_file.stat().st_size == MAX_FILE_SIZE_BYTES

    def test_atomic_append_jsonl_size_cap_boundary(self, tmp_path: Path) -> None:
        log_file = tmp_path / "errors.jsonl"
        # Pre-fill with MAX_FILE_SIZE_BYTES - 20 bytes (< 1 MiB)
        initial_size = MAX_FILE_SIZE_BYTES - 20
        log_file.write_bytes(b"x" * initial_size)

        record = {"tool": "test", "message": "fits and pushes over" * 5}
        ok1 = atomic_append_jsonl(log_file, record)
        assert ok1 is True
        assert log_file.stat().st_size > MAX_FILE_SIZE_BYTES

        # Next append must fail because file is now >= 1 MiB
        ok2 = atomic_append_jsonl(log_file, record)
        assert ok2 is False

    def test_atomic_append_jsonl_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested_file = tmp_path / "deep" / "nested" / "dir" / "errors.jsonl"
        assert not nested_file.parent.exists()

        ok = atomic_append_jsonl(nested_file, {"tool": "test"})
        assert ok is True
        assert nested_file.is_file()

    def test_atomic_append_jsonl_fails_open_on_io_error(self, tmp_path: Path) -> None:
        # A directory path instead of a file causes os.open with O_WRONLY to fail with EISDIR
        bad_path = tmp_path / "a_directory"
        bad_path.mkdir()

        ok = atomic_append_jsonl(bad_path, {"tool": "test"})
        assert ok is False

    def test_atomic_append_jsonl_multiprocess_concurrency(self, tmp_path: Path) -> None:
        log_file = tmp_path / "concurrency_test.jsonl"
        workers = 8
        count_per_worker = 50

        args = [(str(log_file), w, count_per_worker) for w in range(workers)]
        with ProcessPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(_concurrency_worker, args))

        assert sum(results) == workers * count_per_worker

        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == workers * count_per_worker

        seen_records = set()
        for idx, line in enumerate(lines):
            assert len(line.encode("utf-8")) <= MAX_RECORD_LINE_BYTES
            parsed = json.loads(line)
            key = (parsed["worker"], parsed["seq"])
            assert key not in seen_records
            seen_records.add(key)

        assert len(seen_records) == workers * count_per_worker


class TestInstallWritesSessionsConfig:
    """`<tool> plugin install` records sessions_dir for bundles with cisternal-hook hooks."""

    @staticmethod
    def _bundle(*scripts: str) -> object:
        from types import SimpleNamespace

        return SimpleNamespace(hook_specs=[SimpleNamespace(script=s) for s in scripts])

    @pytest.fixture
    def env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.delenv("CISTERNAL_SESSIONS_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.chdir(tmp_path)
        return tmp_path / "cfg" / "cisternal" / "config.toml"

    def test_writes_entry_and_keeps_existing_keys(
        self, env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from cisternal.plugin.app import _ensure_sessions_config

        env.parent.mkdir(parents=True)
        env.write_text('plugin_marketplace = "~/mkt"\n', encoding="utf-8")
        _ensure_sessions_config(self._bundle("cisternal-hook pre-tool-use"), dry_run=False)

        import tomllib

        doc = tomllib.loads(env.read_text(encoding="utf-8"))
        assert doc["plugin_marketplace"] == "~/mkt"
        assert doc["sessions_dir"].endswith("/state/cisternal/sessions")
        assert "wrote sessions_dir" in capsys.readouterr().err
        resolved, layer = resolve_sessions_dir()
        assert resolved == (env.parent.parent.parent / "state" / "cisternal" / "sessions").resolve()
        assert layer == str(env)

    def test_no_write_without_cisternal_hooks_or_in_dry_run(self, env: Path) -> None:
        from cisternal.plugin.app import _ensure_sessions_config

        _ensure_sessions_config(self._bundle("other-tool hook"), dry_run=False)
        _ensure_sessions_config(self._bundle("cisternal-hook pre-tool-use"), dry_run=True)
        assert not env.exists()

    def test_existing_off_entry_is_left_alone(self, env: Path) -> None:
        from cisternal.plugin.app import _ensure_sessions_config

        env.parent.mkdir(parents=True)
        env.write_text('sessions_dir = "off"\n', encoding="utf-8")
        _ensure_sessions_config(self._bundle("cisternal-hook pre-tool-use"), dry_run=False)
        assert env.read_text(encoding="utf-8") == 'sessions_dir = "off"\n'

    def test_writes_user_config_even_when_env_or_cwd_pyproject_configure_it(
        self, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hooks in other projects see neither, so install must still write the user config."""
        from cisternal.plugin.app import _ensure_sessions_config

        monkeypatch.setenv("CISTERNAL_SESSIONS_DIR", str(tmp_path / "from_env"))
        (tmp_path / "pyproject.toml").write_text("broken = [", encoding="utf-8")
        _ensure_sessions_config(self._bundle("cisternal-hook pre-tool-use"), dry_run=False)
        assert "sessions_dir" in env.read_text(encoding="utf-8")
