---
title: Cisterna M3.2 — entry_point emitter registry — Buildable Spec (rev1)
backlog_id: 2563
depends_on: 2326
brainstorm_session: b8307550
brainstorm_winner: OPTION-C+E HYBRID
prior_research: 260623_m32-entry-point-packaging.md
created_at: 2026-06-23
---

# Cisterna M3.2 — Buildable Spec (rev1)

**Scope:** Backlog **#2563** — `importlib.metadata` discovery for emitters, unified `get_emitter()` dispatch, pyproject entry-point registration of four built-in surfaces.

**Out of scope (rev2 deferred):** WriterSink, public `registration.snapshot()`, vendor path-array commands, L14 workflow validate-only parsing, public `register_emitter()` API.

**Zero-regression gate:** All M3.1 golden digests unchanged (AC-M32-7 extends AC-M31c-4).

---

## Locked decisions

| ID | Decision |
|----|----------|
| L29 | **Entry-point group** — `[project.entry-points."cisterna.emitters"]` in `pyproject.toml`; setuptools `build_meta` backend |
| L30 | **Factory targets** — each entry point resolves to a **callable** `(**kwargs) -> Emitter`, not a class. Built-in factories live in `cisterna.export.registry` |
| L31 | **Unified dispatch** — `get_emitter(surface: str, **kwargs) -> Emitter \| None` in `export/registry.py` is the **only** emitter lookup path for CLI and validate |
| L32 | **Kwargs filter** — only `emit_command_bodies` is passed, and **only** when `surface == "claude"`. Other surfaces ignore extra kwargs |
| L33 | **Fail-closed lookup** — `get_emitter` catches entry-point load/instantiate errors, logs warning, returns `None`. CLI/validate exit **2** when `None` (never-raise applies to `Emitter.emit()`, not dispatch) |
| L34 | **Surface listing** — `list_emitter_surfaces() -> tuple[str, ...]` returns sorted registered names from metadata (for tests; no new CLI subcommand in M3.2) |
| L35 | **No public override API** — tests may monkeypatch `registry._load_factories` or use a test-only entry point in conftest; no `register_emitter()` in public `__init__` |

---

## Registry contract (`src/cisterna/export/registry.py`)

```python
def list_emitter_surfaces() -> tuple[str, ...]: ...

def get_emitter(surface: str, *, emit_command_bodies: bool = False) -> Emitter | None:
    """Return emitter instance or None if unknown / load failed."""
```

**Loading:** `importlib.metadata.entry_points(group="cisterna.emitters")` → load callable → invoke with filtered kwargs.

**Built-in factories (also entry-point targets):**

| Surface | Factory | Kwargs |
|---------|---------|--------|
| `claude` | `claude_factory` | `emit_command_bodies` |
| `cursor` | `cursor_factory` | none |
| `copilot` | `copilot_factory` | none |
| `antigravity` | `antigravity_factory` | none |

---

## pyproject.toml delta

```toml
[project.entry-points."cisterna.emitters"]
claude = "cisterna.export.registry:claude_factory"
cursor = "cisterna.export.registry:cursor_factory"
copilot = "cisterna.export.registry:copilot_factory"
antigravity = "cisterna.export.registry:antigravity_factory"
```

Editable `uv pip install -e .` must expose all four entry points (verified in AC-M32-1).

---

## Refactor targets

| Module | Change |
|--------|--------|
| `validate_golden.py` | Remove `_EMITTERS` dict; `emit_surface_files` calls `get_emitter` |
| `cli.py` | Remove hardcoded surface set; use `list_emitter_surfaces()` for validation |
| `export/__init__.py` | Export `get_emitter`, `list_emitter_surfaces` |

---

## Acceptance criteria

| AC | Given | When | Then |
|----|-------|------|------|
| AC-M32-1 | editable install | `entry_points(group="cisterna.emitters")` | 4 built-in surfaces present |
| AC-M32-2 | registry loaded | `list_emitter_surfaces()` | `("antigravity", "claude", "copilot", "cursor")` sorted |
| AC-M32-3 | manifest_minimal | `get_emitter("claude").emit(bundle)` | byte-identical to pre-M3.2 `ClaudeEmitter()` |
| AC-M32-4 | unknown surface `"linear"` | `get_emitter("linear")` | returns `None` |
| AC-M32-5 | broken entry point in test | `get_emitter` | returns `None`, no raise |
| AC-M32-6 | manifest_minimal | `validate --surface` each built-in | exit 0 (all goldens) |
| AC-M32-7 | M3.1 golden fixtures | full pytest | 275+ tests green; all 5 digest hashes unchanged |

---

## Implementation DAG

```
N17 registry.py + factories + pyproject entry-points (AC-M32-1/2/3/4/5)
N18 validate_golden refactor (AC-M32-6)
N19 cli.py refactor to registry (AC-M32-6)
N20 regression suite + export __init__ exports (AC-M32-7)
```

---

## Pre-mortem mitigations

| Risk | Mitigation |
|------|------------|
| kwargs leak to non-claude factories | L32 filter in `get_emitter` |
| third-party factory raises | L33 catch + return None |
| golden drift | AC-M32-7 dedicated regression test |

---

## References

- `.praxia/docs/research/260623_m32-entry-point-packaging.md`
- `src/cisterna/export/base.py` — Emitter ABC (unchanged)
- M3.1 closeout: `.praxia/docs/research/260623_m31-epic-closeout-audit.md`
