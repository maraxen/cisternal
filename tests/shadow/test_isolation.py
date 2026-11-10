"""Tests for cisternal.shadow.isolation and prove_isolation helper (AC-4).

Verifies:
- Clean execution: identical return values, identical live writes, shadow writes only to log -> passed=True.
- Divergence in return values -> live_output_identical=False, passed=False.
- Divergence in live filesystem outputs -> live_output_identical=False, passed=False.
- Leaked writes outside shadow_log_dir and live_roots -> leaked_paths populated, passed=False.
- Telemetry emission of shadow.isolation record.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any

import pytest

import cisternal
import cisternal.shadow.isolation as isolation_mod
from cisternal.shadow.isolation import (
    IsolationRestoreError,
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


def test_prove_isolation_detects_unreadable_file_leak(tmp_path: Path) -> None:
    """Finding 3 (REV2-02): prove_isolation flags unreadable (chmod 000) file leaks."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    leak_file = scratch_dir / "unreadable_leak.bin"

    def live_actor() -> str:
        return "ok"

    def shadow_actor() -> str:
        leak_file.write_bytes(b"secret unreadable leak")
        leak_file.chmod(0o000)
        return "ok"

    try:
        res = prove_isolation(
            live_actor,
            shadow_actor,
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            check_roots=[scratch_dir],
        )
        assert res.passed is False
        assert leak_file.resolve() in [p.resolve() for p in res.leaked_paths]
    finally:
        if leak_file.exists():
            leak_file.chmod(0o666)


def test_prove_isolation_detects_directory_and_symlink_leak(tmp_path: Path) -> None:
    """Finding 3 (REV2-04): prove_isolation flags directory and broken symlink leaks."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    leak_subdir = scratch_dir / "leaked_subfolder"
    leak_symlink = scratch_dir / "leaked_symlink"

    def live_actor() -> str:
        return "clean"

    def shadow_actor() -> str:
        leak_subdir.mkdir()
        leak_symlink.symlink_to("/nonexistent/target")
        return "clean"

    res = prove_isolation(
        live_actor,
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        check_roots=[scratch_dir],
    )
    assert res.passed is False
    leaked_res = [p.resolve() for p in res.leaked_paths]
    assert leak_subdir.resolve() in leaked_res
    # Symlink target may be nonexistent so match on string path or name
    assert any("leaked_symlink" in str(p) for p in res.leaked_paths)


def test_prove_isolation_default_watched_dirs_catches_cwd_leak(tmp_path: Path) -> None:
    """Finding 6 (REV2-05): Default watch set catches leak in Path.cwd()."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    cwd_leak = Path.cwd() / "cisternal_isolation_cwd_leak.tmp"

    def live_actor() -> str:
        return "clean"

    def shadow_actor() -> str:
        cwd_leak.write_text("unauthorized write in cwd")
        return "clean"

    try:
        res = prove_isolation(
            live_actor,
            shadow_actor,
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            # No check_roots passed; relies on default watched_dirs
        )
        assert res.passed is False
        assert any("cisternal_isolation_cwd_leak.tmp" in str(p) for p in res.leaked_paths)
    finally:
        if cwd_leak.exists():
            cwd_leak.unlink()


def test_symlink_in_live_root_is_preserved(tmp_path: Path) -> None:
    """B5.1: a symlink inside a live root must not be turned into a regular file."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (tmp_path / "target.txt").write_text("target", encoding="utf-8")
    link = live_dir / "link"
    link.symlink_to("../target.txt")
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()

    res = prove_isolation(
        lambda: 1,
        lambda: 1,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        check_roots=[tmp_path],
    )

    assert res.passed is True
    assert res.leaked_paths == []
    assert link.is_symlink()
    assert os.readlink(link) == "../target.txt"


def test_unreadable_file_in_live_root_is_preserved(tmp_path: Path) -> None:
    """B5.2: a chmod-000 file in a live root is neither an exception nor lost."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    locked = live_dir / "locked.bin"
    locked.write_bytes(b"keep me")
    locked.chmod(0)

    try:
        res = prove_isolation(
            lambda: "ok",
            lambda: "ok",
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            check_roots=[tmp_path],
        )
        assert res.passed is True
        assert stat.S_IMODE(locked.lstat().st_mode) == 0
    finally:
        locked.chmod(0o600)
    assert locked.read_bytes() == b"keep me"


def test_failed_restore_keeps_backup_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B5.3: a restore that fails midway must not destroy the only copy of the root."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    data = live_dir / "data.txt"
    data.write_text("original contents", encoding="utf-8")

    real_copyfile = shutil.copyfile

    def flaky_copyfile(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(dst).is_relative_to(live_dir):
            raise OSError(errno.EIO, "injected restore failure")
        return real_copyfile(src, dst, *args, **kwargs)

    monkeypatch.setattr(isolation_mod.shutil, "copyfile", flaky_copyfile)

    def shadow_actor() -> str:
        data.write_text("shadow mutation", encoding="utf-8")
        return "ok"

    with pytest.raises(IsolationRestoreError) as excinfo:
        prove_isolation(
            lambda: "ok",
            shadow_actor,
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            check_roots=[tmp_path],
        )

    backup = excinfo.value.backup_path
    try:
        assert str(backup) in str(excinfo.value)
        assert live_dir.is_dir()
        assert (backup / "root_0" / "data.txt").read_text(encoding="utf-8") == "original contents"
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def test_restore_round_trips_mode_and_mtime(tmp_path: Path) -> None:
    """B5.4: content, mode and mtime of a live file are restored after a divergent shadow run."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    cfg = live_dir / "cfg.txt"
    cfg.write_text("v1", encoding="utf-8")
    cfg.chmod(0o640)
    old_ns = 1_600_000_000_000_000_000
    os.utime(cfg, ns=(old_ns, old_ns))
    before = cfg.lstat()

    def shadow_actor() -> str:
        cfg.write_text("v2", encoding="utf-8")
        return "ok"

    res = prove_isolation(
        lambda: "ok",
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        check_roots=[tmp_path],
    )

    after = cfg.lstat()
    assert res.passed is False
    assert cfg.read_text(encoding="utf-8") == "v1"
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode) == 0o640
    assert after.st_mtime_ns == before.st_mtime_ns


def test_entry_that_cannot_be_backed_up_is_not_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B5.4: an entry that backup cannot read is left untouched on restore, never deleted."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    opaque = live_dir / "opaque.bin"
    opaque.write_bytes(b"opaque")

    real_copyfile = shutil.copyfile

    def refuse_opaque(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(src).name == "opaque.bin":
            raise PermissionError(errno.EACCES, "injected unreadable entry", str(src))
        return real_copyfile(src, dst, *args, **kwargs)

    monkeypatch.setattr(isolation_mod.shutil, "copyfile", refuse_opaque)

    def shadow_actor() -> str:
        opaque.write_bytes(b"shadow")
        return "ok"

    res = prove_isolation(
        lambda: "ok",
        shadow_actor,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        check_roots=[tmp_path],
    )

    assert res.passed is False
    assert opaque.exists()


def test_read_only_subdirectory_round_trips(tmp_path: Path) -> None:
    """A mode-0500 live subdirectory is restored in place, with its mode, after a divergent run."""
    live_dir = tmp_path / "live"
    sub = live_dir / "sub"
    sub.mkdir(parents=True)
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    inner = sub / "inner.txt"
    inner.write_text("original", encoding="utf-8")
    sub.chmod(0o500)

    try:
        def shadow_actor() -> str:
            inner.write_text("mutated", encoding="utf-8")
            return "ok"

        res = prove_isolation(
            lambda: "ok",
            shadow_actor,
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            check_roots=[tmp_path],
        )
        assert res.passed is False
        assert stat.S_IMODE(sub.lstat().st_mode) == 0o500
        assert inner.read_text(encoding="utf-8") == "original"
    finally:
        sub.chmod(0o700)


def test_unreadable_subdirectory_in_live_root_is_preserved(tmp_path: Path) -> None:
    """A live subdirectory with mode 0 (no read or execute bit) is backed up and restored intact."""
    live_dir = tmp_path / "live"
    sub = live_dir / "sub"
    sub.mkdir(parents=True)
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    inner = sub / "f.txt"
    inner.write_text("inner contents", encoding="utf-8")
    sub.chmod(0)

    try:
        res = prove_isolation(
            lambda: "ok",
            lambda: "ok",
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            check_roots=[tmp_path],
        )
        assert res.passed is True
        assert stat.S_IMODE(sub.lstat().st_mode) == 0
    finally:
        sub.chmod(0o700)
    assert inner.read_text(encoding="utf-8") == "inner contents"


def test_live_actor_exception_restores_root_and_propagates(tmp_path: Path) -> None:
    """If the live actor raises, live roots are restored and the exception still propagates."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    shadow_log = tmp_path / "shadow_log"
    shadow_log.mkdir()
    keep = live_dir / "keep.txt"
    keep.write_text("before", encoding="utf-8")

    def live_actor() -> str:
        keep.write_text("half written", encoding="utf-8")
        (live_dir / "partial.tmp").write_text("x", encoding="utf-8")
        raise RuntimeError("live actor failed")

    with pytest.raises(RuntimeError, match="live actor failed"):
        prove_isolation(
            live_actor,
            lambda: "ok",
            live_roots=[live_dir],
            shadow_log_dir=shadow_log,
            check_roots=[tmp_path],
        )

    assert keep.read_text(encoding="utf-8") == "before"
    assert not (live_dir / "partial.tmp").exists()
