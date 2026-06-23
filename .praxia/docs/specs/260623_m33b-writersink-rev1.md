---
title: M3.3b — WriterSink ABC — rev1
backlog_id: 2587
parent: 2581
---

# M3.3b — WriterSink (rev1)

**Files owned:** `src/cisterna/export/sink.py`, `src/cisterna/export/write.py`, `src/cisterna/cli.py` (sink param only), `src/cisterna/export/__init__.py`, `tests/test_export_sink.py`

## API

```python
class WriterSink(ABC):
    def write(self, files: dict[str, str], out: Path, *, dry_run: bool = False) -> WriteResult: ...

class FileWriterSink(WriterSink): ...  # current write_bundle logic
class MemoryWriterSink(WriterSink): ...  # captures files dict; ignores out
```

`write_bundle(...)` delegates to `FileWriterSink().write(...)` — signature unchanged.

## ACs

- AC-M33b-1: all `test_export_write.py` pass unchanged
- AC-M33b-2: MemoryWriterSink captures files; dry_run writes nothing
- AC-M33b-3: ruff clean; full pytest green

**Do not touch:** `manifest.py`, `manifest_commands.py`
