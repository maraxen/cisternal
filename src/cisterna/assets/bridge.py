"""PraxiaBundle bridge and subprocess rust digest (M12.1)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from cisterna.assets.bundle import AssetBundle, HookSpecAsset, McpAsset

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFORMANCE_ROOT = _REPO_ROOT / "tests" / "conformance"
_EXPECTED_DIR = _CONFORMANCE_ROOT / "expected"
_MANIFEST_MINIMAL_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def asset_bundle_to_praxia_json(bundle: AssetBundle) -> dict[str, Any]:
    """Map cisterna AssetBundle to PraxiaBundle JSON for praxia-agent-assets."""
    return {
        "metadata": {
            "name": bundle.metadata.name,
            "version": bundle.metadata.version,
            "description": bundle.metadata.description or "",
        },
        "skills": [
            {
                "name": skill.name,
                "description": skill.description or "",
                "body": skill.body,
            }
            for skill in bundle.skills
        ],
        "agents": [
            {
                "name": agent.name,
                "description": agent.description or "",
                "tools": list(agent.tools),
                "model": agent.model,
                "body": agent.body,
            }
            for agent in bundle.agents
        ],
        "commands": [
            {"name": cmd.name, "body": cmd.body}
            for cmd in bundle.commands
        ],
        "hook_specs": [_hook_spec_to_json(hook) for hook in bundle.hook_specs],
        "mcp_servers": [_mcp_to_json(mcp) for mcp in bundle.mcp_servers],
        "workflows": [],
        "pipelines": [],
    }


def _hook_spec_to_json(hook: HookSpecAsset) -> dict[str, Any]:
    return {
        "event": hook.event,
        "matcher": hook.matcher,
        "script": hook.script,
        "tier": hook.tier or "",
        "surfaces": list(hook.surfaces),
    }


def _mcp_to_json(mcp: McpAsset) -> dict[str, Any]:
    env: dict[str, str] = dict(mcp.env)
    return {
        "name": mcp.name,
        "command": list(mcp.command),
        "env": env,
    }


def resolve_bundle_hash_bin(bin_path: str | None = None) -> str | None:
    """Return path to bundle-hash binary from arg or env."""
    raw = (bin_path or os.environ.get("CISTERNA_PRAXIA_ASSETS_BIN", "")).strip()
    return raw or None


def rust_surface_digest(
    bundle: AssetBundle,
    surface: str,
    *,
    bin_path: str | None = None,
) -> str:
    """Compute surface digest via praxia ``bundle-hash`` subprocess."""
    resolved = resolve_bundle_hash_bin(bin_path)
    if resolved is None:
        msg = "CISTERNA_PRAXIA_ASSETS_BIN is unset; cannot run rust parity digest"
        raise RuntimeError(msg)

    payload = json.dumps(asset_bundle_to_praxia_json(bundle), sort_keys=True)
    try:
        proc = subprocess.run(
            [resolved, "--surface", surface],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        msg = f"failed to execute bundle-hash at {resolved!r}: {exc}"
        raise RuntimeError(msg) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        msg = f"bundle-hash exited {proc.returncode}"
        if detail:
            msg = f"{msg}: {detail}"
        raise RuntimeError(msg)

    digest = proc.stdout.strip()
    if not digest:
        msg = "bundle-hash returned empty digest"
        raise RuntimeError(msg)
    return digest


def conformance_expected_path(surface: str) -> Path:
    """Return pinned expected digest path for manifest_minimal conformance."""
    return _EXPECTED_DIR / f"{surface}.sha256"


def conformance_manifest_path() -> Path:
    """Return manifest_minimal path used for rust parity conformance."""
    return _MANIFEST_MINIMAL_FIXTURE


def load_conformance_bundle_json() -> dict[str, Any]:
    """Load canonical PraxiaBundle JSON fixture."""
    path = _CONFORMANCE_ROOT / "manifest_minimal.bundle.json"
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_praxia_json(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize bridge output for structural comparison with fixture."""
    return json.loads(json.dumps(data, sort_keys=True))
