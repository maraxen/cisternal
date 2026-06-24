"""cisterna.export — Pure-emit asset export layer (spec §2).

Public API:
    Emitter       — ABC: emit(bundle) -> dict[str, str]; PURE (zero I/O).
    bundle_sha256 — Provenance digest over a file dict.
    ClaudeEmitter — Concrete emitter for the Claude plugin format.
    CursorEmitter — Concrete emitter for the Cursor plugin format.
    write_bundle      — Write (or dry-run) an emitter's file dict to disk.
    WriteResult       — Frozen result dataclass from write_bundle.
    WriterSink        — ABC for pluggable output sinks.
    FileWriterSink    — Filesystem WriterSink (write_bundle backend).
    MemoryWriterSink  — In-memory WriterSink for tests.
"""

from cisterna.export.base import Emitter
from cisterna.export._hash import bundle_sha256, bundle_sha256_rust
from cisterna.export.antigravity import AntigravityEmitter
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.copilot import CopilotEmitter
from cisterna.export.cursor import CursorEmitter
from cisterna.export.registry import get_emitter, list_emitter_surfaces
from cisterna.export.sink import FileWriterSink, MemoryWriterSink, WriterSink
from cisterna.export.write import WriteResult, write_bundle

__all__ = [
    "Emitter",
    "AntigravityEmitter",
    "bundle_sha256",
    "bundle_sha256_rust",
    "ClaudeEmitter",
    "CopilotEmitter",
    "CursorEmitter",
    "FileWriterSink",
    "get_emitter",
    "list_emitter_surfaces",
    "MemoryWriterSink",
    "WriteResult",
    "WriterSink",
    "write_bundle",
]
