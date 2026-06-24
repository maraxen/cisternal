"""ClaudeEmitter — Claude plugin format emitter (spec §2, B1 resolution).

Mirrors praxia ``crates/praxia-agent-assets/src/bundle_claude.rs``.

Output files:
    ``.claude-plugin/plugin.json``
        Always present.  Fields:
        - ``name``, ``version``, ``description`` (always; description defaults to "").
        - ``commands``: sorted list of command names — present ONLY if non-empty.
        - ``mcpServers``: ``{name: {"command": [...], "env": {...}}}`` — present
          ONLY if non-empty (always omitted in M3).

    ``.claude-plugin/cisterna-provenance.json``
        SHA-256 provenance sidecar.  Computed over the non-provenance file set
        (i.e. just ``plugin.json`` in M3) to avoid self-reference.  See
        ``export/_hash.py`` for the canonical payload format.

B1 resolution — names-only manifest:
    The M3 deliverable lists tool names; per-command ``commands/<name>.md``
    files are deferred to M3.1 (requires a validated Claude command schema).

B2 resolution — distinct hashes:
    - Provenance digest (``bundle_sha256``): over the file dict minus the sidecar.
    - Per-file content_sha256 (``WriteResult``): separate per-file hash computed
      by ``write_bundle`` — NOT the same value.

NEVER-RAISE: empty bundle → valid manifest with name/version/description only.
DETERMINISTIC: identical bundle → byte-identical output (AC-M3-6).
"""

from __future__ import annotations

import json

from cisterna.assets.bundle import AssetBundle
from cisterna.export._hash import bundle_sha256
from cisterna.export.claude_rust import emit_claude_rust_parity
from cisterna.export.base import Emitter

_PLUGIN_JSON_PATH = ".claude-plugin/plugin.json"
_PROVENANCE_PATH = ".claude-plugin/cisterna-provenance.json"
_COMMAND_BODY_DIR = "commands"


class ClaudeEmitter(Emitter):
    """Emit an AssetBundle as a Claude plugin directory.

    Output is two files:
    - ``.claude-plugin/plugin.json`` — plugin manifest (names-only, B1).
    - ``.claude-plugin/cisterna-provenance.json`` — SHA-256 provenance sidecar.

    Pure, deterministic, never-raises.  See module docstring for full spec.
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
            bundle: The :class:`~cisterna.assets.bundle.AssetBundle` to render.

        Returns:
            Legacy mode: plugin.json + provenance sidecar (and optional command bodies).
            Rust parity mode (M12.2): praxia-shaped file set without provenance sidecar.
        """
        if self._rust_parity:
            return emit_claude_rust_parity(bundle)

        manifest = _build_manifest(bundle)
        plugin_json = json.dumps(manifest, sort_keys=True, indent=2)

        files: dict[str, str] = {_PLUGIN_JSON_PATH: plugin_json}
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


def _build_manifest(bundle: AssetBundle) -> dict[str, object]:
    """Build the plugin.json object from *bundle*.

    Always includes ``name``, ``version``, ``description``.
    Conditionally includes ``commands`` (non-empty only) and
    ``mcpServers`` (non-empty only; always omitted in M3).
    """
    meta = bundle.metadata
    obj: dict[str, object] = {
        "name": meta.name,
        "version": meta.version,
        "description": meta.description or "",
    }

    if bundle.commands:
        # AssetBundle.commands is sorted at construction; no re-sort here (#2327).
        obj["commands"] = [cmd.name for cmd in bundle.commands]

    if bundle.mcp_servers:
        obj["mcpServers"] = {
            srv.name: {
                "command": list(srv.command),
                "env": dict(srv.env),
            }
            for srv in bundle.mcp_servers
        }

    return obj
