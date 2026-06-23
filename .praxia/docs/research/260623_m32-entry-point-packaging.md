# M3.2 research — entry_point emitter plugins (packaging survey)

**task_id:** `260623_epic-audit_m31` (W3)  
**gates:** M3.2 spec brainstorm — do not lock emitter plugin API until stub validated  
**date:** 2026-06-23

## Current packaging (verified)

`pyproject.toml`:

- `build-backend = "setuptools.build_meta"` (setuptools + wheel)
- `[project.scripts]` → `cisterna = "cisterna.cli:app"`
- Package discovery: `[tool.setuptools.packages.find]` where = `["src"]`

**Pre-mortem correction:** Project uses **setuptools**, not hatchling. Entry points use PEP 621 `[project.entry-points]` groups — setuptools 61+ reads these from `pyproject.toml`.

## Proposed entry-point group (UNVERIFIED stub)

```toml
[project.entry-points."cisterna.emitters"]
claude = "cisterna.export.claude:ClaudeEmitter"
cursor = "cisterna.export.cursor:CursorEmitter"
copilot = "cisterna.export.copilot:CopilotEmitter"
antigravity = "cisterna.export.antigravity:AntigravityEmitter"
```

M3.2 scope: **discovery + dispatch** via `importlib.metadata.entry_points(group="cisterna.emitters")` with fail-closed fallback when surface unknown. Built-in emitters remain in-tree; third-party wheels register additional surfaces.

## Dispatch today (anchor)

`src/cisterna/cli.py` — `export` and `validate_assets` branch on `--surface` string and instantiate emitters directly. M3.2 must refactor to a registry loader without changing default emission bytes (golden AC-M31c-4).

## Praxia precedent

UNVERIFIED — no `cisterna.emitters` entry-point group in praxia-agent-assets (Rust bundle model). Python plugin pattern is cisterna-specific per M3 brainstorm (ADDITIONAL lazy surface registration — deferred from M3, accepted for M3.2).

## M3.2 out-of-scope (rev2 deferred, still open)

- `WriterSink` ABC (file vs memory sinks)
- Public `registration.snapshot()` accessor
- Vendor path-array command mode (`export_command` beyond `claude_code` paths)
- L14 workflow/pipeline/snippet validate-only parsing

## Recommendation for M3.2 spec

1. Spike: minimal entry_point registration + one test that loads `claude` via metadata.
2. Refactor CLI dispatch to `get_emitter(surface: str) -> Emitter`.
3. Keep built-in emitters as default group members (no optional-dep split until demand proven).
4. Golden regression suite remains gate zero for any dispatch refactor.
