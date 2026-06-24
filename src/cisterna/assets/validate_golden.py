"""Validate emitted asset bundles against golden digests (M3.1a)."""

from __future__ import annotations

from pathlib import Path

from cisterna.assets.bundle import AssetBundle
from cisterna.export._hash import bundle_sha256, bundle_sha256_rust
from cisterna.export.antigravity import AntigravityEmitter
from cisterna.export.claude import ClaudeEmitter
from cisterna.export.copilot import CopilotEmitter
from cisterna.export.cursor import CursorEmitter
from cisterna.export.base import Emitter
from cisterna.export.registry import get_emitter

_RUST_PARITY_EMITTERS: dict[str, type[Emitter]] = {
    "antigravity": AntigravityEmitter,
    "claude": ClaudeEmitter,
    "copilot": CopilotEmitter,
    "cursor": CursorEmitter,
}

_PROVENANCE_FRAGMENT = "cisterna-provenance.json"
_GOLDEN_ROOT = Path(__file__).resolve().parents[3] / "tests" / "golden"
_RUST_PARITY_GOLDEN_ROOT = _GOLDEN_ROOT / "rust_parity"


def resolve_golden_slug(manifest: Path | None) -> str | None:
    """Map a manifest path to a golden tree slug, or None if unknown."""
    if manifest is None:
        return "legacy"
    resolved = manifest.resolve()
    parent_name = resolved.parent.name
    if parent_name == "manifest_minimal":
        return "legacy"
    if parent_name == "manifest_dogfood_praxia":
        return "dogfood_praxia"
    if parent_name == ".praxia":
        return "self_manifest"
    return None


def golden_digest_path(
    surface: str,
    mode: str = "names_only",
    *,
    manifest: Path | None = None,
    golden_root: Path | None = None,
) -> Path:
    """Return path to stored golden digest file."""
    root = golden_root or _GOLDEN_ROOT
    slug = resolve_golden_slug(manifest)
    if slug is None:
        msg = f"unknown manifest for golden resolution: {manifest}"
        raise ValueError(msg)
    if slug == "legacy":
        return root / surface / mode / "digest.sha256"
    return root / slug / surface / mode / "digest.sha256"


def rust_parity_golden_digest_path(
    surface: str,
    *,
    manifest: Path | None = None,
    golden_root: Path | None = None,
) -> Path:
    """Return path to rust-parity golden digest."""
    root = golden_root or _RUST_PARITY_GOLDEN_ROOT
    slug = resolve_golden_slug(manifest)
    if slug is None:
        msg = f"unknown manifest for golden resolution: {manifest}"
        raise ValueError(msg)
    return root / slug / surface / "digest.sha256"


def emit_rust_parity_files(bundle: AssetBundle, surface: str) -> dict[str, str]:
    """Emit surface files using praxia byte parity (M12.2+)."""
    emitter_cls = _RUST_PARITY_EMITTERS.get(surface)
    if emitter_cls is None:
        msg = f"rust parity emit not implemented for surface: {surface!r}"
        raise ValueError(msg)
    return emitter_cls(rust_parity=True).emit(bundle)


def emit_claude_rust_parity_files(bundle: AssetBundle) -> dict[str, str]:
    """Emit Claude files using praxia byte parity (M12.2)."""
    return emit_rust_parity_files(bundle, "claude")


def surface_digest_rust_parity(bundle: AssetBundle, surface: str) -> str:
    """Return rust-canonical digest for *surface*."""
    if surface not in _RUST_PARITY_EMITTERS:
        msg = f"rust parity digest not implemented for surface: {surface!r}"
        raise ValueError(msg)
    files = emit_rust_parity_files(bundle, surface)
    return bundle_sha256_rust(files)


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


def write_golden_digest(
    bundle: AssetBundle,
    surface: str,
    *,
    manifest: Path,
    emit_command_bodies: bool = False,
) -> Path:
    """Write golden digest for *bundle* at the manifest-scoped path (dev helper)."""
    mode = "with_command_bodies" if emit_command_bodies else "names_only"
    digest = surface_digest(bundle, surface, emit_command_bodies=emit_command_bodies)
    path = golden_digest_path(surface, mode, manifest=manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest + "\n", encoding="utf-8")
    return path


def write_rust_parity_golden_digest(
    bundle: AssetBundle,
    surface: str,
    *,
    manifest: Path,
) -> Path:
    """Write rust-parity golden digest for *bundle* (dev helper)."""
    digest = surface_digest_rust_parity(bundle, surface)
    path = rust_parity_golden_digest_path(surface, manifest=manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest + "\n", encoding="utf-8")
    return path
