"""Tests for GitHub-installable repo bundles and `launch = "uvx"` MCP servers.

Covers `cisternal.assets.launch`, `cisternal.plugin.repo`, and the
`plugin repo-bundle` / `plugin index-entry` sub-app commands.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "manifest_minimal"
PLUGIN = "fixture-plugin"


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    from cisternal.registration.registry import clear_registry

    clear_registry()


def _checkout(tmp_path: Path, *, mcp: str = "") -> Path:
    """A repo with the fixture manifest; *mcp* is appended as a [plugin.mcp] table."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT, repo)
    if mcp:
        manifest = repo / ".praxia" / "manifest.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n" + mcp, encoding="utf-8")
    return repo


def _run(app, args: list[str]) -> int:
    try:
        app(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else int(bool(exc.code))
    return 0


def _app():
    from cisternal.plugin import PluginSpec, plugin_app

    return plugin_app(PluginSpec(name=PLUGIN, package="cisternal", version="2.3.4", cli="fx"))


# ---------------------------------------------------------------------------
# launch = "uvx"
# ---------------------------------------------------------------------------


def _bundle(servers):
    from cisternal.assets.bundle import AssetBundle, BundleMetadata

    return AssetBundle(metadata=BundleMetadata(name="tool", version="1.2.0a3"), mcp_servers=servers)


def test_uvx_launch_pins_the_release_and_leaves_path_servers_alone() -> None:
    from cisternal.assets.bundle import McpAsset
    from cisternal.assets.launch import resolve_mcp_launch

    bundle = _bundle((
        McpAsset(name="a", command=("tool-mcp",), launch="uvx"),
        McpAsset(name="b", command=("srv", "--stdio"), launch="uvx", uvx_from="tool[mcp]=={version}"),
        McpAsset(name="c", command=("on-path",)),
    ))
    out = resolve_mcp_launch(bundle)
    a, b, c = out.mcp_servers
    assert a.command == ("uvx", "--from", "tool==1.2.0a3", "tool-mcp")
    assert b.command == ("uvx", "--from", "tool[mcp]==1.2.0a3", "srv", "--stdio")
    assert c == bundle.mcp_servers[2]
    assert all(s.launch == "path" for s in out.mcp_servers)
    assert resolve_mcp_launch(out) == out  # idempotent


def test_uvx_spec_drops_the_local_digest_and_fills_git_templates() -> None:
    from cisternal.assets.launch import uvx_spec

    assert uvx_spec("", name="tool", version="1.0.0+ab12cd34") == "tool==1.0.0"
    assert (
        uvx_spec("git+https://github.com/o/r@v{version}", name="tool", version="1.0.0+ab")
        == "git+https://github.com/o/r@v1.0.0"
    )


def test_manifest_uvx_launch_reaches_the_emitted_mcp_json(tmp_path: Path) -> None:
    from cisternal.export.claude import ClaudeEmitter
    from cisternal.plugin import load_bundle, PluginSpec

    repo = _checkout(tmp_path, mcp='[plugin.mcp]\ncommand = ["fx-mcp"]\nlaunch = "uvx"\n')
    spec = PluginSpec(name=PLUGIN, package="cisternal", version="2.3.4")
    bundle, _ = load_bundle(spec, manifest=repo / ".praxia" / "manifest.toml")
    mcp = json.loads(ClaudeEmitter().emit(bundle)[".mcp.json"])["mcpServers"][PLUGIN]
    assert mcp["command"] == "uvx"
    assert mcp["args"] == ["--from", f"{PLUGIN}==2.3.4", "fx-mcp"]


def test_invalid_launch_is_a_load_warning(tmp_path: Path) -> None:
    from cisternal.assets.manifest import ManifestAssetSource

    repo = _checkout(tmp_path, mcp='[plugin.mcp]\ncommand = ["x"]\nlaunch = "docker"\n')
    report = ManifestAssetSource(repo / ".praxia" / "manifest.toml").load()
    assert any("launch" in w for w in report.warnings)


def test_snapshot_keeps_the_unresolved_launch(tmp_path: Path) -> None:
    from cisternal.assets.manifest import ManifestAssetSource
    from cisternal.assets.snapshot import dumps_snapshot, loads_snapshot

    repo = _checkout(tmp_path, mcp='[plugin.mcp]\ncommand = ["x"]\nlaunch = "uvx"\nuvx_from = "t=={version}"\n')
    bundle = ManifestAssetSource(repo / ".praxia" / "manifest.toml").load().bundle
    (srv,) = loads_snapshot(dumps_snapshot(bundle)).mcp_servers
    assert (srv.launch, srv.uvx_from, srv.command) == ("uvx", "t=={version}", ("x",))


def test_snapshots_written_before_launch_existed_stay_current(tmp_path: Path) -> None:
    """A default-launch server serializes exactly as 0.1.1a13 did (no new keys)."""
    from cisternal.assets.manifest import ManifestAssetSource
    from cisternal.assets.snapshot import dumps_snapshot

    repo = _checkout(tmp_path, mcp='[plugin.mcp]\ncommand = ["x"]\n')
    text = dumps_snapshot(ManifestAssetSource(repo / ".praxia" / "manifest.toml").load().bundle)
    (srv,) = json.loads(text)["bundle"]["mcp_servers"]
    assert set(srv) == {"name", "command", "env"}


# ---------------------------------------------------------------------------
# plugin repo-bundle / index-entry
# ---------------------------------------------------------------------------


def test_repo_bundle_writes_marketplace_and_subdir_bundle(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    assert _run(_app(), ["repo-bundle", "--manifest", str(repo / ".praxia" / "manifest.toml")]) == 0

    doc = json.loads((repo / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert doc["name"] == PLUGIN
    assert doc["plugins"] == [{"name": PLUGIN, "source": "./plugin", "description": doc["description"]}]
    plugin_json = json.loads((repo / "plugin" / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert plugin_json["version"].startswith("2.3.4+")
    assert (repo / "plugin" / "skills" / "demo-skill" / "SKILL.md").is_file()
    assert not (repo / "plugin" / ".claude-plugin" / "marketplace.json").exists()
    assert not (repo / ".mcp.json").exists()  # never at the repo root


def test_repo_bundle_check_catches_stale_missing_and_extra_files(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    args = ["repo-bundle", "--manifest", str(repo / ".praxia" / "manifest.toml")]
    assert _run(_app(), [*args, "--check"]) == 1  # nothing committed yet
    assert _run(_app(), args) == 0
    assert _run(_app(), [*args, "--check"]) == 0

    stray = repo / "plugin" / "STRAY.md"
    stray.write_text("x", encoding="utf-8")
    assert _run(_app(), [*args, "--check"]) == 1
    assert _run(_app(), args) == 0 and not stray.exists()  # rewrite scrubs it

    skill = repo / "skills" / "demo-skill" / "SKILL.md"  # the *source* skill changes
    skill.write_text(skill.read_text(encoding="utf-8") + "\nnew line\n", encoding="utf-8")
    assert _run(_app(), [*args, "--check"]) == 1


def test_repo_bundle_rejects_escaping_dirs(tmp_path: Path) -> None:
    repo = _checkout(tmp_path)
    for bad in ("..", "../x", ".", "/abs"):
        assert _run(_app(), ["repo-bundle", "--dir", bad, "--manifest", str(repo / ".praxia" / "manifest.toml")]) == 1


def test_index_entry_pins_the_release_tag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _checkout(tmp_path)
    assert _run(_app(), ["index-entry", "--repo", "maraxen/fx", "--manifest", str(repo / ".praxia" / "manifest.toml")]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["source"] == {"source": "git-subdir", "url": "maraxen/fx", "path": "plugin", "ref": "v2.3.4"}


@pytest.mark.skipif(shutil.which("claude") is None, reason="needs the real claude CLI")
def test_real_claude_installs_the_repo_bundle(tmp_path: Path) -> None:
    """End to end against the real CLI, in a throwaway CLAUDE_CONFIG_DIR."""
    import os

    repo = _checkout(tmp_path)
    assert _run(_app(), ["repo-bundle", "--manifest", str(repo / ".praxia" / "manifest.toml")]) == 0
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    for argv in (
        ["claude", "plugin", "validate", str(repo)],
        ["claude", "plugin", "marketplace", "add", str(repo)],
        ["claude", "plugin", "install", f"{PLUGIN}@{PLUGIN}", "--scope", "user"],
    ):
        result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)
        assert result.returncode == 0, (argv, result.stdout, result.stderr)
    listing = subprocess.run(
        ["claude", "plugin", "list", "--json"], capture_output=True, text=True, env=env, timeout=60
    )
    (installed,) = [p for p in json.loads(listing.stdout) if p["id"] == f"{PLUGIN}@{PLUGIN}"]
    assert installed["version"].startswith("2.3.4+")
