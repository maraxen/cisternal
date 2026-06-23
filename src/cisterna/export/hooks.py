"""HookSpec surface filtering and dialect helpers (M3.1b L15)."""

from __future__ import annotations

from cisterna.assets.bundle import HookSpecAsset

_EMIT_SURFACES = frozenset({"claude", "cursor", "copilot", "antigravity"})


def hooks_for_surface(
    hook_specs: tuple[HookSpecAsset, ...],
    surface: str,
) -> tuple[HookSpecAsset, ...]:
    """Return hook specs that apply to *surface* per L15."""
    if surface not in _EMIT_SURFACES:
        msg = f"unsupported emit surface: {surface!r}"
        raise ValueError(msg)

    selected: list[HookSpecAsset] = []
    for spec in hook_specs:
        if not spec.surfaces:
            selected.append(spec)
        elif surface in spec.surfaces:
            selected.append(spec)
    return tuple(selected)
