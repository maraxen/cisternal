"""Tests for AC-M3-4, AC-M3-6 — ClaudeEmitter purity + determinism (M13 real plugin format).

AC-M3-4: Emitter cannot be instantiated (abstract); ClaudeEmitter.emit does zero I/O.
M13: plugin.json has name/version/description always, and never commands/mcpServers
     (real Claude Code plugin schema has no such keys — those concepts are
     represented by agents/skills/hooks/.mcp.json files instead); empty bundle OK.
AC-M3-6: emit twice → byte-identical dict including sidecar; sidecar sha256 ==
          bundle_sha256 of the non-provenance file set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    McpAsset,
)
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.export._hash import bundle_sha256
from cisternal.export.base import Emitter
from cisternal.export.claude import ClaudeEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(name: str = "test", version: str = "1.0.0", description: str = "") -> BundleMetadata:
    return BundleMetadata(name=name, version=version, description=description)


def _bundle(
    name: str = "test",
    version: str = "1.0.0",
    description: str = "",
    commands: tuple[CommandAsset, ...] = (),
    mcp_servers: tuple[McpAsset, ...] = (),
) -> AssetBundle:
    return AssetBundle(
        metadata=_meta(name, version, description),
        commands=commands,
        mcp_servers=mcp_servers,
    )


_PLUGIN_JSON_PATH = ".claude-plugin/plugin.json"
_PROVENANCE_PATH = ".claude-plugin/cisternal-provenance.json"


# ---------------------------------------------------------------------------
# AC-M3-4: Emitter is abstract; ClaudeEmitter.emit does zero I/O
# ---------------------------------------------------------------------------


def test_emitter_is_abstract() -> None:
    """Emitter cannot be instantiated directly (it is an ABC)."""
    with pytest.raises(TypeError):
        Emitter()  # type: ignore[abstract]


def test_claude_emitter_emit_does_no_filesystem_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """ClaudeEmitter.emit must not touch the filesystem (no open, no write_text)."""
    from pathlib import Path

    io_calls: list[str] = []

    def _spy_open(*args: object, **kwargs: object) -> object:
        io_calls.append(f"open({args!r})")
        raise AssertionError("ClaudeEmitter.emit called open() — must be pure")

    def _spy_write_text(self: Path, *args: object, **kwargs: object) -> None:
        io_calls.append(f"Path.write_text({args!r})")
        raise AssertionError("ClaudeEmitter.emit called Path.write_text() — must be pure")

    monkeypatch.setattr("builtins.open", _spy_open)
    monkeypatch.setattr(Path, "write_text", _spy_write_text)

    bundle = _bundle(commands=(CommandAsset(name="my_cmd", description="desc"),))
    result = ClaudeEmitter().emit(bundle)

    # If we reach here, no I/O occurred.
    assert io_calls == [], f"Unexpected I/O calls: {io_calls}"
    assert _PLUGIN_JSON_PATH in result


def test_claude_emitter_emit_does_no_filesystem_io_empty_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ClaudeEmitter.emit does no I/O even with an empty bundle."""
    from pathlib import Path

    io_calls: list[str] = []

    def _spy_open(*args: object, **kwargs: object) -> object:
        io_calls.append("open")
        raise AssertionError("open called during emit")

    def _spy_write_text(self: Path, *args: object, **kwargs: object) -> None:
        io_calls.append("write_text")
        raise AssertionError("write_text called during emit")

    monkeypatch.setattr("builtins.open", _spy_open)
    monkeypatch.setattr(Path, "write_text", _spy_write_text)

    result = ClaudeEmitter().emit(_bundle())
    assert io_calls == [], f"Unexpected I/O: {io_calls}"
    assert _PLUGIN_JSON_PATH in result


# ---------------------------------------------------------------------------
# AC-M3-5: plugin.json schema validation
# ---------------------------------------------------------------------------


def test_plugin_json_always_has_name_version_description() -> None:
    """plugin.json always contains name, version, description."""
    bundle = _bundle(name="myplugin", version="2.3.4", description="A plugin.")
    files = ClaudeEmitter().emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON_PATH])

    assert manifest["name"] == "myplugin"
    assert manifest["version"] == "2.3.4"
    assert manifest["description"] == "A plugin."


def test_plugin_json_description_defaults_to_empty_string() -> None:
    """When description is '', the manifest description field is ''."""
    bundle = _bundle(description="")
    files = ClaudeEmitter().emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON_PATH])
    assert manifest["description"] == ""


def test_plugin_json_commands_key_never_present() -> None:
    """plugin.json never has a 'commands' key — real schema has no such field."""
    bundle = _bundle(
        commands=(
            CommandAsset(name="zebra", description=None),
            CommandAsset(name="alpha", description=None),
            CommandAsset(name="mango", description=None),
        )
    )
    files = ClaudeEmitter().emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON_PATH])

    assert "commands" not in manifest


def test_plugin_json_commands_omitted_when_empty() -> None:
    """commands key remains absent when the bundle has no commands."""
    bundle = _bundle(commands=())
    files = ClaudeEmitter().emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON_PATH])

    assert "commands" not in manifest


def test_plugin_json_mcp_servers_key_never_present() -> None:
    """mcpServers is never a plugin.json key — represented by root .mcp.json instead."""
    bundle = _bundle(mcp_servers=())
    files = ClaudeEmitter().emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON_PATH])

    assert "mcpServers" not in manifest


def test_mcp_json_omitted_when_empty() -> None:
    """.mcp.json is omitted entirely when mcp_servers is empty."""
    bundle = _bundle(mcp_servers=())
    files = ClaudeEmitter().emit(bundle)
    assert ".mcp.json" not in files


def test_mcp_json_present_when_non_empty() -> None:
    """.mcp.json (root, not under .claude-plugin/) is emitted when mcp_servers is non-empty."""
    bundle = _bundle(
        mcp_servers=(
            McpAsset(
                name="my_server",
                command=("python", "-m", "server"),
                env=(("API_KEY", "secret"), ("DEBUG", "1")),
            ),
        )
    )
    files = ClaudeEmitter().emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON_PATH])
    assert "mcpServers" not in manifest

    assert ".mcp.json" in files
    mcp_doc = json.loads(files[".mcp.json"])
    srv = mcp_doc["mcpServers"]["my_server"]
    assert srv["command"] == ["python", "-m", "server"]
    assert srv["env"] == {"API_KEY": "secret", "DEBUG": "1"}


def test_empty_bundle_produces_valid_manifest_no_error() -> None:
    """Empty bundle → valid manifest with name/version/description only; never raises."""
    bundle = _bundle()
    files = ClaudeEmitter().emit(bundle)

    # Must have both output files.
    assert _PLUGIN_JSON_PATH in files
    assert _PROVENANCE_PATH in files

    manifest = json.loads(files[_PLUGIN_JSON_PATH])
    # Only the three always-present keys.
    assert set(manifest.keys()) == {"name", "version", "description"}


def test_provenance_sidecar_is_valid_json() -> None:
    """Provenance sidecar must be valid JSON with a 'sha256' key."""
    bundle = _bundle(commands=(CommandAsset(name="tool1", description="A tool."),))
    files = ClaudeEmitter().emit(bundle)

    provenance = json.loads(files[_PROVENANCE_PATH])
    assert "sha256" in provenance
    # Hex digest: 64 chars.
    assert len(provenance["sha256"]) == 64


# ---------------------------------------------------------------------------
# AC-M3-6: determinism + provenance sha256 integrity
# ---------------------------------------------------------------------------


def test_emit_twice_byte_identical_dict() -> None:
    """Calling emit twice on the same bundle produces byte-identical dicts."""
    bundle = _bundle(
        name="determinism",
        version="0.1.0",
        commands=(
            CommandAsset(name="foo", description="Foo tool."),
            CommandAsset(name="bar", description="Bar tool."),
        ),
    )
    emitter = ClaudeEmitter()
    result1 = emitter.emit(bundle)
    result2 = emitter.emit(bundle)

    assert result1 == result2, "Two identical emit calls must be byte-identical"


def test_emit_twice_byte_identical_including_sidecar() -> None:
    """Sidecar must also be byte-identical across two emit calls."""
    bundle = _bundle(
        name="sidecar-det",
        version="0.5.0",
        commands=(CommandAsset(name="tool_a", description="Tool A."),),
    )
    emitter = ClaudeEmitter()
    r1 = emitter.emit(bundle)
    r2 = emitter.emit(bundle)

    assert r1[_PROVENANCE_PATH] == r2[_PROVENANCE_PATH], (
        "Provenance sidecar must be byte-identical across two emit calls"
    )


def test_provenance_sha256_equals_bundle_sha256_of_non_provenance_set() -> None:
    """Sidecar sha256 == bundle_sha256 computed over just plugin.json (AC-M3-6, B2)."""
    bundle = _bundle(
        name="hash-check",
        version="1.0.0",
        commands=(
            CommandAsset(name="cmd1", description="Command 1."),
            CommandAsset(name="cmd2", description="Command 2."),
        ),
    )
    files = ClaudeEmitter().emit(bundle)

    # Non-provenance set = everything except the sidecar itself.
    non_provenance = {k: v for k, v in files.items() if k != _PROVENANCE_PATH}
    expected_digest = bundle_sha256(non_provenance)

    provenance = json.loads(files[_PROVENANCE_PATH])
    assert provenance["sha256"] == expected_digest, (
        f"Sidecar sha256 {provenance['sha256']!r} != bundle_sha256 {expected_digest!r}"
    )


def test_empty_bundle_provenance_sha256_integrity() -> None:
    """Even for an empty bundle, sidecar sha256 == bundle_sha256 of plugin.json."""
    bundle = _bundle()
    files = ClaudeEmitter().emit(bundle)

    non_provenance = {k: v for k, v in files.items() if k != _PROVENANCE_PATH}
    expected_digest = bundle_sha256(non_provenance)

    provenance = json.loads(files[_PROVENANCE_PATH])
    assert provenance["sha256"] == expected_digest


# ---------------------------------------------------------------------------
# M13: real plugin format — agents/, skills/, hooks/, .mcp.json (mirrors
# tests/test_export_cursor.py's fixture test pattern).
# ---------------------------------------------------------------------------


def test_claude_emit_manifest_minimal_fixture() -> None:
    """M13: manifest_minimal emits plugin.json, agents/, skills/, hooks/hooks.json."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    files = ClaudeEmitter().emit(report.bundle)

    assert _PLUGIN_JSON_PATH in files
    assert "agents/recon.md" in files
    assert "skills/demo-skill/SKILL.md" in files
    assert "hooks/hooks.json" in files

    manifest = json.loads(files[_PLUGIN_JSON_PATH])
    assert manifest["name"] == "fixture-plugin"
    assert manifest["version"] == "1.2.3"
    assert "commands" not in manifest
    assert "mcpServers" not in manifest

    hooks_doc = json.loads(files["hooks/hooks.json"])
    pre_tool = hooks_doc["hooks"]["PreToolUse"]
    assert pre_tool[0]["matcher"] == "Bash"

    assert "Agent body for tests" in files["agents/recon.md"]
    assert "Skill content" in files["skills/demo-skill/SKILL.md"]


def test_claude_fail_closed_omits_agent_file_without_body() -> None:
    """M13: agent with an empty body is not emitted as agents/<name>.md."""
    bundle = AssetBundle(
        metadata=BundleMetadata(name="p", version="1.0.0"),
        agents=(
            AgentAsset(name="ghost", description="Ghost", body=""),
            AgentAsset(name="present", description="Here", body="Agent body\n"),
        ),
    )

    files = ClaudeEmitter().emit(bundle)

    assert "agents/present.md" in files
    assert "agents/ghost.md" not in files
