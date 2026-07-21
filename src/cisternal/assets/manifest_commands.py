"""Vendor export_command path loading (M3.3c)."""

from __future__ import annotations

from pathlib import Path

from cisternal.assets.bundle import CommandAsset

VENDOR_EXPORT_KEYS: tuple[str, ...] = ("claude_code", "cursor", "copilot", "antigravity")


def load_export_commands(
    plugin: dict[str, object],
    root: Path,
    warnings: list[str],
) -> tuple[CommandAsset, ...]:
    """Load command assets from vendor path arrays under ``[plugin.export_command]``."""
    export_cmd = plugin.get("export_command")
    if not isinstance(export_cmd, dict):
        return ()

    seen: set[str] = set()
    commands: list[CommandAsset] = []

    for vendor_key in VENDOR_EXPORT_KEYS:
        paths = export_cmd.get(vendor_key)
        if not isinstance(paths, list):
            continue
        for rel in paths:
            rel_path = str(rel)
            path = root / rel_path
            name = path.stem
            if name in seen:
                continue
            seen.add(name)
            text = _read_text(path, warnings, f"command {name!r}")
            body = text if text is not None else ""
            commands.append(CommandAsset(name=name, description=None, body=body))

    return tuple(commands)


def _read_text(path: Path, warnings: list[str], label: str) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"{label}: missing or unreadable: {path}: {exc}")
        return None
