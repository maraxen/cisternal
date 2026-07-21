"""AntigravityEmitter — real Antigravity plugin format (M13.1).

Historical note: prior to M13.1, this emitter produced a ``gemini-extension.json``
manifest (with ``agents``/``skills``/``commands`` name lists and an inline
``mcpServers`` key) plus Claude-shaped ``hooks/hooks.json`` and ``.mcp.json`` —
modeled on Claude Code's shape rather than Antigravity's actual plugin schema.
M13.1 replaces that with the real format, per praxia's in-progress
``crates/praxia-agent-assets/src/bundle_antigravity.rs`` (uncommitted as of
2026-07-21) plus manual confirmation that Antigravity plugins auto-discover
at ``~/.gemini/config/plugins/<name>/`` and that skills/hooks/MCP are the only
plugin-bundled surfaces — Antigravity has no file-based agent registration.

Output files (non-rust-parity mode):
    ``plugin.json`` (plugin root, NOT under a ``.claude-plugin/``-style dir)
        Always present. Fields: ``name``, ``description`` only — no
        ``version``, no ``contextFileName``, no ``settings``, no
        ``agents``/``skills``/``commands`` arrays.

    ``skills/<name>/SKILL.md``
        One per ``bundle.skills`` entry with a non-empty ``body``
        (fail-closed). Rendered via ``format_skill_markdown``.

    ``hooks.json`` (plugin root, NOT ``hooks/hooks.json``)
        Present only when ``bundle.hook_specs`` filtered for the
        "antigravity" surface is non-empty. Antigravity-specific schema, not
        Claude's: entries nest one level deeper under an arbitrary top-level
        key (the bundle's own name), only ``PreToolUse``/``PostToolUse`` are
        supported (other events are silently dropped), entries sharing a
        matcher aggregate into one ``hooks`` list, and the ``Bash`` matcher
        remaps to ``run_command``. Built via
        ``cisterna.export.hooks.build_antigravity_hooks``.

    ``mcp_config.json`` (plugin root, NOT ``.mcp.json``)
        Present only when ``bundle.mcp_servers`` is non-empty:
        ``{"mcpServers": {name: {"command": <first token>, "args": [...rest]}}}``
        — command is split into a bare string plus an args array, unlike
        Claude's ``{"command": [...]}`` array-only shape.

NOT emitted, intentionally:
    - ``agents/`` — Antigravity has no file-based agent/subagent registration.
      Confirmed both by praxia's adapter (a dedicated test asserts agents are
      never written even when the bundle has them) and by direct testing.
    - A rules directory — Antigravity rules live outside the plugin system.

Known open gaps vs. the praxia reference (flagged, not silently resolved):
    - MCP server ``env`` vars are not carried through, matching praxia's
      current WIP adapter — which also drops them. Unclear whether that's
      deliberate or an oversight upstream; worth reconciling once praxia's
      change lands and this module can be re-checked against it.
    - Praxia's adapter also bundles hook script *bodies* into
      ``scripts/<script>`` files (referenced as ``./scripts/<script>`` in
      hooks.json), because its ``HookSpecAsset`` carries a ``content``
      field. Cisterna's ``HookSpecAsset`` has no equivalent field yet, so
      ``spec.script`` is used as-is in the ``command`` field here — the same
      external-reference convention the other three surfaces already use.
      Self-contained script bundling is a follow-up once cisterna's asset
      model grows a content field, not something to smuggle in here.

The rust-parity codepath (``antigravity_rust.py``) is untouched — it is
pinned to praxia's last-*committed* Antigravity shape (still the old
Claude-mirroring layout) and should be updated separately once praxia
commits its own rewrite and regenerates conformance goldens.
"""

from __future__ import annotations

import json

from cisterna.assets.bundle import AssetBundle
from cisterna.export._markdown import format_skill_markdown
from cisterna.export.antigravity_rust import emit_antigravity_rust_parity
from cisterna.export.base import Emitter
from cisterna.export.hooks import build_antigravity_hooks, hooks_for_surface

_PLUGIN_JSON_PATH = "plugin.json"
_HOOKS_JSON_PATH = "hooks.json"
_MCP_JSON_PATH = "mcp_config.json"


class AntigravityEmitter(Emitter):
    """Emit an AssetBundle as an Antigravity plugin directory.

    Pure, deterministic, never-raises. See module docstring for the full
    output file set and the M13.1 real-plugin-format spec.
    """

    def __init__(self, *, rust_parity: bool = False) -> None:
        self._rust_parity = rust_parity

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        """Render *bundle* to the Antigravity plugin file dict.

        Args:
            bundle: The :class:`~cisterna.assets.bundle.AssetBundle` to render.

        Returns:
            Legacy mode: plugin.json + skills/hooks.json/mcp_config.json files.
            Rust parity mode (M12.3): praxia-shaped file set matching praxia's
                last-committed (pre-M13.1) Antigravity adapter.
        """
        if self._rust_parity:
            return emit_antigravity_rust_parity(bundle)

        files: dict[str, str] = {}

        plugin_json = {
            "name": bundle.metadata.name,
            "description": bundle.metadata.description or "",
        }
        files[_PLUGIN_JSON_PATH] = json.dumps(plugin_json, sort_keys=True, indent=2)

        for skill in bundle.skills:
            if skill.body:
                files[f"skills/{skill.name}/SKILL.md"] = format_skill_markdown(skill)

        hook_specs = hooks_for_surface(bundle.hook_specs, "antigravity")
        if hook_specs:
            hooks_root = build_antigravity_hooks(hook_specs, bundle.metadata.name)
            files[_HOOKS_JSON_PATH] = json.dumps(hooks_root, sort_keys=True, indent=2)

        if bundle.mcp_servers:
            mcp_servers: dict[str, object] = {}
            for srv in bundle.mcp_servers:
                command = list(srv.command)
                server_obj: dict[str, object] = {
                    "command": command[0] if command else "",
                }
                if len(command) > 1:
                    server_obj["args"] = command[1:]
                mcp_servers[srv.name] = server_obj
            files[_MCP_JSON_PATH] = json.dumps(
                {"mcpServers": mcp_servers},
                sort_keys=True,
                indent=2,
            )

        return files
