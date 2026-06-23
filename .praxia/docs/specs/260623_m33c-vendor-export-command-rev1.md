---
title: M3.3c — vendor path-array export_command — rev1
backlog_id: 2588
parent: 2581
---

# M3.3c — vendor export_command paths (rev1)

**Files owned:** `src/cisterna/assets/manifest_commands.py` (new), `src/cisterna/assets/manifest.py` (import only), `tests/test_assets_manifest_vendor_commands.py`, `tests/fixtures/manifest_vendor_commands/`

## Behavior

`[plugin.export_command]` may list path arrays per vendor key:

```toml
[plugin.export_command]
claude_code = ["commands/foo.md"]
cursor = ["commands/cursor-cmd.md"]
```

- New module `manifest_commands.load_export_commands(plugin, root, warnings) -> tuple[CommandAsset, ...]`
- Merge paths from keys: `claude_code`, `cursor`, `copilot`, `antigravity`
- Dedupe by command name (first wins); missing path → warning + empty body (existing behavior)
- `manifest.py` replaces inline `_load_commands` with import

## ACs

- AC-M33c-1: fixture loads commands from claude_code + cursor keys
- AC-M33c-2: `manifest_minimal` unchanged; all golden tests pass
- AC-M33c-3: ruff clean; full pytest green

**Do not touch:** `export/sink.py`, `write.py`, `cli.py` write path
