"""Bundle snapshots: a manifest's resolved assets as one JSON file.

A manifest (``.praxia/manifest.toml``) points at skill/agent/hook files
elsewhere in a source checkout, so it cannot ship inside a wheel. A snapshot
is the same :class:`AssetBundle` with every file's content inlined, written
once at dev/build time (``cisternal assets snapshot``) and shipped as package
data. ``cisternal.plugin`` reads it when no source checkout is available, so
an installed tool can install its own plugin without its repo.

The format is versioned (``schema``); readers reject versions they do not
know rather than guessing.
"""

from __future__ import annotations

import json
from typing import Any

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    HookSpecAsset,
    MarketplaceAsset,
    McpAsset,
    SkillAsset,
)
from cisternal.assets.inspect_json import _serialize_bundle

SNAPSHOT_SCHEMA = 1

__all__ = ["SNAPSHOT_SCHEMA", "bundle_from_dict", "dumps_snapshot", "loads_snapshot"]


def dumps_snapshot(bundle: AssetBundle) -> str:
    """Serialize *bundle* deterministically (sorted keys, trailing newline)."""
    data = _serialize_bundle(bundle)
    # Fields added after schema 1 shipped are written only when non-default,
    # so upgrading cisternal does not make every already-committed snapshot
    # "stale" under `assets snapshot --check`. Readers default them back.
    for srv in data.get("mcp_servers", ()):
        for key, default in _MCP_LATE_DEFAULTS.items():
            if srv.get(key) == default:
                srv.pop(key)
    doc = {"schema": SNAPSHOT_SCHEMA, "bundle": data}
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# McpAsset fields added in 0.1.1a14 (`[plugin.mcp] launch` / `uvx_from`).
_MCP_LATE_DEFAULTS = {"launch": "path", "uvx_from": ""}


def loads_snapshot(text: str) -> AssetBundle:
    """Parse a snapshot written by :func:`dumps_snapshot`. Raises ``ValueError`` if malformed."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"bundle snapshot is not valid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(doc, dict) or doc.get("schema") != SNAPSHOT_SCHEMA:
        found = doc.get("schema") if isinstance(doc, dict) else None
        msg = f"unsupported bundle snapshot schema {found!r} (expected {SNAPSHOT_SCHEMA})"
        raise ValueError(msg)
    if not isinstance(doc.get("bundle"), dict):
        msg = "malformed bundle snapshot: 'bundle' must be an object"
        raise ValueError(msg)
    return bundle_from_dict(doc["bundle"])


def bundle_from_dict(data: dict[str, Any]) -> AssetBundle:
    """Inverse of ``inspect_json._serialize_bundle``."""
    try:
        marketplace = data.get("marketplace")
        return AssetBundle(
            metadata=BundleMetadata(**data["metadata"]),
            commands=tuple(CommandAsset(**c) for c in data.get("commands", ())),
            mcp_servers=tuple(
                McpAsset(
                    name=m["name"],
                    command=tuple(m.get("command", ())),
                    env=tuple((k, v) for k, v in m.get("env", ())),
                    launch=m.get("launch", "path"),
                    uvx_from=m.get("uvx_from", ""),
                )
                for m in data.get("mcp_servers", ())
            ),
            skills=tuple(
                SkillAsset(
                    name=s["name"],
                    description=s.get("description", ""),
                    body=s.get("body", ""),
                    triggers=tuple(s.get("triggers", ())),
                    resources=tuple((p, c) for p, c in s.get("resources", ())),
                )
                for s in data.get("skills", ())
            ),
            agents=tuple(
                AgentAsset(
                    name=a["name"],
                    description=a.get("description", ""),
                    tools=tuple(a.get("tools", ())),
                    model=a.get("model"),
                    body=a.get("body", ""),
                )
                for a in data.get("agents", ())
            ),
            hook_specs=tuple(
                HookSpecAsset(
                    event=h["event"],
                    matcher=h["matcher"],
                    script=h["script"],
                    tier=h.get("tier", ""),
                    surfaces=tuple(h.get("surfaces", ())),
                    content=h.get("content", ""),
                )
                for h in data.get("hook_specs", ())
            ),
            marketplace=MarketplaceAsset(**marketplace) if marketplace else None,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        msg = f"malformed bundle snapshot: {exc!r}"
        raise ValueError(msg) from exc
