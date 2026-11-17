"""Copilot export: MCP servers in the shape the Copilot CLI validates (debt 3413).

The Copilot CLI's own schema, read from its installed package (app.js, version labels disagree: package.json 1.0.9 and the
banner 1.0.63; whether the plugin loader applies it to plugin servers was not traced), defines a stdio MCP server as
``{type?: "local"|"stdio", command: string, args: string[] (required), cwd?: string, env?: {string: string}}``; its plugin
docs show ``command`` as a string with a separate ``args`` array, never a list. cisternal wrote ``command`` as a list and no
``args``.
"""

from __future__ import annotations

import json

import pytest

from cisternal.assets.bundle import AssetBundle, BundleMetadata, McpAsset
from cisternal.export.copilot import CopilotEmitter
from cisternal.export.copilot_rust import emit_copilot_rust_parity

STDIO_KEYS = {"type", "command", "args", "cwd", "env"}


def _bundle(*servers: McpAsset) -> AssetBundle:
    return AssetBundle(metadata=BundleMetadata(name="demo", version="1.0.0", description="d"), mcp_servers=servers)


def _satisfies_copilot_stdio_schema(entry: object) -> None:
    """A stand-in for the CLI's zod schema: string command, required string-list args, optional string-map env."""
    assert isinstance(entry, dict) and set(entry) <= STDIO_KEYS, entry
    assert isinstance(entry["command"], str) and entry["command"], entry
    assert isinstance(entry["args"], list) and all(isinstance(a, str) for a in entry["args"]), entry
    env = entry.get("env", {})
    assert isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()), entry


def test_the_program_is_command_and_the_rest_are_args_in_both_files() -> None:
    files = CopilotEmitter().emit(_bundle(McpAsset(name="demo", command=("demo", "run-mcp", "--flag"), env={"K": "V"})))
    want = {"command": "demo", "args": ["run-mcp", "--flag"], "env": {"K": "V"}}
    assert json.loads(files["plugin.json"])["mcpServers"]["demo"] == want
    assert json.loads(files[".mcp.json"])["mcpServers"]["demo"] == want


def test_a_program_with_no_arguments_gets_an_empty_args_list_not_a_missing_one() -> None:
    files = CopilotEmitter().emit(_bundle(McpAsset(name="solo", command=("solo",))))
    entry = json.loads(files[".mcp.json"])["mcpServers"]["solo"]
    assert entry["command"] == "solo" and entry["args"] == [] and entry["env"] == {}


def test_every_emitted_server_satisfies_the_copilot_stdio_schema() -> None:
    files = CopilotEmitter().emit(
        _bundle(McpAsset(name="a", command=("a", "x")), McpAsset(name="b", command=("b",), env={"E": "1"}))
    )
    for path in ("plugin.json", ".mcp.json"):
        servers = json.loads(files[path])["mcpServers"]
        assert set(servers) == {"a", "b"}
        for entry in servers.values():
            _satisfies_copilot_stdio_schema(entry)


def test_no_server_means_no_mcp_files_and_no_mcpservers_key() -> None:
    files = CopilotEmitter().emit(_bundle())
    assert ".mcp.json" not in files and "mcpServers" not in json.loads(files["plugin.json"])


def test_emitting_is_deterministic() -> None:
    bundle = _bundle(McpAsset(name="demo", command=("demo", "run-mcp")))
    assert CopilotEmitter().emit(bundle) == CopilotEmitter().emit(bundle)


@pytest.mark.parametrize("command", [("demo", "run-mcp"), ("demo",)])
def test_the_rust_parity_path_is_untouched(command: tuple[str, ...]) -> None:
    """Parity mode reproduces the Rust emitter byte for byte; this change must not leak into it."""
    bundle = _bundle(McpAsset(name="demo", command=command))
    assert CopilotEmitter(rust_parity=True).emit(bundle) == emit_copilot_rust_parity(bundle)
