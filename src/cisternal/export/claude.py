"""ClaudeEmitter — Claude Code plugin format emitter (M13: real plugin spec).

Historical note: prior to M13, this emitter produced a non-standard
``plugin.json`` that stuffed ``commands``/``mcpServers`` keys into the
manifest and emitted no other files. M3.1b (see
``tests/test_export_regression_m31b.py``) deliberately froze that shape
while the other three surfaces (cursor/copilot/antigravity) were upgraded
to the real per-file asset layout. M13 reverses that freeze: Claude Code's
actual plugin manifest schema (per code.claude.com/docs/en/plugins) only
has ``name``/``description``/``version``/``author``/``homepage``/
``repository``/``license`` — no ``commands``, no ``mcpServers``. Those
concepts are represented by files on disk instead.

Output files (non-rust-parity mode):
    ``.claude-plugin/plugin.json``
        Always present. Fields: ``name``, ``version``, ``description``
        (description defaults to ``""``). No ``commands``/``mcpServers``
        keys — the real schema doesn't have them.

    ``agents/<name>.md``
        One per ``bundle.agents`` entry with a non-empty ``body``
        (fail-closed, mirrors ``cursor.py``/``copilot.py``). Rendered via
        ``format_agent_markdown``. Note: plain ``agents/<name>.md``, NOT
        ``.agent.md`` (that's Cursor's convention, not Claude Code's).

    ``skills/<name>/SKILL.md``
        One per ``bundle.skills`` entry with a non-empty ``body``
        (fail-closed). Rendered via ``format_skill_markdown``.

    ``hooks/hooks.json``
        Present only when ``bundle.hook_specs`` filtered for the "claude"
        surface is non-empty. Built via
        ``cisternal.export.hooks.build_claude_style_hooks``, wrapped as
        ``{"hooks": <result>}``.

    ``hooks/scripts/<name>`` (#6859)
        One per hook spec with ``content`` (its script body, basename of
        ``script``) and per resource of those specs. A spec with content
        gets the command ``"${CLAUDE_PLUGIN_ROOT}"/hooks/scripts/<name>``.

    ``.mcp.json`` (root, NOT under ``.claude-plugin/``)
        Present only when ``bundle.mcp_servers`` is non-empty:
        ``{"mcpServers": {name: {"command": "...", "args": [...], "env": {...}}}}``.
        ``command`` is a single executable string (the first element of the
        argv tuple); ``args`` holds the remaining argv elements and is
        omitted when there are none. Matches Claude Code's actual
        ``.mcp.json`` schema (a bare argv array in ``command`` is rejected —
        see git history for the confirmed production failure).

    ``commands/<name>.md``
        Only when ``emit_command_bodies=True``, one per ``bundle.commands``
        entry with a non-empty ``body``. This is the real Claude Code
        ``commands/`` directory concept and is unaffected by M13.

    ``.claude-plugin/marketplace.json``
        Present only when ``bundle.marketplace`` is set. Renders the
        [plugin.marketplace] table (name, owner, plugin entries) per
        code.claude.com's local-marketplace schema.

    ``.claude-plugin/cisternal-provenance.json``
        SHA-256 provenance sidecar. Computed over the full non-provenance
        file set above (now larger than the M3-era two-file set) to avoid
        self-reference. See ``export/_hash.py`` for the canonical payload
        format.

B2 resolution — distinct hashes:
    - Provenance digest (``bundle_sha256``): over the file dict minus the sidecar.
    - Per-file content_sha256 (``WriteResult``): separate per-file hash computed
      by ``write_bundle`` — NOT the same value.

NEVER-RAISE: empty bundle → valid manifest with name/version/description only.
DETERMINISTIC: identical bundle → byte-identical output (AC-M3-6).
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath

from cisternal.assets.bundle import AssetBundle, ConfigOptionAsset, HookSpecAsset, McpAsset
from cisternal.export._hash import bundle_sha256
from cisternal.export._markdown import format_agent_markdown, format_skill_markdown
from cisternal.export.base import Emitter
from cisternal.export.claude_rust import emit_claude_rust_parity
from cisternal.export.hooks import build_claude_style_hooks, hooks_for_surface

_log = logging.getLogger("cisternal.export")
_PLUGIN_JSON_PATH = ".claude-plugin/plugin.json"
_PROVENANCE_PATH = ".claude-plugin/cisternal-provenance.json"
_COMMAND_BODY_DIR = "commands"
_HOOKS_JSON_PATH = "hooks/hooks.json"
_HOOK_SCRIPTS_DIR = "hooks/scripts"
_MCP_JSON_PATH = ".mcp.json"
_MARKETPLACE_JSON_PATH = ".claude-plugin/marketplace.json"


class ClaudeEmitter(Emitter):
    """Emit an AssetBundle as a Claude Code plugin directory.

    Pure, deterministic, never-raises. See module docstring for the full
    output file set and the M13 real-plugin-format spec.
    """

    def __init__(
        self,
        *,
        emit_command_bodies: bool = False,
        rust_parity: bool = False,
    ) -> None:
        self._emit_command_bodies = emit_command_bodies
        self._rust_parity = rust_parity

    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        """Render *bundle* to the Claude plugin file dict.

        Args:
            bundle: The :class:`~cisternal.assets.bundle.AssetBundle` to render.

        Returns:
            Legacy mode: plugin.json + agents/skills/hooks/.mcp.json files +
                provenance sidecar (and optional command bodies).
            Rust parity mode (M12.2): praxia-shaped file set without provenance sidecar.
        """
        if self._rust_parity:
            return emit_claude_rust_parity(bundle)

        manifest = _build_manifest(bundle)
        plugin_json = json.dumps(manifest, sort_keys=True, indent=2)

        files: dict[str, str] = {_PLUGIN_JSON_PATH: plugin_json}

        hook_specs = hooks_for_surface(bundle.hook_specs, "claude")

        emit_agents = tuple(a for a in bundle.agents if a.body)
        emit_skills = tuple(s for s in bundle.skills if s.body)

        for agent in emit_agents:
            files[f"agents/{agent.name}.md"] = format_agent_markdown(agent)

        for skill in emit_skills:
            files[f"skills/{skill.name}/SKILL.md"] = format_skill_markdown(skill)
            for resource_path, content in skill.resources:
                files[f"skills/{skill.name}/{resource_path}"] = content

        if hook_specs:
            hooks_root = build_claude_style_hooks(
                hook_specs, plugin_script_dir=_HOOK_SCRIPTS_DIR
            )
            files[_HOOKS_JSON_PATH] = json.dumps(
                {"hooks": hooks_root},
                sort_keys=True,
                indent=2,
            )
            for name, body in _bundled_hook_files(hook_specs).items():
                files[f"{_HOOK_SCRIPTS_DIR}/{name}"] = body

        if bundle.mcp_servers:
            mcp_obj = {
                "mcpServers": {
                    srv.name: _mcp_server_obj(srv) for srv in bundle.mcp_servers
                }
            }
            files[_MCP_JSON_PATH] = json.dumps(mcp_obj, sort_keys=True, indent=2)

        if bundle.marketplace is not None:
            owner: dict[str, str] = {
                "name": bundle.marketplace.owner_name or bundle.metadata.name,
            }
            if bundle.marketplace.owner_email:
                owner["email"] = bundle.marketplace.owner_email
            if bundle.marketplace.owner_url:
                owner["url"] = bundle.marketplace.owner_url
            marketplace_obj = {
                "name": bundle.marketplace.name,
                "owner": owner,
                "plugins": [{"name": bundle.metadata.name, "source": "./"}],
            }
            files[_MARKETPLACE_JSON_PATH] = json.dumps(
                marketplace_obj, sort_keys=True, indent=2
            )

        if self._emit_command_bodies:
            for cmd in bundle.commands:
                if cmd.body:
                    path = f"{_COMMAND_BODY_DIR}/{cmd.name}.md"
                    files[path] = cmd.body

        # Provenance digest covers only the non-provenance files.
        non_provenance = {
            path: contents
            for path, contents in files.items()
            if _PROVENANCE_PATH not in path
        }
        digest = bundle_sha256(non_provenance)
        provenance_json = json.dumps({"sha256": digest}, sort_keys=True)

        files[_PROVENANCE_PATH] = provenance_json
        return files


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _bundled_hook_files(hook_specs: tuple[HookSpecAsset, ...]) -> dict[str, str]:
    """Map ``hooks/scripts/<name>`` basename to body for every bundled hook file (#6859).

    A spec contributes its script (basename of ``spec.script``) and each of its
    resources, only when it carries ``content``. Specs arrive in the bundle's
    sorted order, so on a basename clash the first file wins and nothing raises.
    """
    files: dict[str, str] = {}
    for spec in hook_specs:
        if not spec.content:
            continue
        candidates = [(PurePosixPath(spec.script).name, spec.content), *spec.resources]
        for name, body in candidates:
            previous = files.setdefault(name, body)
            if previous != body:
                # The loader refuses such clashes; a programmatic bundle can still
                # reach here, so keep the first file and say so.
                _log.warning(
                    "cisternal.export: hook file %s clashes with another hook file of "
                    "different content; keeping the first",
                    name,
                )
    return files


def _mcp_server_obj(srv: McpAsset) -> dict[str, object]:
    """Build one ``mcpServers.<name>`` entry from an ``McpAsset``.

    Claude Code's ``.mcp.json`` schema expects ``command`` as a single
    executable string with a separate ``args`` array for the remaining
    argv — NOT the whole argv tuple crammed into ``command``. ``args`` is
    omitted entirely when there are no arguments (mirrors this file's other
    sparse-field conventions, e.g. optional keys in the marketplace block).
    Defensive: an empty ``command`` tuple (shouldn't happen — see
    ``assets/manifest.py::_load_mcp``) falls back to ``""`` rather than
    raising, per the NEVER-RAISE emitter contract.
    """
    command = srv.command
    obj: dict[str, object] = {
        "command": command[0] if command else "",
        "env": dict(srv.env),
    }
    if len(command) > 1:
        obj["args"] = list(command[1:])
    return obj


def _build_manifest(bundle: AssetBundle) -> dict[str, object]:
    """Build the plugin.json object from *bundle*.

    Always includes ``name``, ``version``, ``description``. Per the real
    Claude Code plugin manifest schema, there are no ``commands`` or
    ``mcpServers`` keys — those concepts are represented by files on disk
    instead (``commands/<name>.md``, ``.mcp.json``).
    """
    meta = bundle.metadata
    manifest: dict[str, object] = {
        "name": meta.name,
        "version": meta.version,
        "description": meta.description or "",
    }
    if bundle.config_options:
        # Claude Code's `userConfig`: the user is asked for these when the plugin is enabled and the saved
        # values land in settings.json under pluginConfigs["<plugin>@<marketplace>"].options. Nothing here
        # substitutes ${user_config.*} anywhere else: other surfaces would receive the placeholder verbatim
        # and a hook that references an unsaved option does not run.
        manifest["userConfig"] = {
            option.key: _user_config_entry(option) for option in bundle.config_options
        }
    return manifest


def _user_config_entry(option: ConfigOptionAsset) -> dict[str, object]:
    entry: dict[str, object] = {
        "type": option.type,
        "title": option.title or option.key,
        "description": option.description,
    }
    if option.options:
        entry["options"] = list(option.options)
    if option.default is not None:
        entry["default"] = option.default
    return entry
