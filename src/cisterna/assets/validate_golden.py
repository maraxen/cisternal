"""Validate emitted asset bundles against golden digests (M3.1a)."""

from __future__ import annotations

from pathlib import Path

from cisterna.assets.bundle import AssetBundle
from cisterna.export._hash import bundle_sha256
from cisterna.export.registry import get_emitter

_PROVENANCE_FRAGMENT = "cisterna-provenance.json"


def emit_claude_files(
    bundle: AssetBundle,
    *,
    emit_command_bodies: bool = False,
) -> dict[str, str]:
    """Emit Claude surface files for *bundle*."""
    emitter = get_emitter("claude", emit_command_bodies=emit_command_bodies)
    if emitter is None:
        msg = "claude emitter is not registered"
        raise ValueError(msg)
    return emitter.emit(bundle)


def emit_surface_files(
    bundle: AssetBundle,
    surface: str,
    *,
    emit_command_bodies: bool = False,
) -> dict[str, str]:
    """Emit files for *surface* via the emitter registry."""
    if surface != "claude" and emit_command_bodies:
        msg = f"emit_command_bodies applies to claude surface only, not {surface!r}"
        raise ValueError(msg)
    emitter = get_emitter(
        surface,
        emit_command_bodies=emit_command_bodies if surface == "claude" else False,
    )
    if emitter is None:
        msg = f"unsupported validate surface: {surface!r}"
        raise ValueError(msg)
    return emitter.emit(bundle)


def surface_digest(
    bundle: AssetBundle,
    surface: str,
    *,
    emit_command_bodies: bool = False,
) -> str:
    """Return golden-style digest for *surface* (provenance sidecar excluded)."""
    if surface != "claude" and emit_command_bodies:
        msg = f"emit_command_bodies applies to claude surface only, not {surface!r}"
        raise ValueError(msg)
    files = emit_surface_files(
        bundle,
        surface,
        emit_command_bodies=emit_command_bodies,
    )
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
