"""HookSpec surface filtering and dialect helpers (M3.1b L15)."""

from __future__ import annotations

from collections import defaultdict

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


def build_claude_style_hooks(
    hook_specs: tuple[HookSpecAsset, ...],
) -> dict[str, list[dict[str, object]]]:
    """Claude-shaped nested hooks (praxia build_claude_hooks bundle adapter)."""
    events: dict[str, list[dict[str, object]]] = defaultdict(list)
    pre_tool: list[dict[str, object]] = []
    post_tool: list[dict[str, object]] = []

    for spec in hook_specs:
        hook_cmd: dict[str, str] = {"type": "command", "command": spec.script}
        entry: dict[str, object] = {
            "matcher": spec.matcher,
            "hooks": [hook_cmd],
        }

        if spec.event == "PreToolUse":
            pre_tool.append(entry)
            continue
        if spec.event == "PostToolUse":
            post_tool.append(entry)
            continue

        events[spec.event].append(entry)

    root: dict[str, list[dict[str, object]]] = dict(sorted(events.items()))
    if pre_tool:
        root["PreToolUse"] = pre_tool
    if post_tool:
        root["PostToolUse"] = post_tool
    return root
