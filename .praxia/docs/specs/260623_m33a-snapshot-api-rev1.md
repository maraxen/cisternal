---
title: Cisterna M3.3a — public registration.snapshot() API — Buildable Spec (rev1)
backlog_id: 2581
parent_backlog_id: 2581
brainstorm_session: 179dcc85
brainstorm_winner: OPTION-A M33A-SNAPSHOT
depends_on: 2563
created_at: 2026-06-23
---

# Cisterna M3.3a — Buildable Spec (rev1)

**Scope:** First child of parent **#2581** — public `registration.snapshot()` and `list_registries()`; migrate `assets/source.py` off `_snapshot` / `_REGISTRIES`.

**Out of scope (sibling children M3.3b/c/d):** WriterSink, vendor path-array `export_command`, L14 validate-only parsing.

**Parent #2581** remains open until all four deferred items ship or are explicitly descoped.

---

## Locked decisions

| ID | Decision |
|----|----------|
| L36 | **Public `snapshot(name)`** — shallow copy of named partition; same semantics as legacy `_snapshot` (C6) |
| L37 | **`list_registries()`** — returns sorted tuple of partition names that exist; does not create partitions |
| L38 | **`_snapshot` alias** — retained as alias calling `snapshot()` for wire/tests; not removed in M3.3a |
| L39 | **Unknown registry in assets** — `registry_assets` returns `()` when `name not in list_registries()` (no silent partition creation) |
| L40 | **Exports** — `snapshot`, `list_registries` on `cisterna.registration` package; optional lazy export on `cisterna` top-level |

---

## API (`src/cisterna/registration/registry.py`)

```python
def list_registries() -> tuple[str, ...]: ...

def snapshot(name: str = "default") -> dict[str, ToolEntry]:
    """Shallow copy at call time (C6). May create empty partition if name unseen."""

def _snapshot(name: str = "default") -> dict[str, ToolEntry]:
    """Alias for snapshot(); internal/wire compatibility."""
```

---

## Acceptance criteria

| AC | Given | When | Then |
|----|-------|------|------|
| AC-M33a-1 | tools in `default` | `snapshot("default")` | shallow copy; mutating dict does not affect live registry |
| AC-M33a-2 | no `unknown` partition | `list_registries()` | does not include `unknown` |
| AC-M33a-3 | `unknown` never registered | `registry_assets("unknown")` | returns `()` without creating partition |
| AC-M33a-4 | registered tools | `registry_assets` via public snapshot | AC-M3-2 tests still pass |
| AC-M33a-5 | full suite | pytest | 283+ green; ruff clean |

---

## Implementation DAG

```
N21 snapshot() + list_registries() + _snapshot alias
N22 migrate source.py + wired.py imports
N23 registration __init__ exports + tests
```

---

## Sibling backlog (register at triage)

| Child | Title |
|-------|-------|
| M3.3b | WriterSink ABC + MemoryWriterSink |
| M3.3c | vendor path-array export_command mode |
| M3.3d | L14 workflow/pipeline/snippet validate-only |
