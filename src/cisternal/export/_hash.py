"""Provenance digest for asset bundles (spec §2, B2 resolution).

bundle_sha256 computes a canonical SHA-256 digest over a file dict produced by
an Emitter.  It is the *provenance digest* — distinct from the per-file
content_sha256 values stored in WriteResult.files (see export/write.py).

Canonical form:
    Input  : ``sorted(files.items())`` → deterministic key order.
    Payload: ``"".join(f"{path}\\n{contents}\\n" for path, contents in ...)``
    Hash   : ``hashlib.sha256(payload.encode()).hexdigest()``

Separators are FIXED LITERALS (newline after path, newline after contents).
The payload is NOT repr() of anything — repr output is implementation-defined
and must never be used as a canonical hash input (PM-5).

Design note (B2):
    The sidecar file (``cisternal-provenance.json``) is EXCLUDED from its own
    digest to avoid self-reference.  Callers must pass only the non-provenance
    file set (i.e. just ``plugin.json`` in M3).  Determinism AC (AC-M3-6):
    emit twice on an identical bundle → byte-identical dict including the
    sidecar.
"""

from __future__ import annotations

import hashlib


def bundle_sha256(files: dict[str, str]) -> str:
    """Return the SHA-256 provenance digest for *files*.

    Args:
        files: A ``{forward-slash-path: contents}`` dict as produced by
               ``Emitter.emit``.  The sidecar file must be excluded by the
               caller to avoid self-reference.

    Returns:
        Lowercase hex digest string (64 characters).
    """
    payload = "".join(
        f"{path}\n{contents}\n"
        for path, contents in sorted(files.items())
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def bundle_sha256_rust(files: dict[str, str]) -> str:
    """Return SHA-256 digest using praxia ``surface_bundle_sha256`` canonicalization.

    Payload per path (sorted): ``path + \\0 + contents + \\n`` (see praxia bundle.rs).
    """
    hasher = hashlib.sha256()
    for path, contents in sorted(files.items()):
        hasher.update(path.encode())
        hasher.update(b"\0")
        hasher.update(contents.encode())
        hasher.update(b"\n")
    return hasher.hexdigest()
