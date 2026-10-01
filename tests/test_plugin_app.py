"""Tests for the mountable `<tool> plugin` sub-app (cisternal.plugin).

Fake packages are built under tmp_path to exercise both bundle sources a
real tool hits: a source checkout (editable install) and a packaged
snapshot (wheel install). A fake `claude` script records every invocation,
so no real Claude Code state is touched.
"""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "manifest_minimal"
FIXTURE_MANIFEST = FIXTURE_ROOT / ".praxia" / "manifest.toml"
PLUGIN = "fixture-plugin"  # [plugin].name in the fixture manifest
REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No real marketplace config, no legacy dir, a clean registry."""
    from cisternal.registration.registry import clear_registry

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CISTERNAL_PLUGIN_MARKETPLACE", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.chdir(tmp_path)
    clear_registry()


def _make_checkout(tmp_path: Path, pkg: str) -> Path:
    """repo/.praxia/manifest.toml + repo/src/<pkg>/ -- an editable-install layout."""
    repo = tmp_path / f"repo_{pkg}"
    shutil.copytree(FIXTURE_ROOT, repo)
    (repo / "src" / pkg).mkdir(parents=True)
    (repo / "src" / pkg / "__init__.py").write_text("", encoding="utf-8")
    return repo / "src"


def _make_wheel(tmp_path: Path, pkg: str) -> Path:
    """site-packages/<pkg>/agent_plugin.json -- a wheel-install layout."""
    from cisternal.assets.manifest import ManifestAssetSource
    from cisternal.assets.snapshot import dumps_snapshot

    site = tmp_path / "venv" / "lib" / "site-packages"
    (site / pkg).mkdir(parents=True)
    (site / pkg / "__init__.py").write_text("", encoding="utf-8")
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    (site / pkg / "agent_plugin.json").write_text(dumps_snapshot(bundle), encoding="utf-8")
    return site


def _import_from(path: Path, pkg: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(path))
    monkeypatch.delitem(sys.modules, pkg, raising=False)
    importlib.invalidate_caches()


def _spec(pkg: str):
    from cisternal.plugin import PluginSpec

    return PluginSpec(name=PLUGIN, package=pkg, version="1.0.0", cli="fx")


def _run(app, args: list[str], *, exit_code: int = 0) -> None:
    try:
        app(args)
    except SystemExit as exc:
        assert (exc.code or 0) == exit_code, f"exit {exc.code}, expected {exit_code}"
    else:
        assert exit_code == 0


def _fake_claude(
    tmp_path: Path,
    *,
    installed: dict[str, tuple[str, str]] | list[tuple[str, str, str]] | None = None,
    marketplaces: dict[str, str] | None = None,
    remote_marketplaces: dict[str, str] | None = None,
    fail_update_scopes: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    """installed: {id: (version, scope)} or [(id, version, scope)];
    marketplaces: {name: directory path}; remote_marketplaces: {name: repo}."""
    if isinstance(installed, dict):
        installed = [(i, v, sc) for i, (v, sc) in installed.items()]
    plugins = [{"id": i, "version": v, "scope": sc} for i, v, sc in (installed or [])]
    mkts = [{"name": n, "source": "directory", "path": p} for n, p in (marketplaces or {}).items()]
    mkts += [{"name": n, "source": "github", "repo": r} for n, r in (remote_marketplaces or {}).items()]
    log = tmp_path / "claude_calls.jsonl"
    script = tmp_path / "fake_claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:4] == ['plugin', 'marketplace', 'list']:\n"
        f"    print(json.dumps({mkts!r}))\n"
        "elif sys.argv[1:3] == ['plugin', 'list']:\n"
        f"    print(json.dumps({plugins!r}))\n"
        "elif sys.argv[1:3] == ['plugin', 'update'] and '--scope' in sys.argv:\n"
        f"    if sys.argv[sys.argv.index('--scope') + 1] in {list(fail_update_scopes)!r}:\n"
        "        sys.exit(1)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, log


def _calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _mutating(log: Path) -> list[list[str]]:
    return [c for c in _calls(log) if "list" not in c]


# ---------------------------------------------------------------------------
# snapshot round trip
# ---------------------------------------------------------------------------


def test_snapshot_round_trips_and_rejects_unknown_schema() -> None:
    from cisternal.assets.manifest import ManifestAssetSource
    from cisternal.assets.snapshot import dumps_snapshot, loads_snapshot

    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    assert bundle.skills and bundle.agents  # the fixture is not vacuous
    text = dumps_snapshot(bundle)
    assert loads_snapshot(text) == bundle
    assert dumps_snapshot(loads_snapshot(text)) == text

    doc = json.loads(text)
    doc["schema"] = 999
    with pytest.raises(ValueError, match="schema"):
        loads_snapshot(json.dumps(doc))
    for broken in ({"schema": 1}, {"schema": 1, "bundle": []}, {"schema": 1, "bundle": {"skills": [1]}}):
        with pytest.raises(ValueError, match="malformed"):
            loads_snapshot(json.dumps(broken))


def test_snapshot_check_detects_drift(tmp_path: Path) -> None:
    from cisternal.cli import app

    out = tmp_path / "pkg" / "agent_plugin.json"
    base = ["assets", "snapshot", "--manifest", str(FIXTURE_MANIFEST), "--out", str(out)]
    _run(app, [*base, "--check"], exit_code=1)  # missing
    _run(app, base)
    _run(app, [*base, "--check"])
    out.write_text(out.read_text(encoding="utf-8").replace("demo-skill", "renamed"), encoding="utf-8")
    _run(app, [*base, "--check"], exit_code=1)  # stale


def test_cisternal_packaged_snapshot_matches_its_manifest() -> None:
    """The shipped src/cisternal/agent_plugin.json must track .praxia/manifest.toml."""
    from cisternal.cli import app

    _run(
        app,
        [
            "assets", "snapshot", "--check",
            "--manifest", str(REPO_ROOT / ".praxia" / "manifest.toml"),
            "--out", str(REPO_ROOT / "src" / "cisternal" / "agent_plugin.json"),
        ],
    )


# ---------------------------------------------------------------------------
# locating the bundle
# ---------------------------------------------------------------------------


def test_checkout_manifest_wins_in_a_source_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cisternal.plugin import locate_bundle

    _import_from(_make_checkout(tmp_path, "fx_checkout"), "fx_checkout", monkeypatch)
    source = locate_bundle(_spec("fx_checkout"))
    assert source.kind == "checkout"
    assert source.path == tmp_path / "repo_fx_checkout" / ".praxia" / "manifest.toml"


def test_wheel_install_uses_packaged_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cisternal.plugin import locate_bundle

    site = _make_wheel(tmp_path, "fx_wheel")
    # A manifest above site-packages (e.g. the project owning the venv) must be ignored.
    shutil.copytree(FIXTURE_ROOT / ".praxia", tmp_path / "venv" / ".praxia")
    _import_from(site, "fx_wheel", monkeypatch)
    source = locate_bundle(_spec("fx_wheel"))
    assert source.kind == "snapshot"
    assert source.record == {"package": "fx_wheel", "snapshot": "agent_plugin.json", "registry": "default"}


def test_manifest_for_another_plugin_is_not_picked_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cisternal.plugin import PluginError, PluginSpec, locate_bundle

    _import_from(_make_checkout(tmp_path, "fx_other"), "fx_other", monkeypatch)
    with pytest.raises(PluginError, match="no plugin bundle"):
        locate_bundle(PluginSpec(name="some-other-plugin", package="fx_other"))


def test_checkout_and_snapshot_emit_identical_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wheel path must install exactly what the source checkout would."""
    from cisternal.export.claude import ClaudeEmitter
    from cisternal.plugin import load_bundle

    _import_from(_make_checkout(tmp_path, "fx_a"), "fx_a", monkeypatch)
    _import_from(_make_wheel(tmp_path, "fx_b"), "fx_b", monkeypatch)
    from_checkout, s1 = load_bundle(_spec("fx_a"))
    from_wheel, s2 = load_bundle(_spec("fx_b"))
    assert (s1.kind, s2.kind) == ("checkout", "snapshot")
    assert ClaudeEmitter().emit(from_checkout) == ClaudeEmitter().emit(from_wheel)


# ---------------------------------------------------------------------------
# marketplace location
# ---------------------------------------------------------------------------


def test_marketplace_resolution_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cisternal.plugin import marketplace_root_source, resolve_marketplace_root

    assert marketplace_root_source() == (None, "unconfigured")

    # The pre-resolver location is never used implicitly, only suggested.
    legacy = tmp_path / "home" / ".cisternal" / "claude-plugin-marketplace"
    legacy.mkdir(parents=True)
    assert marketplace_root_source() == (None, "unconfigured")
    with pytest.raises(ValueError, match=r'plugin_marketplace = ".*claude-plugin-marketplace"'):
        resolve_marketplace_root()

    config = tmp_path / "xdg" / "cisternal" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('plugin_marketplace = "mkt-user"\n', encoding="utf-8")
    assert marketplace_root_source()[0] == (config.parent / "mkt-user").resolve()

    (tmp_path / "pyproject.toml").write_text(
        '[tool.cisternal]\nplugin_marketplace = "mkt-proj"\n', encoding="utf-8"
    )
    nested = tmp_path / "sub" / "dir"
    nested.mkdir(parents=True)
    root, layer = marketplace_root_source(start=nested)
    assert root == (tmp_path / "mkt-proj").resolve() and "pyproject.toml" in layer

    monkeypatch.setenv("CISTERNAL_PLUGIN_MARKETPLACE", str(tmp_path / "mkt-env"))
    assert marketplace_root_source() == ((tmp_path / "mkt-env").resolve(), "$CISTERNAL_PLUGIN_MARKETPLACE")
    assert marketplace_root_source(tmp_path / "x")[1] == "argument"

    monkeypatch.setenv("CISTERNAL_PLUGIN_MARKETPLACE", "none")
    assert marketplace_root_source()[0] is None


def test_malformed_marketplace_config_fails_loudly(tmp_path: Path) -> None:
    from cisternal.plugin import marketplace_root_source

    config = tmp_path / "xdg" / "cisternal" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("plugin_marketplace = [", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid TOML"):
        marketplace_root_source()
    config.write_text("plugin_marketplace = 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty string"):
        marketplace_root_source()


@pytest.mark.parametrize(
    "body", ['[tool]\ncisternal = "~/mkt"\n', "[tool]\ncisternal = 3\n", "tool = 1\n"]
)
def test_non_table_tool_cisternal_is_an_error_not_a_skip(tmp_path: Path, body: str) -> None:
    from cisternal.plugin import marketplace_root_source

    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="must be a table"):
        marketplace_root_source()


def test_info_reports_a_malformed_config_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cisternal.plugin import plugin_app

    _import_from(_make_wheel(tmp_path, "fx_info"), "fx_info", monkeypatch)
    (tmp_path / "pyproject.toml").write_text("[tool\n", encoding="utf-8")
    _run(plugin_app(_spec("fx_info")), ["info"])
    assert "invalid TOML" in capsys.readouterr().out


def test_install_without_any_marketplace_config_explains_how(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from cisternal.plugin import plugin_app

    _import_from(_make_wheel(tmp_path, "fx_nomkt"), "fx_nomkt", monkeypatch)
    claude, log = _fake_claude(tmp_path)
    _run(plugin_app(_spec("fx_nomkt")), ["install", "claude", "--claude-bin", str(claude)], exit_code=1)
    assert "CISTERNAL_PLUGIN_MARKETPLACE" in caplog.text
    assert _calls(log) == []


# ---------------------------------------------------------------------------
# install / update against a fake claude
# ---------------------------------------------------------------------------


@pytest.fixture
def wheel_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from cisternal.plugin import plugin_app

    _import_from(_make_wheel(tmp_path, "fx_tool"), "fx_tool", monkeypatch)
    return plugin_app(_spec("fx_tool"))


def _published_version(marketplace: Path) -> str:
    plugin_json = marketplace / "plugins" / PLUGIN / ".claude-plugin" / "plugin.json"
    return json.loads(plugin_json.read_text(encoding="utf-8"))["version"]


def test_install_from_wheel_registers_marketplace_and_installs(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    claude, log = _fake_claude(tmp_path)
    _run(wheel_app, ["install", "claude", "--marketplace", str(mkt), "--claude-bin", str(claude)])

    assert (mkt / "plugins" / PLUGIN / "skills" / "demo-skill" / "SKILL.md").is_file()
    assert _published_version(mkt).startswith("1.0.0+")  # spec version, not the manifest's
    assert _mutating(log) == [
        ["plugin", "marketplace", "add", str(mkt.resolve())],
        ["plugin", "install", f"{PLUGIN}@cisternal-local", "--scope", "user"],
    ]
    sidecar = json.loads(
        (mkt / "plugins" / PLUGIN / ".claude-plugin" / "cisternal-source.json").read_text("utf-8")
    )
    assert sidecar["update_command"] == "fx plugin update claude"
    assert sidecar["package"] == "fx_tool"


def test_install_when_current_is_a_no_op(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    first, _ = _fake_claude(tmp_path)
    _run(wheel_app, ["install", "--marketplace", str(mkt), "--claude-bin", str(first)])
    version = _published_version(mkt)

    (tmp_path / "claude_calls.jsonl").unlink()
    claude, log = _fake_claude(
        tmp_path,
        installed={f"{PLUGIN}@cisternal-local": (version, "user")},
        marketplaces={"cisternal-local": str(mkt)},
    )
    _run(wheel_app, ["install", "--marketplace", str(mkt), "--claude-bin", str(claude)])
    assert _mutating(log) == []


def test_update_targets_the_installed_scope(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    claude, log = _fake_claude(
        tmp_path,
        installed={f"{PLUGIN}@cisternal-local": ("0.9.0+old", "project")},
        marketplaces={"cisternal-local": str(mkt)},
    )
    _run(wheel_app, ["update", "claude", "--marketplace", str(mkt), "--claude-bin", str(claude)])
    assert _mutating(log) == [
        ["plugin", "marketplace", "update", "cisternal-local"],
        ["plugin", "update", f"{PLUGIN}@cisternal-local", "--scope", "project"],
    ]


def test_update_when_not_installed_fails(tmp_path: Path, wheel_app) -> None:
    claude, log = _fake_claude(tmp_path)
    _run(
        wheel_app,
        ["update", "--marketplace", str(tmp_path / "mkt"), "--claude-bin", str(claude)],
        exit_code=1,
    )
    assert not any(c[:2] == ["plugin", "install"] for c in _calls(log))


def test_same_named_marketplace_elsewhere_is_refused(tmp_path: Path, wheel_app) -> None:
    claude, log = _fake_claude(tmp_path, marketplaces={"cisternal-local": str(tmp_path / "other")})
    _run(
        wheel_app,
        ["install", "--marketplace", str(tmp_path / "mkt"), "--claude-bin", str(claude)],
        exit_code=1,
    )
    assert _mutating(log) == []


def test_dry_run_changes_nothing(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    claude, log = _fake_claude(tmp_path)
    _run(wheel_app, ["install", "--dry-run", "--marketplace", str(mkt), "--claude-bin", str(claude)])
    assert not mkt.exists()
    assert _calls(log) == []


def test_surface_without_installer_points_at_export(
    tmp_path: Path, wheel_app, caplog: pytest.LogCaptureFixture
) -> None:
    _run(wheel_app, ["install", "cursor", "--marketplace", str(tmp_path / "mkt")], exit_code=1)
    assert "plugin export" in caplog.text


def test_export_writes_any_surface(tmp_path: Path, wheel_app) -> None:
    out = tmp_path / "cursor-out"
    _run(wheel_app, ["export", "cursor", "--out", str(out)])
    assert (out / ".cursor-plugin" / "plugin.json").is_file()
    _run(wheel_app, ["export", "nope", "--out", str(out)], exit_code=1)


def test_update_refusal_writes_nothing(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    claude, log = _fake_claude(tmp_path)
    _run(wheel_app, ["update", "--marketplace", str(mkt), "--claude-bin", str(claude)], exit_code=1)
    assert not mkt.exists()
    assert _mutating(log) == []


def test_same_named_remote_marketplace_is_refused(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    claude, log = _fake_claude(tmp_path, remote_marketplaces={"cisternal-local": "someone/plugins"})
    _run(wheel_app, ["install", "--marketplace", str(mkt), "--claude-bin", str(claude)], exit_code=1)
    assert not mkt.exists()  # refused before publishing
    assert _mutating(log) == []


def test_every_stale_scope_is_updated(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    first, _ = _fake_claude(tmp_path)
    _run(wheel_app, ["install", "--marketplace", str(mkt), "--claude-bin", str(first)])
    current = _published_version(mkt)
    (tmp_path / "claude_calls.jsonl").unlink()

    pid = f"{PLUGIN}@cisternal-local"
    claude, log = _fake_claude(
        tmp_path,
        installed=[(pid, current, "project"), (pid, "0.1+old", "user"), (pid, "0.2+old", "local")],
        marketplaces={"cisternal-local": str(mkt)},
    )
    _run(wheel_app, ["install", "--marketplace", str(mkt), "--claude-bin", str(claude)])
    assert _mutating(log) == [
        ["plugin", "marketplace", "update", "cisternal-local"],
        ["plugin", "update", pid, "--scope", "user"],
        ["plugin", "update", pid, "--scope", "local"],
    ]


def test_a_failing_scope_is_reported_without_skipping_the_rest(tmp_path: Path, wheel_app) -> None:
    mkt = tmp_path / "mkt"
    pid = f"{PLUGIN}@cisternal-local"
    claude, log = _fake_claude(
        tmp_path,
        installed=[(pid, "0.1+old", "project"), (pid, "0.1+old", "user")],
        marketplaces={"cisternal-local": str(mkt)},
        fail_update_scopes=("project",),
    )
    _run(wheel_app, ["update", "--marketplace", str(mkt), "--claude-bin", str(claude)], exit_code=1)
    assert ["plugin", "update", pid, "--scope", "user"] in _calls(log)


def test_update_command_without_cli_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from cisternal.plugin import PluginSpec

    spec = PluginSpec(name="x", package="xpkg")
    monkeypatch.setattr(sys, "argv", ["/venv/lib/xpkg/__main__.py", "plugin"])
    assert spec.update_command() == "python -m xpkg plugin update claude"
    monkeypatch.setattr(sys, "argv", ["/venv/bin/xp", "plugin"])
    assert spec.update_command() == "xp plugin update claude"


def test_update_all_defers_to_the_owning_tool(
    tmp_path: Path, wheel_app, capsys: pytest.CaptureFixture[str]
) -> None:
    from cisternal.cli import app

    mkt = tmp_path / "mkt"
    claude, _ = _fake_claude(tmp_path)
    _run(wheel_app, ["install", "--marketplace", str(mkt), "--claude-bin", str(claude)])
    version = _published_version(mkt)
    capsys.readouterr()

    _run(app, ["assets", "update-all", "--marketplace", str(mkt), "--no-refresh"])
    assert "run `fx plugin update claude`" in capsys.readouterr().out
    assert _published_version(mkt) == version  # not rebuilt with the manifest's version


def test_cisternal_mounts_its_own_plugin_app(capsys: pytest.CaptureFixture[str]) -> None:
    from cisternal.cli import app

    _run(app, ["plugin", "info"])
    out = capsys.readouterr().out
    assert "plugin:      cisternal" in out
    assert "bundle:      checkout:" in out
