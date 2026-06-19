"""cisterna.export — Pure-emit asset export layer (spec §2).

Public API:
    Emitter       — ABC: emit(bundle) -> dict[str, str]; PURE (zero I/O).
    bundle_sha256 — Provenance digest over a file dict.
    ClaudeEmitter — Concrete emitter for the Claude plugin format.
    write_bundle  — Write (or dry-run) an emitter's file dict to disk.
    WriteResult   — Frozen result dataclass from write_bundle.
"""

from cisterna.export.base import Emitter
from cisterna.export._hash import bundle_sha256
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.write import WriteResult, write_bundle

__all__ = [
    "Emitter",
    "bundle_sha256",
    "ClaudeEmitter",
    "WriteResult",
    "write_bundle",
]
