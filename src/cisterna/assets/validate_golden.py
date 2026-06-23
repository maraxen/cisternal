"""Validate emitted asset bundles against golden digests (M3.1a)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from cisterna.assets.bundle import AssetBundle
from cisterna.export._hash import bundle_sha256
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.copilot import CopilotEmitter
from cisterna.export.cursor import CursorEmitter

_PROVENANCE_FRAGMENT = "cisterna-provenance.json"
_EMITTERS: dict[str, Callable[[AssetBundle], dict[str, str]]] = {
    "claude": lambda bundle: ClaudeEmitter().emit(bundle),
    "cursor": lambda bundle: CursorEmitter().emit(bundle),
    "copilot": lambda bundle: CopilotEmitter().emit(bundle),
}


def emit_claude_files(
    bundle: AssetBundle,
    *,
    emit_command_bodies: bool = False,
) -> dict[str, str]:
    """Emit Claude surface files for *bundle*."""
    return ClaudeEmitter(emit_command_bodies=emit_command_bodies).emit(bundle)


def emit_surface_files(
    bundle: AssetBundle,
    surface: str,
    *,
    emit_command_bodies: bool = False,
) -> dict[str, str]:
    """Emit files for *surface* (claude, cursor, or copilot)."""
    if surface == "claude":
        return emit_claude_files(bundle, emit_command_bodies=emit_command_bodies)
    if surface not in _EMITTERS:
        msg = f"unsupported validate surface: {surface!r}"
        raise ValueError(msg)
    return _EMITTERS[surface](bundle)


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
