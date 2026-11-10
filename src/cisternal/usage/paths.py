"""Derived-data directory resolver and atomic JSONL writer for cisternal usage telemetry.

Implements the 5-layer precedence hierarchy for derived session data directories
and POSIX-compliant atomic single-line append with strict byte caps and fail-open semantics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tomllib
from typing import Any

__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_RECORD_LINE_BYTES",
    "TRUNCATION_MARKER",
    "atomic_append_jsonl",
    "resolve_sessions_dir",
    "user_config_path",
    "write_sessions_config",
]

MAX_RECORD_LINE_BYTES: int = 4096
MAX_FILE_SIZE_BYTES: int = 1_048_576  # 1 MiB (1024 * 1024 bytes)
TRUNCATION_MARKER: str = " ...[TRUNCATED]"
OFF_VALUES: frozenset[str] = frozenset({"", "off", "none"})


SESSIONS_CONFIG_KEY = "sessions_dir"


def user_config_path() -> Path:
    """``${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml`` (same file as the marketplace)."""
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "cisternal" / "config.toml"


def _resolve_user_config_sessions_dir(*, is_hook: bool) -> tuple[Path | None, str] | None:
    config = user_config_path()
    try:
        if not config.is_file():
            return None
        doc = tomllib.loads(config.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        if is_hook:
            return None, "off"  # fail open: no ledger rather than a crash
        msg = f"{config}: invalid TOML: {exc}"
        raise ValueError(msg) from exc
    if SESSIONS_CONFIG_KEY not in doc:
        return None
    raw_obj = doc[SESSIONS_CONFIG_KEY]
    if not isinstance(raw_obj, str):
        if is_hook:
            return None, "off"
        msg = f"{config}: {SESSIONS_CONFIG_KEY} must be a string, got {raw_obj!r}"
        raise ValueError(msg)
    raw_val = raw_obj.strip()
    if raw_val.lower() in OFF_VALUES:
        return None, "off"
    return (config.parent / Path(raw_val).expanduser()).resolve(), str(config)


def _resolve_pyproject_sessions_dir(
    anchor: Path | None,
    *,
    is_hook: bool,
) -> tuple[Path | None, str] | None:
    """Walk up from anchor to resolve [tool.cisternal] sessions_dir from pyproject.toml."""
    if anchor is None:
        return None
    for directory in (anchor, *anchor.parents):
        candidate = directory / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
            parsed = tomllib.loads(content)
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
            if is_hook:
                continue  # Fail-open in hook mode
            msg = f"{candidate}: invalid TOML: {exc}"
            raise ValueError(msg) from exc

        tool = parsed.get("tool")
        if isinstance(tool, dict):
            cisternal_cfg = tool.get("cisternal")
            if isinstance(cisternal_cfg, dict) and "sessions_dir" in cisternal_cfg:
                raw_obj = cisternal_cfg["sessions_dir"]
                if not isinstance(raw_obj, str):
                    if is_hook:
                        continue  # Fail-open in hook mode
                    msg = (
                        f"{candidate}: [tool.cisternal] sessions_dir must be a string, "
                        f"got {raw_obj!r}"
                    )
                    raise ValueError(msg)
                raw_val = raw_obj.strip()
                if raw_val.lower() in OFF_VALUES:
                    return None, "off"
                val_path = Path(raw_val).expanduser()
                if not val_path.is_absolute():
                    val_path = (directory / val_path).resolve()
                else:
                    val_path = val_path.resolve()
                return val_path, f"[tool.cisternal] in {candidate}"
    return None


def resolve_sessions_dir(
    data_dir: Path | str | None = None,
    is_hook: bool = False,
    project_dir: Path | str | None = None,
) -> tuple[Path | None, str]:
    """Resolve session directory from 5-layer precedence chain.

    Precedence:
    1. Explicit argument (`data_dir`) -> (path, "argument")
    2. Environment variable (`CISTERNAL_SESSIONS_DIR`) -> (path, "$CISTERNAL_SESSIONS_DIR")
    3. `[tool.cisternal] sessions_dir` in `pyproject.toml`:
       - Hook mode (`is_hook=True`): anchored to $CLAUDE_PROJECT_DIR. If unset or empty,
         Layer 3 is SKIPPED completely, falling directly to Layer 4 (GAP-26).
       - Non-hook mode: anchored to `project_dir` or `Path.cwd()`.
    4. `sessions_dir` in `${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml`
       -> (path, "<config path>"); relative values resolve against the config dir.
       Plugin install writes this entry (see :func:`write_sessions_config`).
    5. Nothing configured -> `(None, "unconfigured")`. No default path is baked in.
    Off switch: `""`, `"off"` or `"none"` at any layer returns `(None, "off")`.

    Returns:
        tuple[Path | None, str]: `(resolved_path, winning_layer)`
    """
    # --- Layer 1: Explicit argument ---
    if data_dir is not None:
        raw = str(data_dir).strip()
        if raw.lower() in OFF_VALUES:
            return None, "off"
        return Path(raw).expanduser().resolve(), "argument"

    # --- Layer 2: Environment variable CISTERNAL_SESSIONS_DIR ---
    if "CISTERNAL_SESSIONS_DIR" in os.environ:
        raw = os.environ["CISTERNAL_SESSIONS_DIR"].strip()
        if raw.lower() in OFF_VALUES:
            return None, "off"
        return Path(raw).expanduser().resolve(), "$CISTERNAL_SESSIONS_DIR"

    # --- Layer 3: [tool.cisternal] sessions_dir in pyproject.toml ---
    anchor: Path | None = None
    if is_hook:
        # GAP-26: In hook contexts, anchor strictly to $CLAUDE_PROJECT_DIR.
        # If unset or empty, skip Layer 3 completely to avoid cross-cwd drift.
        claude_proj = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
        if project_dir is not None:
            anchor = Path(project_dir).expanduser().resolve()
        elif claude_proj:
            anchor = Path(claude_proj).expanduser().resolve()
        else:
            anchor = None  # Skip Layer 3!
    else:
        if project_dir is not None:
            anchor = Path(project_dir).expanduser().resolve()
        else:
            anchor = Path.cwd().resolve()

    res = _resolve_pyproject_sessions_dir(anchor, is_hook=is_hook)
    if res is not None:
        return res

    # --- Layer 4: sessions_dir in the per-machine user config ---
    # ${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml, written by
    # `<tool> plugin install` when it installs cisternal-hook hooks (never by a
    # hook). No path is baked in here: unconfigured means off.
    res = _resolve_user_config_sessions_dir(is_hook=is_hook)
    if res is not None:
        return res
    return None, "unconfigured"


def _format_and_truncate_record(
    record: dict[str, Any],
    max_bytes: int = MAX_RECORD_LINE_BYTES,
) -> bytes:
    """Format record as a single JSON line <= max_bytes using iterative binary search truncation.

    Guarantees:
    - Output is <= max_bytes.
    - Output is 100% valid UTF-8.
    - Output is 100% valid JSON parseable by json.loads().
    - Output ends with a trailing newline (\\n).
    - Never performs raw byte slicing on serialized JSON.
    """
    line = (
        json.dumps(record, separators=(",", ":"), ensure_ascii=False, default=str)
        + "\n"
    )
    data = line.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return data

    rec_copy = dict(record)

    marker_bytes_len = len(TRUNCATION_MARKER.encode("utf-8"))
    # Identify candidate string fields whose byte length exceeds TRUNCATION_MARKER
    candidates = [
        k
        for k, v in rec_copy.items()
        if isinstance(v, str)
        and len(v.encode("utf-8", errors="replace")) > marker_bytes_len
    ]
    # Sort candidates by UTF-8 byte length descending to truncate largest contributors first
    candidates.sort(
        key=lambda k: len(rec_copy[k].encode("utf-8", errors="replace")),
        reverse=True,
    )

    for field in candidates:
        orig_val = rec_copy[field]
        # Test if setting this field to TRUNCATION_MARKER allows the entire line to fit
        rec_copy[field] = TRUNCATION_MARKER
        cand_bytes = (
            json.dumps(rec_copy, separators=(",", ":"), ensure_ascii=False, default=str)
            + "\n"
        ).encode("utf-8", errors="replace")
        if len(cand_bytes) > max_bytes:
            # Even with this field at marker length, line is still over max_bytes; keep marker and continue
            continue

        # Fits at marker length: binary search for the maximal prefix of orig_val that fits
        low = 0
        high = len(orig_val) - 1
        best_data = cand_bytes
        while low <= high:
            mid = (low + high) // 2
            rec_copy[field] = orig_val[:mid] + TRUNCATION_MARKER
            cand_bytes = (
                json.dumps(
                    rec_copy, separators=(",", ":"), ensure_ascii=False, default=str
                )
                + "\n"
            ).encode("utf-8", errors="replace")
            if len(cand_bytes) <= max_bytes:
                best_data = cand_bytes
                low = mid + 1
            else:
                high = mid - 1
        return best_data

    # Fallback: all string fields truncated or record dominated by non-string structures.
    # Construct a well-formed JSON summary record; NEVER raw-byte slice.
    summary: dict[str, Any] = {
        "error": "record_exceeds_max_line_bytes",
        "marker": TRUNCATION_MARKER.strip(),
    }
    for k in ("session_id", "tool", "family", "error_code", "timestamp", "source"):
        if k in record:
            v = record[k]
            if isinstance(v, (int, float, bool)):
                summary[k] = v
            elif isinstance(v, str):
                summary[k] = v[:128]

    cand = (
        json.dumps(summary, separators=(",", ":"), ensure_ascii=False, default=str)
        + "\n"
    ).encode("utf-8", errors="replace")
    if len(cand) <= max_bytes:
        return cand
    if max_bytes >= len(b'{"error":"record_exceeds_max_line_bytes"}\n'):
        return b'{"error":"record_exceeds_max_line_bytes"}\n'
    if max_bytes >= len(b"{}\n"):
        return b"{}\n"
    return b""


def atomic_append_jsonl(
    file_path: Path | str,
    record: dict[str, Any],
    *,
    max_file_size: int = MAX_FILE_SIZE_BYTES,
    max_line_bytes: int = MAX_RECORD_LINE_BYTES,
) -> bool:
    """Atomically append a single JSON record to file_path.

    Guarantees:
    - POSIX atomic append via os.O_WRONLY | os.O_CREAT | os.O_APPEND.
    - Exactly one os.write() syscall per line.
    - Line capped to <= max_line_bytes (4096 bytes) with truncation marker.
    - Fails open (returns False, no exception) if existing file size >= max_file_size (1 MiB).
    - Fails open on any OSError or I/O error.

    Returns:
        bool: True if appended successfully, False otherwise.
    """
    path = Path(file_path)
    try:
        data = _format_and_truncate_record(record, max_bytes=max_line_bytes)
        path.parent.mkdir(parents=True, exist_ok=True)

        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            st = os.fstat(fd)
            if st.st_size >= max_file_size:
                return False
            written = os.write(fd, data)
            return written == len(data)
        finally:
            os.close(fd)
    except Exception:
        return False


def default_sessions_value() -> str:
    """The value plugin install records: under ``$XDG_STATE_HOME`` if set, else ``~/.local/state``."""
    xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
    base = xdg_state if xdg_state else "~/.local/state"
    return f"{base.rstrip('/')}/cisternal/sessions"


def write_sessions_config(value: str | None = None) -> tuple[Path, bool]:
    """Record ``sessions_dir = value`` in the user config; return ``(path, written)``.

    An existing ``sessions_dir`` key (including ``"off"``) is left alone and
    ``written`` is False. Delegates the atomic, symlink-preserving write to
    :func:`cisternal.plugin.config.write_user_config`.
    """
    from cisternal.plugin.config import write_user_config

    config = user_config_path()
    if config.is_file():
        try:
            doc = tomllib.loads(config.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            msg = f"{config}: invalid TOML: {exc}"
            raise ValueError(msg) from exc
        if SESSIONS_CONFIG_KEY in doc:
            return config, False
    path = write_user_config(
        value or default_sessions_value(),
        key=SESSIONS_CONFIG_KEY,
        comment="Session ledgers and registration cache for the cisternal-hook hooks.",
    )
    return path, True
