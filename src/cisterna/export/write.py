"""write_bundle — filesystem sink for emitter output (spec §3, B2 resolution).

write_bundle is intentionally Emitter-independent: it takes a plain
``dict[str, str]`` (as returned by ``Emitter.emit``) and a target directory,
then writes (or dry-runs) each file via :class:`FileWriterSink`.

Design invariants:
    - ``dry_run=True``: computes content_sha256 for each file, writes NOTHING,
      returns a WriteResult capturing the hashes.
    - ``dry_run=False``: creates parent directories and writes each file as UTF-8,
      then returns WriteResult.  I/O failures (OSError / PermissionError) are
      caught per-file: a WARNING is logged naming the path and error, and the
      loop continues to the next file.  The function NEVER raises on I/O failure.
    - content_sha256 is the SHA-256 of the file contents and is always computed,
      regardless of write success (the hash is content-based, not write-success-based).
    - Empty ``files`` → empty WriteResult, no error (PM-1/3).
    - NEVER raises (never-raise contract), including on I/O failure.

B2 resolution — distinct hashes:
    The ``content_sha256`` in WriteResult is the per-file content hash
    (SHA-256 of the UTF-8 file bytes).  This is DISTINCT from the provenance
    digest computed by ``bundle_sha256`` in ``export/_hash.py``.  They are
    different values even for the same file contents, because the provenance
    digest is computed over a canonical multi-file payload, not individual
    file bytes.
"""

from __future__ import annotations

from pathlib import Path

from cisterna.export.sink import FileWriterSink, WriteResult

__all__ = ["WriteResult", "write_bundle"]


def write_bundle(
    files: dict[str, str],
    out: Path,
    *,
    dry_run: bool = False,
) -> WriteResult:
    """Write (or dry-run) *files* into the *out* directory.

    Args:
        files:   ``{forward-slash-relative-path: contents}`` dict as produced
                 by ``Emitter.emit``.
        out:     Target root directory.  Intermediate directories are created
                 automatically (``mkdir -p`` semantics).
        dry_run: If ``True``, compute hashes but write nothing.  Defaults to
                 ``False``.

    Returns:
        A :class:`WriteResult` with per-file ``content_sha256`` values and the
        ``dry_run`` flag.  Empty ``files`` yields an empty WriteResult (no
        error).  When ``dry_run=False``, I/O errors are logged as WARNINGs and
        skipped — this function never raises on I/O failure.
    """
    return FileWriterSink().write(files, out, dry_run=dry_run)
