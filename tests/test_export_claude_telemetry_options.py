"""``userConfig`` in the rendered Claude plugin (spec 261116_telemetry-config-layers, FR-6)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from cisternal.assets.bundle import (
    AssetBundle,
    BundleMetadata,
    ConfigOptionAsset,
    McpAsset,
    TelemetryAsset,
)
from cisternal.export.antigravity import AntigravityEmitter
from cisternal.export.claude import ClaudeEmitter
from cisternal.export.copilot import CopilotEmitter
from cisternal.export.cursor import CursorEmitter
from cisternal.export.jcode import JCodeEmitter
from cisternal.export.opencode import OpenCodeEmitter
from cisternal.export.pi import PiEmitter

SPANS = ConfigOptionAsset(
    key="telemetry_spans",
    type="string",
    title="Span telemetry",
    description="Record call timing locally. 'inherit' defers to your machine config.",
    options=("inherit", "on", "off"),
    default="inherit",
)
SHADOW = ConfigOptionAsset(
    key="telemetry_shadow",
    type="string",
    title="Shadow records",
    description="Collect local verdict records.",
    options=("inherit", "on", "off"),
    default="inherit",
)
TELEMETRY = TelemetryAsset("demo", "demo", "telemetry_spans", "telemetry_shadow", False, True)


@pytest.fixture
def bundle() -> AssetBundle:
    return AssetBundle(
        metadata=BundleMetadata(name="demo", version="1.2.3", description="demo plugin"),
        mcp_servers=(McpAsset(name="demo", command=("demo", "run-mcp")),),
        telemetry=TELEMETRY,
        config_options=(SHADOW, SPANS),
    )


def _bare(bundle: AssetBundle) -> AssetBundle:
    return replace(bundle, telemetry=None, config_options=())


def test_userconfig_is_rendered_in_plugin_json(bundle: AssetBundle) -> None:
    plugin = json.loads(ClaudeEmitter().emit(bundle)[".claude-plugin/plugin.json"])
    assert plugin["name"] == "demo" and plugin["version"] == "1.2.3"
    assert list(plugin["userConfig"]) == ["telemetry_shadow", "telemetry_spans"]  # deterministic order
    assert plugin["userConfig"]["telemetry_spans"] == {
        "type": "string",
        "title": "Span telemetry",
        "description": "Record call timing locally. 'inherit' defers to your machine config.",
        "options": ["inherit", "on", "off"],
        "default": "inherit",
    }


def test_userconfig_omits_options_and_default_when_unset() -> None:
    option = ConfigOptionAsset(key="flag", type="boolean", title="", description="A flag.")
    bundle = AssetBundle(metadata=BundleMetadata(name="demo", version="1", description=""), config_options=(option,))
    entry = json.loads(ClaudeEmitter().emit(bundle)[".claude-plugin/plugin.json"])["userConfig"]["flag"]
    assert entry == {"type": "boolean", "title": "flag", "description": "A flag."}


def test_a_false_default_is_rendered_not_dropped() -> None:
    option = ConfigOptionAsset(key="flag", type="boolean", title="Flag", description="d", default=False)
    bundle = AssetBundle(metadata=BundleMetadata(name="demo", version="1", description=""), config_options=(option,))
    entry = json.loads(ClaudeEmitter().emit(bundle)[".claude-plugin/plugin.json"])["userConfig"]["flag"]
    assert entry["default"] is False


def test_no_userconfig_key_without_options(bundle: AssetBundle) -> None:
    plugin = json.loads(ClaudeEmitter().emit(_bare(bundle))[".claude-plugin/plugin.json"])
    assert set(plugin) == {"name", "version", "description"}


def test_nothing_substitutes_user_config_anywhere_else(bundle: AssetBundle) -> None:
    files = ClaudeEmitter().emit(bundle)
    for path, content in files.items():
        if path == ".claude-plugin/plugin.json":
            continue
        assert "${user_config" not in content, path
    assert "${user_config" not in files[".claude-plugin/plugin.json"]
    assert json.loads(files[".mcp.json"])["mcpServers"]["demo"]["env"] == {}


def test_emitting_is_deterministic(bundle: AssetBundle) -> None:
    assert ClaudeEmitter().emit(bundle) == ClaudeEmitter().emit(bundle)


def test_the_rest_of_the_claude_output_is_unchanged_by_the_options(bundle: AssetBundle) -> None:
    with_options = ClaudeEmitter().emit(bundle)
    without = ClaudeEmitter().emit(_bare(bundle))
    changed = {p for p in with_options if with_options[p] != without.get(p)}
    assert changed == {".claude-plugin/plugin.json", ".claude-plugin/cisternal-provenance.json"}


@pytest.mark.parametrize(
    "emitter",
    [CursorEmitter, CopilotEmitter, AntigravityEmitter, OpenCodeEmitter, PiEmitter, JCodeEmitter],
)
def test_other_surfaces_ignore_the_options(emitter, bundle: AssetBundle) -> None:
    """A placeholder or option must never reach a surface that cannot substitute it."""
    assert emitter().emit(bundle) == emitter().emit(_bare(bundle))


@pytest.mark.parametrize(
    "emitter",
    [CursorEmitter, CopilotEmitter, AntigravityEmitter, OpenCodeEmitter, PiEmitter, JCodeEmitter],
)
def test_other_surfaces_render_no_variables_or_placeholders(emitter, bundle: AssetBundle) -> None:
    """Spec 261116_cross-surface-plugin-config FR-2: no `variables` key and no `${` that the bare bundle lacks."""
    files = emitter().emit(bundle)
    bare = emitter().emit(_bare(bundle))
    for path, content in files.items():
        assert content.count("${") == bare.get(path, "").count("${"), path
        assert '"variables"' not in content, path


@pytest.mark.skipif(shutil.which("agy") is None, reason="the agy binary is not installed")
def test_other_surfaces_antigravity_plugin_installs_enabled(bundle: AssetBundle, tmp_path: Path) -> None:
    """A declared Antigravity `variables` entry would install the plugin disabled (probe P1); the export must not."""
    plugin = tmp_path / "plugin"
    for path, content in AntigravityEmitter().emit(bundle).items():
        target = plugin / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
    }
    installed = subprocess.run(
        ["agy", "plugin", "install", str(plugin)], capture_output=True, text=True, timeout=120, check=False, env=env
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "disabled until its MCP servers are configured" not in installed.stdout + installed.stderr
    listed = subprocess.run(
        ["agy", "plugin", "list", "--json"], capture_output=True, text=True, timeout=120, check=False, env=env
    )
    plugins = json.loads(listed.stdout)
    assert plugins and all(p["enabled"] is True for p in plugins), listed.stdout


def test_rust_parity_output_is_unchanged(bundle: AssetBundle) -> None:
    assert ClaudeEmitter(rust_parity=True).emit(bundle) == ClaudeEmitter(rust_parity=True).emit(_bare(bundle))


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude binary is not installed")
def test_the_rendered_plugin_validates_under_claude_plugin_validate(bundle: AssetBundle, tmp_path: Path) -> None:
    for path, content in ClaudeEmitter().emit(bundle).items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    proc = subprocess.run(
        ["claude", "plugin", "validate", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    report = json.loads(proc.stdout)
    assert report["success"] is True, proc.stdout
    assert report["manifest"]["errors"] == []
