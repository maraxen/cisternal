"""Make a tool's GitHub repo installable as a Claude Code plugin.

Layout written into the repo (committed, regenerated with ``--check`` in CI)::

    <repo>/.claude-plugin/marketplace.json   # one entry: {"source": "./plugin"}
    <repo>/plugin/                           # the emitted Claude bundle
        .claude-plugin/plugin.json           # version = <release>+<content digest>
        skills/ agents/ hooks/ .mcp.json

so ``/plugin marketplace add <owner>/<repo>`` then ``/plugin install
<tool>@<tool>`` works without the tool's Python package -- pair it with
``[plugin.mcp] launch = "uvx"`` so the MCP server is self-contained too. The
bundle sits in a subdirectory, not the repo root, so a root ``.mcp.json``
never registers a duplicate project MCP server for people working in the
repo.

The same bundle is what a family-wide index (e.g. ``maraxen/plugins``) points
at, via :func:`index_entry`'s ``git-subdir`` source pinned to the release tag.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from cisternal.assets.bundle import AssetBundle

MARKETPLACE_SCHEMA = "https://anthropic.com/claude-code/marketplace.schema.json"
ROOT_MARKETPLACE = ".claude-plugin/marketplace.json"
DEFAULT_PLUGIN_DIR = "plugin"

__all__ = [
    "DEFAULT_PLUGIN_DIR",
    "ROOT_MARKETPLACE",
    "check_repo_bundle",
    "index_entry",
    "repo_bundle_files",
    "write_repo_bundle",
]


def _check_dir(plugin_dir: str) -> str:
    parts = Path(plugin_dir).parts
    if not plugin_dir or Path(plugin_dir).is_absolute() or ".." in parts or plugin_dir in {".", "./"}:
        msg = f"plugin dir must be a relative subdirectory of the repo, got {plugin_dir!r}"
        raise ValueError(msg)
    return Path(plugin_dir).as_posix()


def repo_bundle_files(
    bundle: AssetBundle, *, plugin_dir: str = DEFAULT_PLUGIN_DIR
) -> tuple[str, dict[str, str]]:
    """``(version, {repo-relative path: content})`` for the whole repo layout."""
    from cisternal.plugin.shared import versioned_claude_bundle  # noqa: PLC0415

    plugin_dir = _check_dir(plugin_dir)
    owner = (bundle.marketplace.owner_name if bundle.marketplace else "") or bundle.metadata.name
    versioned, emitted = versioned_claude_bundle(bundle)
    files = {f"{plugin_dir}/{path}": content for path, content in emitted.items()}
    name = versioned.metadata.name
    marketplace = {
        "$schema": MARKETPLACE_SCHEMA,
        "name": name,
        "description": versioned.metadata.description,
        "owner": {"name": owner},
        "plugins": [
            {
                "name": name,
                "source": f"./{plugin_dir}",
                "description": versioned.metadata.description,
            }
        ],
    }
    files[ROOT_MARKETPLACE] = json.dumps(marketplace, indent=2, ensure_ascii=False) + "\n"
    return versioned.metadata.version, files


def write_repo_bundle(root: Path, files: dict[str, str], *, plugin_dir: str = DEFAULT_PLUGIN_DIR) -> None:
    """Write *files* under *root*, scrubbing ``<root>/<plugin_dir>`` first (no stale files)."""
    from cisternal.export.write import write_bundle  # noqa: PLC0415

    shutil.rmtree(root / _check_dir(plugin_dir), ignore_errors=True)
    write_bundle(files, root)


def check_repo_bundle(
    root: Path, files: dict[str, str], *, plugin_dir: str = DEFAULT_PLUGIN_DIR
) -> list[str]:
    """Problems that make the committed layout differ from *files* (empty = current)."""
    problems: list[str] = []
    for rel, content in sorted(files.items()):
        path = root / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"stale: {rel}")
    bundle_root = root / _check_dir(plugin_dir)
    if bundle_root.is_dir():
        for path in sorted(p for p in bundle_root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if rel not in files:
                problems.append(f"extra: {rel}")
    return problems


def index_entry(
    bundle: AssetBundle,
    *,
    repo: str,
    plugin_dir: str = DEFAULT_PLUGIN_DIR,
    ref: str | None = None,
) -> dict[str, Any]:
    """A ``marketplace.json`` entry for a family index pointing at this repo's bundle.

    ``ref`` defaults to ``v<version>`` (the release tag; the local ``+digest``
    is dropped), the same release ``launch = "uvx"`` pins the MCP server to.
    """
    version = bundle.metadata.version.split("+", 1)[0]
    return {
        "name": bundle.metadata.name,
        "description": bundle.metadata.description,
        "source": {
            "source": "git-subdir",
            "url": repo,
            "path": _check_dir(plugin_dir),
            "ref": ref or f"v{version}",
        },
    }
