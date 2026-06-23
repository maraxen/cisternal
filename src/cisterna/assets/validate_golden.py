"""Validate emitted asset bundles against golden digests (M3.1a)."""

from __future__ import annotations

from pathlib import Path

from cisterna.assets.bundle import AssetBundle
from cisterna.export._hash import bundle_sha256
from cisterna.export.claude import ClaudeEmitter

_PROVENANCE_FRAGMENT = "cisterna-provenance.json"


def emit_claude_files(
    bundle: AssetBundle,
    *,
    emit_command_bodies: bool = False,
) -> dict[str, str]:
    """Emit Claude surface files for *bundle*."""
    return ClaudeEmitter(emit_command_bodies=emit_command_bodies).emit(bundle)


def surface_digest(
    bundle: AssetBundle,
    surface: str,
    *,
    emit_command_bodies: bool = False,
) -> str:
    """Return golden-style digest for *surface* (provenance sidecar excluded)."""
    if surface != "claude":
        raise ValueError(f"unsupported validate surface: {surface!r}")
    files = emit_claude_files(bundle, emit_command_bodies=emit_command_bodies)
    hashed = {
        path: contents
        for path, contents in files.items()
        if _PROVENANCE_FRAGMENT not in path
    }
    return bundle_sha256(hashed)


def golden_digest_path(
    surface: str,
    mode: str = "names_only",
    *,
    golden_root: Path | None = None,
) -> Path:
    """Return path to stored golden digest file."""
    root = golden_root or Path(__file__).resolve().parents[3] / "tests" / "golden"
    return root / surface / mode / "digest.sha256"
