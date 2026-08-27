"""cisternal.export — Pure-emit asset export layer (spec §2).

Public API:
    Emitter            — ABC: emit(bundle) -> dict[str, str]; PURE (zero I/O).
    bundle_sha256      — Provenance digest over a file dict.
    AntigravityEmitter — Concrete emitter for the Antigravity plugin format.
    ClaudeEmitter      — Concrete emitter for the Claude plugin format.
    CopilotEmitter     — Concrete emitter for the Copilot plugin format.
    CursorEmitter      — Concrete emitter for the Cursor plugin format.
    JCodeEmitter       — Concrete emitter for the JCode plugin format.
    OpenCodeEmitter    — Concrete emitter for the OpenCode plugin format.
    PiEmitter          — Concrete emitter for the Pi package format.
    write_bundle       — Write (or dry-run) an emitter's file dict to disk.
    WriteResult        — Frozen result dataclass from write_bundle.
    WriterSink         — ABC for pluggable output sinks.
    FileWriterSink     — Filesystem WriterSink (write_bundle backend).
    MemoryWriterSink   — In-memory WriterSink for tests.
"""


from cisternal.export.base import Emitter
from cisternal.export._hash import bundle_sha256, bundle_sha256_rust
from cisternal.export.antigravity import AntigravityEmitter
from cisternal.export.claude import ClaudeEmitter
from cisternal.export.copilot import CopilotEmitter
from cisternal.export.cursor import CursorEmitter
from cisternal.export.jcode import JCodeEmitter
from cisternal.export.opencode import OpenCodeEmitter
from cisternal.export.pi import PiEmitter
from cisternal.export.registry import get_emitter, list_emitter_surfaces
from cisternal.export.sink import FileWriterSink, MemoryWriterSink, WriterSink
from cisternal.export.write import WriteResult, write_bundle

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
    "JCodeEmitter",
    "list_emitter_surfaces",
    "MemoryWriterSink",
    "OpenCodeEmitter",
    "PiEmitter",
    "WriteResult",
    "WriterSink",
    "write_bundle",
]

