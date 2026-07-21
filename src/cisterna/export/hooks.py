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


_ANTIGRAVITY_MATCHER_REMAP = {"Bash": "run_command"}


def build_antigravity_hooks(
    hook_specs: tuple[HookSpecAsset, ...],
    plugin_name: str,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Antigravity-shaped hooks (mirrors praxia bundle_antigravity.rs, M13.1).

    Schema differs from Claude/Cursor/Copilot's ``build_claude_style_hooks``:
    - Only ``PreToolUse``/``PostToolUse`` are supported; every other event is
      silently dropped (Antigravity has no other hook events).
    - Entries aggregate by matcher: multiple hooks sharing a matcher within
      the same event append into one entry's ``hooks`` list, rather than one
      entry per hook.
    - The ``Bash`` matcher remaps to ``run_command``; all other matchers
      pass through unchanged.
    - The whole object nests one level deeper than Claude's shape, under an
      arbitrary top-level key — *plugin_name* is used here (praxia's own
      in-progress adapter hardcodes ``"praxia"`` since it exports itself;
      cisterna is a generic exporter, so the bundle's own name is the
      sensible general default).
    - When a spec carries ``content`` (M13.2: the manifest gave it a
      ``path``), the command references the bundled ``./scripts/<script>``
      file the caller writes alongside this JSON — matching praxia's
      self-contained convention. Specs without content keep referencing
      ``spec.script`` as a literal command, same as Claude/Cursor/Copilot —
      deliberately NOT switching to a ``./scripts/`` reference in that case,
      since no such file gets bundled and that would just dangle.
    """
    pre_tool: list[dict[str, object]] = []
    post_tool: list[dict[str, object]] = []

    for spec in hook_specs:
        if spec.event not in ("PreToolUse", "PostToolUse"):
            continue

        matcher = _ANTIGRAVITY_MATCHER_REMAP.get(spec.matcher, spec.matcher)
        command = f"./scripts/{spec.script}" if spec.content else spec.script
        hook_cmd: dict[str, str] = {"type": "command", "command": command}
        bucket = pre_tool if spec.event == "PreToolUse" else post_tool

        existing = next((e for e in bucket if e["matcher"] == matcher), None)
        if existing is not None:
            existing["hooks"].append(hook_cmd)  # type: ignore[union-attr]
        else:
            bucket.append({"matcher": matcher, "hooks": [hook_cmd]})

    events: dict[str, list[dict[str, object]]] = {}
    if pre_tool:
        events["PreToolUse"] = pre_tool
    if post_tool:
        events["PostToolUse"] = post_tool

    return {plugin_name: events}
