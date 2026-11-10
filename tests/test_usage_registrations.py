"""Tests for active server registrations scanner and cache manager."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from cisternal.usage.registrations import (
    ActiveRegistrations,
    scan_active_registrations,
)


class TestRegistrationsHostSafety:
    """Verify host safety invariants: read-only, no config mutation, no claude CLI spawning."""

    def test_no_config_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scanner must use marketplace_root_source() and never create ~/.config/cisternal/config.toml."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        # Run scanner with no marketplace configured
        registrations = scan_active_registrations(
            sessions_dir=tmp_path / "sessions",
            claude_dir=tmp_path / "claude",
        )
        assert isinstance(registrations, ActiveRegistrations)

        # Host config dir must not have been created
        config_file = fake_home / ".config" / "cisternal" / "config.toml"
        assert not config_file.exists()

    def test_never_spawns_claude(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scanner must strictly read files and never invoke the `claude` subprocess."""

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if cmd and ("claude" in str(cmd)):
                pytest.fail(
                    "Host safety violation: attempted to spawn claude CLI subprocess!"
                )
            return subprocess.CompletedProcess(args=args, returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(subprocess, "Popen", fake_run)

        registrations = scan_active_registrations(
            sessions_dir=tmp_path / "sessions",
            claude_dir=tmp_path / "claude",
        )
        assert isinstance(registrations, ActiveRegistrations)


class TestRegistrationsScanning:
    """Test server discovery, prefix expansion, and atomic caching."""

    def test_wire_prefix_expansion(self, tmp_path: Path) -> None:
        """Plugin servers get mcp__plugin_<p>_<s>__ prefix; standalone servers get mcp__<s>__."""
        claude_dir = tmp_path / "claude"
        claude_dir.mkdir()
        settings_file = claude_dir / "settings.json"
        settings_file.write_text(
            json.dumps(
                {
                    "enabledPlugins": {"bathos": True},
                    "mcpServers": {
                        "standalone_server": {"command": "standalone"},
                    },
                }
            ),
            encoding="utf-8",
        )

        m_root = tmp_path / "marketplace"
        bathos_plugin = m_root / "plugins" / "bathos"
        bathos_plugin.mkdir(parents=True)
        (bathos_plugin / ".claude-plugin").mkdir()
        (bathos_plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"mcpServers": {"bathos": {}}}),
            encoding="utf-8",
        )

        manifest_file = tmp_path / "manifest.toml"
        manifest_file.write_text(
            """
[plugin]
name = "cisternal"
version = "0.1.0"

[families]
sql = ["bathos/run_sql", "standalone_server/query"]
""",
            encoding="utf-8",
        )

        sessions_dir = tmp_path / "sessions"
        reg = scan_active_registrations(
            sessions_dir=sessions_dir,
            claude_dir=claude_dir,
            marketplace_dir=m_root,
            manifest_path=manifest_file,
            force=True,
        )

        assert "bathos" in reg.servers
        assert "standalone_server" in reg.servers

        # Wire name expansion
        assert reg.tools["bathos/run_sql"] == "mcp__plugin_bathos_bathos__run_sql"
        assert reg.tools["standalone_server/query"] == "mcp__standalone_server__query"

    def test_atomic_write_and_caching(self, tmp_path: Path) -> None:
        """Cache file is written atomically and reused when configuration is unchanged."""
        sessions_dir = tmp_path / "sessions"
        claude_dir = tmp_path / "claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(
            json.dumps({"mcpServers": {"praxia": {}}}),
            encoding="utf-8",
        )

        # Initial scan writes cache
        reg1 = scan_active_registrations(
            sessions_dir=sessions_dir, claude_dir=claude_dir
        )
        cache_file = sessions_dir / "active_servers.json"
        assert cache_file.is_file()
        assert "praxia" in reg1.servers

        # Second scan uses cache
        reg2 = scan_active_registrations(
            sessions_dir=sessions_dir, claude_dir=claude_dir
        )
        assert reg2.servers == reg1.servers

    def test_readonly_sessions_dir_fail_open(self, tmp_path: Path) -> None:
        """Scanner fails open without raising OSError when sessions_dir is read-only."""
        ro_parent = tmp_path / "readonly_parent"
        ro_parent.mkdir()
        ro_parent.chmod(0o500)
        sessions_dir = ro_parent / "sessions"
        claude_dir = tmp_path / "claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(
            json.dumps({"mcpServers": {"praxia": {}}}),
            encoding="utf-8",
        )
        try:
            reg = scan_active_registrations(
                sessions_dir=sessions_dir, claude_dir=claude_dir
            )
            assert "praxia" in reg.servers
        finally:
            ro_parent.chmod(0o700)

    def test_default_locate_bundle_and_sidecar_merge(self, tmp_path: Path) -> None:
        """Scanner loads cisternal bundle via locate_bundle when manifest_path is None and merges sidecar families/verbs."""
        claude_dir = tmp_path / "claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"bathos": True, "custom_ext": True}}),
            encoding="utf-8",
        )

        m_root = tmp_path / "marketplace"
        for p in ("bathos", "custom_ext"):
            p_dir = m_root / "plugins" / p / ".claude-plugin"
            p_dir.mkdir(parents=True)
            (p_dir / "plugin.json").write_text(
                json.dumps({"mcpServers": {p: {}}}),
                encoding="utf-8",
            )

        # Write cisternal-source.json sidecar with custom families & verbs for custom_ext
        (m_root / "plugins" / "custom_ext" / ".claude-plugin" / "cisternal-source.json").write_text(
            json.dumps(
                {
                    "families": {"custom_fam": ["custom_ext/do_work"]},
                    "verbs": {
                        "custom_ext": {
                            "binary": "cext",
                            "subcommands": {"work": "custom_ext/do_work"},
                            "tool_family": "custom_fam",
                            "exclude": [],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        sessions_dir = tmp_path / "sessions"
        reg = scan_active_registrations(
            sessions_dir=sessions_dir,
            claude_dir=claude_dir,
            marketplace_dir=m_root,
            manifest_path=None,
            force=True,
        )
        # From cisternal's own bundle via locate_bundle (no manifest_path supplied):
        assert "bathos_query" in reg.families
        assert reg.tools.get("bathos/run_sql") == "mcp__plugin_bathos_bathos__run_sql"
        # From installed plugin's cisternal-source.json sidecar:
        assert "custom_fam" in reg.families
        assert reg.tools.get("custom_ext/do_work") == "mcp__plugin_custom_ext_custom_ext__do_work"
        assert "custom_ext" in reg.verbs

