"""write_bundle — filesystem sink for emitter output (spec §3, B2 resolution).

write_bundle is intentionally Emitter-independent: it takes a plain
``dict[str, str]`` (as returned by ``Emitter.emit``) and a target directory,
then writes (or dry-runs) each file.

Design invariants:
    - ``dry_run=True``: computes content_sha256 for each file, writes NOTHING,
      returns a WriteResult capturing the hashes.
    - ``dry_run=False``: creates parent directories and writes each file as UTF-8,
      then returns WriteResult.
    - Empty ``files`` → empty WriteResult, no error (PM-1/3).
    - NEVER raises (never-raise contract).

B2 resolution — distinct hashes:
    The ``content_sha256`` in WriteResult is the per-file content hash
    (SHA-256 of the UTF-8 file bytes).  This is DISTINCT from the provenance
    digest computed by ``bundle_sha256`` in ``export/_hash.py``.  They are
    different values even for the same file contents, because the provenance
    digest is computed over a canonical multi-file payload, not individual
    file bytes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Result of a write_bundle call.

    Attributes:
        files:   Tuple of ``(forward-slash-relative-path, content_sha256)``
                 for each file processed.  content_sha256 is the SHA-256
                 hex digest of the UTF-8 encoded file contents.
                 Distinct from the provenance digest in the sidecar (B2).
        dry_run: ``True`` if no files were written; ``False`` if files were
                 written to disk.
    """

    files: tuple[tuple[str, str], ...]
    dry_run: bool


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
        error).
    """
    result: list[tuple[str, str]] = []

    for rel_path, contents in files.items():
        encoded = contents.encode()
        sha = hashlib.sha256(encoded).hexdigest()
        result.append((rel_path, sha))

        if not dry_run:
            target = out / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")

    return WriteResult(files=tuple(result), dry_run=dry_run)
