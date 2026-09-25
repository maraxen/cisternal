"""Tests for publish-shared's Claude Code refresh and `cisternal assets update-all`.

A fake `claude` script records every invocation, so no real Claude Code state
is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / ".praxia" / "manifest.toml"
)


def _invoke_app(args: list[str], *, exit_code: int = 0) -> None:
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code


def _fake_claude(
    tmp_path: Path, *, installed: list[str] | dict[str, str], fail_update: bool = False
) -> tuple[Path, Path]:
    versions = installed if isinstance(installed, dict) else {i: "0" for i in installed}
    log = tmp_path / "claude_calls.jsonl"
    script = tmp_path / "fake_claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['plugin', 'list']:\n"
        f"    print(json.dumps([{{'id': i, 'version': v}} for i, v in {versions!r}.items()]))\n"
        f"elif sys.argv[1:3] == ['plugin', 'update'] and {fail_update!r}:\n"
        "    sys.exit(1)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, log


def _calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _publish(marketplace: Path, claude: Path, *extra: str, exit_code: int = 0) -> None:
    _invoke_app(
        [
            "assets", "publish-shared",
            "--manifest", str(FIXTURE_MANIFEST),
            "--marketplace", str(marketplace),
            "--claude-bin", str(claude),
            *extra,
        ],
        exit_code=exit_code,
    )


def test_publish_records_source_sidecar(tmp_path: Path) -> None:
    claude, _ = _fake_claude(tmp_path, installed=[])
    _publish(tmp_path / "mkt", claude)
    sidecar = tmp_path / "mkt" / "plugins" / "fixture-plugin" / ".claude-plugin" / "cisternal-source.json"
    source = json.loads(sidecar.read_text(encoding="utf-8"))
    assert source["manifest"] == str(FIXTURE_MANIFEST.resolve())
    assert source["registry"] == "default"


def test_refresh_updates_installed_plugin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude, log = _fake_claude(tmp_path, installed=["fixture-plugin@cisternal-local"])
    _publish(tmp_path / "mkt", claude)
    calls = _calls(log)
    assert ["plugin", "marketplace", "update", "cisternal-local"] in calls
    assert ["plugin", "update", "fixture-plugin@cisternal-local"] in calls
    assert "restart Claude Code" in capsys.readouterr().out


def test_refresh_does_not_install_uninstalled_plugin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude, log = _fake_claude(tmp_path, installed=[])
    _publish(tmp_path / "mkt", claude)
    assert not any(c[:2] == ["plugin", "install"] or c[:2] == ["plugin", "update"] for c in _calls(log))
    assert "claude plugin install fixture-plugin@cisternal-local" in capsys.readouterr().out


def _published_version(marketplace: Path) -> str:
    plugin_json = marketplace / "plugins" / "fixture-plugin" / ".claude-plugin" / "plugin.json"
    return json.loads(plugin_json.read_text(encoding="utf-8"))["version"]


def test_up_to_date_install_is_not_updated(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"
    claude, _ = _fake_claude(tmp_path, installed=[])
    _publish(marketplace, claude, "--no-refresh")
    current, log = _fake_claude(
        tmp_path, installed={"fixture-plugin@cisternal-local": _published_version(marketplace)}
    )
    _publish(marketplace, current)
    assert [c[:2] for c in _calls(log)] == [["plugin", "list"]]


def test_stale_install_updated_even_when_marketplace_unchanged(tmp_path: Path) -> None:
    # The bathos case: the marketplace copy was already current, the install was not.
    marketplace = tmp_path / "mkt"
    claude, _ = _fake_claude(tmp_path, installed=[])
    _publish(marketplace, claude, "--no-refresh")
    stale, log = _fake_claude(tmp_path, installed={"fixture-plugin@cisternal-local": "1.2.3+deadbeef"})
    _publish(marketplace, stale)
    assert ["plugin", "update", "fixture-plugin@cisternal-local"] in _calls(log)


def test_no_refresh_never_calls_claude(tmp_path: Path) -> None:
    claude, log = _fake_claude(tmp_path, installed=["fixture-plugin@cisternal-local"])
    _publish(tmp_path / "mkt", claude, "--no-refresh")
    assert _calls(log) == []


def test_missing_claude_binary_prints_manual_steps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _publish(tmp_path / "mkt", tmp_path / "no-such-claude")
    out = capsys.readouterr().out
    assert "/plugin marketplace update cisternal-local" in out
    assert "/plugin update fixture-plugin@cisternal-local" in out


def test_failed_plugin_update_exits_nonzero(tmp_path: Path) -> None:
    claude, _ = _fake_claude(tmp_path, installed=["fixture-plugin@cisternal-local"], fail_update=True)
    _publish(tmp_path / "mkt", claude, exit_code=1)


def test_update_all_republishes_managed_and_reports_unmanaged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    marketplace = tmp_path / "mkt"
    claude, log = _fake_claude(tmp_path, installed=["fixture-plugin@cisternal-local"])
    _publish(marketplace, claude, "--no-refresh")
    (marketplace / "plugins" / "hand-made" / ".claude-plugin").mkdir(parents=True)
    # Simulate a stale publish: an older version on disk.
    plugin_json = marketplace / "plugins" / "fixture-plugin" / ".claude-plugin" / "plugin.json"
    doc = json.loads(plugin_json.read_text(encoding="utf-8"))
    doc["version"] = "1.2.3+00000000"
    plugin_json.write_text(json.dumps(doc), encoding="utf-8")
    capsys.readouterr()

    _invoke_app(["assets", "update-all", "--marketplace", str(marketplace), "--claude-bin", str(claude)])

    out = capsys.readouterr().out
    assert "fixture-plugin: 1.2.3+00000000 -> 1.2.3+" in out
    assert "hand-made: unmanaged" in out
    assert ["plugin", "update", "fixture-plugin@cisternal-local"] in _calls(log)


def test_update_all_dry_run_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    marketplace = tmp_path / "mkt"
    claude, log = _fake_claude(tmp_path, installed=[])
    _publish(marketplace, claude, "--no-refresh")
    before = (marketplace / "plugins" / "fixture-plugin" / ".claude-plugin" / "plugin.json").read_text()
    capsys.readouterr()

    _invoke_app(["assets", "update-all", "--marketplace", str(marketplace), "--claude-bin", str(claude), "--dry-run"])

    assert "would republish fixture-plugin" in capsys.readouterr().out
    assert (marketplace / "plugins" / "fixture-plugin" / ".claude-plugin" / "plugin.json").read_text() == before
    assert _calls(log) == []


def test_update_all_reports_missing_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    marketplace = tmp_path / "mkt"
    sidecar_dir = marketplace / "plugins" / "gone" / ".claude-plugin"
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "cisternal-source.json").write_text(
        json.dumps({"manifest": str(tmp_path / "nope.toml"), "registry": "default"}), encoding="utf-8"
    )
    _invoke_app(["assets", "update-all", "--marketplace", str(marketplace), "--no-refresh"], exit_code=1)
    assert "FAILED gone: manifest not found" in capsys.readouterr().out


def _shadow_fixture(claude_home: Path) -> tuple[Path, Path, Path]:
    """Raw ~/.claude copies of the fixture plugin's skill + agent, plus an unrelated skill."""
    skill = claude_home / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo-skill\n---\nraw copy\n", encoding="utf-8")
    agent = claude_home / "agents" / "fixture-plugin-recon.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("raw agent copy\n", encoding="utf-8")
    unrelated = claude_home / "skills" / "my-own-skill"
    unrelated.mkdir()
    (unrelated / "SKILL.md").write_text("mine\n", encoding="utf-8")
    return skill, agent, unrelated


def test_publish_reports_shadowing_copies_without_touching_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    claude_home = tmp_path / "claude_home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    skill, agent, unrelated = _shadow_fixture(claude_home)
    claude, _ = _fake_claude(tmp_path, installed=[])
    _publish(tmp_path / "mkt", claude)
    out = capsys.readouterr().out
    assert f"shadowed: {skill}" in out
    assert f"shadowed: {agent}" in out
    assert "my-own-skill" not in out
    assert skill.exists() and agent.exists() and unrelated.exists()


def test_publish_prune_shadowed_moves_copies_to_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_home = tmp_path / "claude_home"
    backup_root = tmp_path / "shadow_backup"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    monkeypatch.setenv("CISTERNAL_SHADOW_BACKUP_DIR", str(backup_root))
    skill, agent, unrelated = _shadow_fixture(claude_home)
    claude, _ = _fake_claude(tmp_path, installed=[])
    _publish(tmp_path / "mkt", claude, "--prune-shadowed")
    assert not skill.exists() and not agent.exists()
    assert unrelated.exists()
    moved = sorted(p.relative_to(backup_root).as_posix() for p in backup_root.rglob("*") if p.is_file())
    assert any(m.endswith("skills/demo-skill/SKILL.md") for m in moved)
    assert any(m.endswith("agents/fixture-plugin-recon.md") for m in moved)


def test_update_all_prunes_shadowed_for_every_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_home = tmp_path / "claude_home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    monkeypatch.setenv("CISTERNAL_SHADOW_BACKUP_DIR", str(tmp_path / "shadow_backup"))
    claude, _ = _fake_claude(tmp_path, installed=[])
    mkt = tmp_path / "mkt"
    _publish(mkt, claude, "--no-refresh")
    skill, agent, unrelated = _shadow_fixture(claude_home)
    _invoke_app(
        ["assets", "update-all", "--marketplace", str(mkt), "--claude-bin", str(claude),
         "--prune-shadowed"]
    )
    assert not skill.exists() and not agent.exists() and unrelated.exists()
