"""Local Claude Code plugin marketplace publishing.

Implements the shared-marketplace protocol already dogfooded by the
cisternal-family tools (see ``~/.cisternal/claude-plugin-marketplace/README.md``):
an flock'd, atomic read-modify-write merge of one plugin entry into a shared
``marketplace.json``, plus first-use README bootstrap.

This module is the canonical, importable implementation of the merge
algorithm that previously existed only as a hand-copied reference script
(myxcel's ``scripts/marketplace/sync_marketplace.py``). Cisternal is the
shared export toolkit for the praxia tool family, so this logic belongs here
rather than duplicated per consuming repo.

Unlike ``export.base.Emitter``, these functions perform real filesystem I/O
by design — publishing to a shared, concurrently-written marketplace
directory is inherently not a pure operation.
"""

from __future__ import annotations

import hashlib
import json
from fcntl import LOCK_EX, flock
from pathlib import Path
from typing import Any

MARKETPLACE_SCHEMA = "https://anthropic.com/claude-code/marketplace.schema.json"

DEFAULT_MARKETPLACE_NAME = "cisternal-local"
DEFAULT_MARKETPLACE_OWNER = "cisternal"
DEFAULT_MARKETPLACE_DESCRIPTION = (
    "Locally generated plugins for the cisternal tool family "
    "(praxia, myxcel, bathos, ...)"
)


def content_version(base_version: str, files: dict[str, str]) -> str:
    """Return *base_version* suffixed with a short content digest of *files*.

    Claude Code caches installed plugins in a version-keyed directory, so a
    static version string means a re-published bundle is never picked up by
    an existing install. Appending a digest over the emitted file set busts
    that cache exactly when the bundle's actual content changes, and no
    other time — re-publishing unchanged content yields the same version.
    """
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(files[path].encode())
        digest.update(b"\0")
    return f"{base_version}+{digest.hexdigest()[:8]}"


def default_seed(
    *,
    marketplace_name: str = DEFAULT_MARKETPLACE_NAME,
    owner: str = DEFAULT_MARKETPLACE_OWNER,
    description: str = DEFAULT_MARKETPLACE_DESCRIPTION,
) -> dict[str, Any]:
    """Return the ``marketplace.json`` document to start from when none exists."""
    return {
        "$schema": MARKETPLACE_SCHEMA,
        "name": marketplace_name,
        "description": description,
        "owner": {"name": owner},
        "plugins": [],
    }


def merge_marketplace_entry(
    marketplace_root: Path,
    entry: dict[str, Any],
    *,
    seed: dict[str, Any] | None = None,
    readme_template: str | None = None,
) -> Path:
    """Merge *entry* into ``marketplace_root``'s ``marketplace.json`` (flock'd, atomic).

    Replace-or-append by ``entry["name"]``: any existing entry with the same
    name is dropped first, then *entry* is appended and the list is sorted by
    name for determinism. Every other tool's entry is preserved untouched.
    Concurrent publishes from multiple cisternal-family tools must go through
    this same lock, or a race can drop an entry.

    Returns the path to the written ``marketplace.json``.
    """
    entry_name = entry.get("name")
    if not entry_name:
        msg = "entry has no 'name' field"
        raise ValueError(msg)

    marketplace_root.mkdir(parents=True, exist_ok=True)
    plugin_dir = marketplace_root / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (marketplace_root / "plugins").mkdir(parents=True, exist_ok=True)

    lock_path = plugin_dir / ".lock"
    marketplace_json_path = plugin_dir / "marketplace.json"

    with lock_path.open("a", encoding="utf-8") as lock_file:
        flock(lock_file.fileno(), LOCK_EX)

        if marketplace_json_path.exists():
            doc = json.loads(marketplace_json_path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or "plugins" not in doc:
                msg = f"{marketplace_json_path} is malformed (missing 'plugins')"
                raise ValueError(msg)
        else:
            doc = dict(seed) if seed is not None else default_seed()

        doc["plugins"] = [
            p for p in doc.get("plugins", []) if p.get("name") != entry_name
        ]
        doc["plugins"].append(entry)
        doc["plugins"].sort(key=lambda p: p.get("name", ""))

        temp_path = marketplace_json_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(marketplace_json_path)

    readme_dest = marketplace_root / "README.md"
    if readme_template is not None and not readme_dest.exists():
        readme_dest.write_text(readme_template, encoding="utf-8")

    return marketplace_json_path


def plugin_output_dir(marketplace_root: Path, name: str) -> Path:
    """Return ``marketplace_root/plugins/<name>``, rejecting unsafe names.

    *name* must be a single path segment — no separators, no ``..`` — so a
    malicious or malformed bundle name cannot write outside ``plugins/``.
    """
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        msg = f"unsafe plugin name for marketplace publish: {name!r}"
        raise ValueError(msg)
    return marketplace_root / "plugins" / name
