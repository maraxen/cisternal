"""WriterSink ABC — pluggable output targets for emitter file dicts (M3.3b).

FileWriterSink performs filesystem writes (formerly write_bundle logic).
MemoryWriterSink captures output in memory for tests; ignores *out*.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("cisternal.export")


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Result of a WriterSink.write call.

    Attributes:
        files:   Tuple of ``(forward-slash-relative-path, content_sha256)``
                 for each file processed.  content_sha256 is the SHA-256
                 hex digest of the UTF-8 encoded file contents.
                 Distinct from the provenance digest in the sidecar (B2).
        dry_run: ``True`` if no files were written; ``False`` if files were
                 written to the sink.
    """

    files: tuple[tuple[str, str], ...]
    dry_run: bool


def _build_write_result(
    files: dict[str, str],
    *,
    dry_run: bool,
) -> WriteResult:
    """Compute per-file content_sha256 entries for *files*."""
    result: list[tuple[str, str]] = []
    for rel_path, contents in files.items():
        sha = hashlib.sha256(contents.encode()).hexdigest()
        result.append((rel_path, sha))
    return WriteResult(files=tuple(result), dry_run=dry_run)


class WriterSink(ABC):
    """Abstract sink that accepts an emitter file dict and performs I/O."""

    @abstractmethod
    def write(
        self,
        files: dict[str, str],
        out: Path,
        *,
        dry_run: bool = False,
    ) -> WriteResult:
        """Write (or dry-run) *files* into the sink rooted at *out*."""


class FileWriterSink(WriterSink):
    """Filesystem sink — writes UTF-8 files under *out* (mkdir -p semantics).

    ``dry_run=True``: computes content_sha256, writes nothing.
    ``dry_run=False``: creates parent dirs and writes each file.  I/O failures
    are logged as WARNINGs and skipped; this sink never raises on I/O failure.
    """

    def write(
        self,
        files: dict[str, str],
        out: Path,
        *,
        dry_run: bool = False,
    ) -> WriteResult:
        write_result = _build_write_result(files, dry_run=dry_run)

        if dry_run:
            return write_result

        for rel_path, contents in files.items():
            target = out / rel_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")
            except OSError as exc:
                _log.warning(
                    "cisternal.export: write_bundle failed to write %s: %s",
                    target,
                    exc,
                )

        return write_result


class MemoryWriterSink(WriterSink):
    """In-memory sink for tests — captures *files*; ignores *out*.

    ``dry_run=True``: computes hashes only; does not update :attr:`captured`.
    ``dry_run=False``: replaces :attr:`captured` with a copy of *files*.
    """

    def __init__(self) -> None:
        self.captured: dict[str, str] = {}

    def write(
        self,
        files: dict[str, str],
        out: Path,
        *,
        dry_run: bool = False,
    ) -> WriteResult:
        write_result = _build_write_result(files, dry_run=dry_run)
        if not dry_run:
            self.captured = dict(files)
        return write_result
