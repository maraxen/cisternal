"""Validate-only manifest extensions — workflows, pipelines, snippets (M3.3d L14).

Parsed for structural/path validation only; not loaded into AssetBundle IR.
"""

from __future__ import annotations

from pathlib import Path

_EXTENSION_TABLES: tuple[str, ...] = ("workflows", "pipelines", "snippets")


def validate_extension_sections(
    plugin: dict[str, object],
    root: Path,
) -> tuple[str, ...]:
    """Return warnings for workflows/pipelines/snippets entries (L14 validate-only)."""
    warnings: list[str] = []
    for table in _EXTENSION_TABLES:
        entries = plugin.get(table)
        if entries is None:
            continue
        if not isinstance(entries, list):
            warnings.append(f"plugin.{table} must be an array of tables")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                warnings.append(f"plugin.{table} entry is not a table")
                continue
            name = str(entry.get("name") or "")
            rel = str(entry.get("path") or "")
            if not name or not rel:
                warnings.append(f"{table} entry missing name or path: {entry!r}")
                continue
            path = root / rel
            try:
                path.read_text(encoding="utf-8")
            except OSError as exc:
                warnings.append(
                    f"{table} {name!r}: missing or unreadable: {path}: {exc}"
                )
            scope = entry.get("scope")
            if table == "snippets" and scope is not None:
                scope_str = str(scope)
                if scope_str not in {"project", "user", "session"}:
                    warnings.append(
                        f"snippet {name!r}: invalid scope {scope_str!r} "
                        "(expected project|user|session)"
                    )
    return tuple(warnings)
