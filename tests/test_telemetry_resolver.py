"""Telemetry resolver (spec 261116_telemetry-config-layers, FR-1 to FR-3 and the FR-7 writer).

Selectors used by the spec's acceptance lines: ``layers``, ``env``, ``files_and_settings``.
Every test passes ``environ``, ``repo_root``, ``user_config_file`` and ``config_dir`` explicitly, so none
reads the real environment, the real ``~/.claude`` or the working directory's ``pyproject.toml``.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cisternal import telemetry_setting as ts
from cisternal.telemetry_setting import (
    Registration,
    TelemetrySettingError,
    discover_registration,
    set_machine_value,
    set_telemetry_setting,
    telemetry_setting,
)

FIXTURE = Path(__file__).parent / "fixtures" / "claude_settings_install_probe.json"

REG = {
    "plugin": "maraxiom",
    "spans_option": "telemetry_spans",
    "shadow_option": "telemetry_shadow",
    "defaults": {"spans": False, "shadow": True},
}


@pytest.fixture(autouse=True)
def _fresh_caches() -> None:
    ts._NOTICED.clear()
    ts._SETTINGS_CACHE.clear()


class Env:
    """An isolated world: tmp repo root, machine file, Claude config dir and environment mapping."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.config_dir = tmp_path / "claude"
        self.config_dir.mkdir()
        self.machine = tmp_path / "xdg" / "cisternal" / "config.toml"
        self.environ: dict[str, str] = {}

    def pyproject(self, body: str) -> None:
        (self.root / "pyproject.toml").write_text(body, encoding="utf-8")

    def machine_file(self, body: str) -> None:
        self.machine.parent.mkdir(parents=True, exist_ok=True)
        self.machine.write_text(body, encoding="utf-8")

    def settings(self, data: object, *, raw: str | None = None) -> None:
        text = raw if raw is not None else json.dumps(data)
        (self.config_dir / "settings.json").write_text(text, encoding="utf-8")

    def plugin_option(self, option: str, value: object, *, plugin: str = "maraxiom@cisternal-local") -> None:
        self.settings(
            {
                "enabledPlugins": {plugin: True},
                "pluginConfigs": {plugin: {"options": {option: value}}},
            }
        )

    def get(self, behaviour: str, *, consumer: str = "maraxiom", registration: object = REG, **kw: object):
        return telemetry_setting(
            consumer,
            behaviour,
            registration=registration,  # type: ignore[arg-type]
            config_dir=self.config_dir,
            repo_root=self.root,
            user_config_file=self.machine,
            environ=self.environ,
            **kw,  # type: ignore[arg-type]
        )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------


def test_layers_unregistered_consumer_is_off(env: Env) -> None:
    d = env.get("spans", consumer="other", registration=None)
    assert (d.enabled, d.layer, d.registered) == (False, "off (no registered default)", False)


def test_layers_registered_default_decides_when_nothing_else_speaks(env: Env) -> None:
    spans, shadow = env.get("spans"), env.get("shadow")
    assert (spans.enabled, spans.layer) == (False, "registered default")
    assert (shadow.enabled, shadow.layer) == (True, "registered default")


def test_layers_machine_file_beats_registered_default(env: Env) -> None:
    env.machine_file("[telemetry]\nspans = true\nshadow = false\n")
    spans, shadow = env.get("spans"), env.get("shadow")
    assert (spans.enabled, spans.layer, spans.source) == (True, "machine file [telemetry]", env.machine)
    assert (shadow.enabled, shadow.layer) == (False, "machine file [telemetry]")


def test_layers_saved_plugin_option_beats_machine_file(env: Env) -> None:
    env.machine_file("[telemetry.maraxiom]\nshadow = true\n")
    env.plugin_option("telemetry_shadow", "off")
    d = env.get("shadow")
    assert (d.enabled, d.layer, d.source) == (False, "saved plugin option", env.config_dir / "settings.json")


def test_layers_pyproject_beats_saved_plugin_option(env: Env) -> None:
    env.plugin_option("telemetry_shadow", "off")
    env.pyproject("[tool.cisternal.telemetry]\nshadow = true\n")
    d = env.get("shadow")
    assert (d.enabled, d.layer) == (True, "pyproject.toml [tool.cisternal.telemetry]")


def test_layers_whole_consumer_variable_beats_pyproject(env: Env) -> None:
    env.pyproject("[tool.cisternal.telemetry]\nspans = false\n")
    env.environ["CISTERNAL_TELEMETRY"] = "maraxiom"
    d = env.get("spans")
    assert (d.enabled, d.layer) == (True, "environment variable CISTERNAL_TELEMETRY")


def test_layers_behaviour_variable_beats_whole_consumer_variable(env: Env) -> None:
    env.environ["CISTERNAL_TELEMETRY"] = "all"
    env.environ["CISTERNAL_TELEMETRY_SPANS"] = "off"
    d = env.get("spans")
    assert (d.enabled, d.layer) == (False, "environment variable CISTERNAL_TELEMETRY_SPANS")


def test_layers_explicit_argument_beats_everything(env: Env) -> None:
    env.environ["CISTERNAL_TELEMETRY_SPANS"] = "off"
    d = env.get("spans", explicit=True)
    assert (d.enabled, d.layer) == (True, "explicit argument")


def test_layers_off_in_the_environment_beats_a_file_that_says_on(env: Env) -> None:
    env.machine_file("[telemetry]\nspans = true\nshadow = true\n")
    env.environ["CISTERNAL_TELEMETRY"] = "off"
    assert env.get("spans").enabled is False
    assert env.get("shadow").enabled is False


def test_layers_consumer_subtable_beats_generic_table_in_a_file(env: Env) -> None:
    env.machine_file("[telemetry]\nspans = false\n[telemetry.maraxiom]\nspans = true\n")
    d = env.get("spans")
    assert (d.enabled, d.layer) == (True, "machine file [telemetry.maraxiom]")
    other = env.get("spans", consumer="bathos", registration=None)
    assert (other.enabled, other.layer) == (False, "machine file [telemetry]")


def test_layers_pyproject_consumer_subtable_beats_generic_table(env: Env) -> None:
    env.pyproject("[tool.cisternal.telemetry]\nshadow = false\n[tool.cisternal.telemetry.maraxiom]\nshadow = true\n")
    d = env.get("shadow")
    assert (d.enabled, d.layer) == (True, "pyproject.toml [tool.cisternal.telemetry.maraxiom]")


def test_layers_registration_is_discovered_through_the_entry_point_group(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = SimpleNamespace(name="maraxiom", load=lambda: REG)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [fake])
    d = env.get("shadow", registration=None)
    assert (d.enabled, d.layer, d.registered) == (True, "registered default", True)


def test_layers_unknown_behaviour_raises(env: Env) -> None:
    with pytest.raises(TelemetrySettingError, match="unknown telemetry behaviour"):
        env.get("everything")


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["all", "1", "true", "yes", "maraxiom", "MARAXIOM", " True "])
def test_env_whole_consumer_on_tokens(env: Env, token: str) -> None:
    env.environ["CISTERNAL_TELEMETRY"] = token
    assert env.get("spans").enabled is True
    assert env.get("shadow").enabled is True


@pytest.mark.parametrize("token", ["off", "none", "0", "false", "OFF"])
def test_env_whole_consumer_off_tokens(env: Env, token: str) -> None:
    env.machine_file("[telemetry]\nspans = true\nshadow = true\n")
    env.environ["CISTERNAL_TELEMETRY"] = token
    assert env.get("spans").enabled is False
    assert env.get("shadow").enabled is False


@pytest.mark.parametrize("token", ["", "   ", "bathos", "contemplex,xperiri"])
def test_env_whole_consumer_empty_or_other_consumer_is_no_opinion(env: Env, token: str) -> None:
    env.environ["CISTERNAL_TELEMETRY"] = token
    assert env.get("spans").layer == "registered default"
    assert env.get("shadow").layer == "registered default"


def test_env_whole_consumer_accepts_a_comma_list(env: Env) -> None:
    env.environ["CISTERNAL_TELEMETRY"] = "bathos, maraxiom"
    assert env.get("spans").enabled is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("on", True), ("1", True), ("ON", True), ("false", False), ("off", False), ("0", False)],
)
def test_env_behaviour_variable_vocabulary(env: Env, raw: str, expected: bool) -> None:
    env.environ["CISTERNAL_TELEMETRY_SHADOW"] = raw
    d = env.get("shadow")
    assert (d.enabled, d.layer) == (expected, "environment variable CISTERNAL_TELEMETRY_SHADOW")


@pytest.mark.parametrize("raw", ["", "  "])
def test_env_behaviour_variable_empty_is_no_opinion(env: Env, raw: str) -> None:
    env.environ["CISTERNAL_TELEMETRY_SPANS"] = raw
    assert env.get("spans").layer == "registered default"


@pytest.mark.parametrize("raw", ["maybe", "2", "enabled"])
def test_env_behaviour_variable_invalid_value_raises_naming_the_variable(env: Env, raw: str) -> None:
    env.environ["CISTERNAL_TELEMETRY_SPANS"] = raw
    with pytest.raises(TelemetrySettingError, match="CISTERNAL_TELEMETRY_SPANS"):
        env.get("spans")


# ---------------------------------------------------------------------------
# files_and_settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("[telemetry\nspans = true\n", "malformed user config"),
        ("[telemetry]\nspans = \"yes\"\n", "telemetry.spans must be true or false"),
        ("telemetry = 3\n", "'telemetry' must be a table"),
        ("[telemetry.maraxiom]\nshadow = 1\n", "telemetry.maraxiom.shadow must be true or false"),
    ],
)
def test_files_and_settings_malformed_machine_file_raises_with_file_and_key(env: Env, body: str, needle: str) -> None:
    env.machine_file(body)
    with pytest.raises(TelemetrySettingError, match=needle) as info:
        env.get("spans")
    assert str(env.machine) in str(info.value)


def test_files_and_settings_malformed_pyproject_raises(env: Env) -> None:
    env.pyproject("[tool.cisternal.telemetry]\nspans = 1\n")
    with pytest.raises(TelemetrySettingError, match="tool.cisternal.telemetry.spans must be true or false"):
        env.get("spans")


PLACEHOLDERS = [
    "${CISTERNAL_TELEMETRY_SHADOW}",
    "${CISTERNAL_TELEMETRY_SHADOW:-}",
    "${X:-off}",
    "{env:CISTERNAL_TELEMETRY_SHADOW}",
    "$CISTERNAL_TELEMETRY_SHADOW",
    "%CISTERNAL_TELEMETRY_SHADOW%",
    "  ${X}  ",
]


@pytest.mark.parametrize("value", PLACEHOLDERS)
def test_placeholder_forms_are_no_opinion(env: Env, value: str, capsys: pytest.CaptureFixture[str]) -> None:
    """A surface that passes a placeholder 'as written' must not turn a setting off (spec FR-1)."""
    env.environ["CISTERNAL_TELEMETRY_SHADOW"] = value
    d = env.get("shadow")  # must not raise
    assert d.layer == "registered default" and d.enabled is True and d.ok
    err = capsys.readouterr().err
    assert "ignored unexpanded placeholder in environment variable CISTERNAL_TELEMETRY_SHADOW" in err


def test_placeholder_lets_the_next_layer_decide(env: Env) -> None:
    env.environ["CISTERNAL_TELEMETRY_SHADOW"] = "${CISTERNAL_TELEMETRY_SHADOW:-}"
    env.machine_file("[telemetry.maraxiom]\nshadow = false\n")
    d = env.get("shadow")
    assert d.enabled is False and d.layer.startswith("machine file")


def test_placeholder_notice_is_printed_once_per_process(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.environ["CISTERNAL_TELEMETRY_SHADOW"] = "${X}"
    env.get("shadow")
    env.get("shadow")
    assert capsys.readouterr().err.count("ignored unexpanded placeholder") == 1


def test_placeholder_applies_to_the_spans_variable_too(env: Env) -> None:
    env.environ["CISTERNAL_TELEMETRY_SPANS"] = "${CISTERNAL_TELEMETRY_SPANS}"
    d = env.get("spans")
    assert d.layer == "registered default" and d.enabled is False


@pytest.mark.parametrize("value", ["maybe", "${1X}", "$", "${A B}", "prefix${X}", "${X}suffix", "%X", "${X", "$1"])
def test_placeholder_rule_does_not_swallow_other_invalid_values(env: Env, value: str) -> None:
    env.environ["CISTERNAL_TELEMETRY_SHADOW"] = value
    with pytest.raises(TelemetrySettingError, match="invalid value"):
        env.get("shadow")


def test_placeholder_legitimate_values_are_unchanged(env: Env) -> None:
    for raw, expected in (("on", True), ("off", False), ("1", True), ("0", False), (" TRUE ", True)):
        env.environ["CISTERNAL_TELEMETRY_SHADOW"] = raw
        assert env.get("shadow").enabled is expected


def test_files_and_settings_deeply_nested_settings_fail_closed_not_raise(env: Env) -> None:
    depth = 200_000
    env.settings(None, raw="[" * depth + "]" * depth)
    d = env.get("shadow")  # must not raise RecursionError
    assert d.enabled is False
    assert d.error is not None and "cannot read" in d.error


def test_files_and_settings_missing_working_directory_is_no_repository_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()  # the process's working directory no longer exists
    assert ts._find_repo_root() is None
    d = telemetry_setting(
        "maraxiom",
        "shadow",
        registration=REG,
        config_dir=tmp_path / "claude",
        user_config_file=tmp_path / "machine.toml",
        environ={},
    )
    assert d.layer == "registered default" and d.ok


def test_files_and_settings_missing_settings_file_is_no_opinion(env: Env) -> None:
    d = env.get("shadow")
    assert d.layer == "registered default" and d.ok


def test_files_and_settings_missing_entry_and_absent_option_are_no_opinion(env: Env) -> None:
    env.settings({"enabledPlugins": {"maraxiom@cisternal-local": True}})
    assert env.get("shadow").layer == "registered default"
    env.settings({"enabledPlugins": {"maraxiom@cisternal-local": True}, "pluginConfigs": {"maraxiom@cisternal-local": {"options": {}}}})
    assert env.get("shadow").layer == "registered default"


def test_files_and_settings_inherit_is_no_opinion(env: Env) -> None:
    env.plugin_option("telemetry_shadow", "inherit")
    env.machine_file("[telemetry]\nshadow = false\n")
    d = env.get("shadow")
    assert (d.enabled, d.layer) == (False, "machine file [telemetry]")


@pytest.mark.parametrize(("value", "expected"), [("on", True), ("off", False)])
def test_files_and_settings_on_and_off_are_honoured(env: Env, value: str, expected: bool) -> None:
    env.plugin_option("telemetry_spans", value)
    d = env.get("spans")
    assert (d.enabled, d.layer, d.ok) == (expected, "saved plugin option", True)


@pytest.mark.parametrize(
    "enabled_plugins",
    [pytest.param(None, id="no-enabledPlugins"), pytest.param({"maraxiom@cisternal-local": False}, id="disabled-here")],
)
def test_files_and_settings_a_saved_option_applies_without_a_user_level_enabled_entry(
    env: Env, enabled_plugins: object
) -> None:
    """Claude Code installs have scopes: a project-scope install has no user `enabledPlugins` entry, but its
    saved options live in the user's `pluginConfigs`. Ignoring them would silently drop a user's opt-out."""
    data: dict[str, object] = {
        "pluginConfigs": {"maraxiom@cisternal-local": {"options": {"telemetry_shadow": "off"}}},
    }
    if enabled_plugins is not None:
        data["enabledPlugins"] = enabled_plugins
    env.settings(data)
    d = env.get("shadow")
    assert (d.enabled, d.layer) == (False, "saved plugin option")


def test_files_and_settings_several_marketplaces_are_told_apart_by_enabled_plugins(env: Env) -> None:
    env.settings(
        {
            "enabledPlugins": {"maraxiom@a": False, "maraxiom@b": True},
            "pluginConfigs": {
                "maraxiom@a": {"options": {"telemetry_shadow": "on"}},
                "maraxiom@b": {"options": {"telemetry_shadow": "off"}},
            },
        }
    )
    d = env.get("shadow")
    assert (d.enabled, d.layer, d.ok) == (False, "saved plugin option", True)


def test_files_and_settings_another_plugins_entry_is_ignored(env: Env) -> None:
    env.plugin_option("telemetry_shadow", "off", plugin="bathos@cisternal-local")
    assert env.get("shadow").layer == "registered default"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda e: e.settings(None, raw="{not json"), id="bad-json"),
        pytest.param(lambda e: e.settings(None, raw="[1, 2]"), id="not-an-object"),
        pytest.param(lambda e: e.plugin_option("telemetry_shadow", "sometimes"), id="value-outside-the-set"),
        pytest.param(lambda e: e.plugin_option("telemetry_shadow", True), id="wrong-type"),
        pytest.param(
            lambda e: e.settings(
                {
                    "enabledPlugins": {"maraxiom@a": True, "maraxiom@b": True},
                    "pluginConfigs": {"maraxiom@a": {"options": {}}, "maraxiom@b": {"options": {}}},
                }
            ),
            id="two-enabled-entries",
        ),
        pytest.param(
            lambda e: e.settings(
                {
                    "enabledPlugins": {"maraxiom@a": False},
                    "pluginConfigs": {"maraxiom@a": {"options": {}}, "maraxiom@b": {"options": {}}},
                }
            ),
            id="two-entries-none-enabled",
        ),
        pytest.param(
            lambda e: e.settings({"enabledPlugins": {"maraxiom@a": True}, "pluginConfigs": {"maraxiom@a": {"options": 7}}}),
            id="options-not-an-object",
        ),
        pytest.param(
            lambda e: e.settings(
                {"enabledPlugins": [], "pluginConfigs": {"maraxiom@a": {"options": {}}, "maraxiom@b": {"options": {}}}}
            ),
            id="enabledPlugins-not-an-object-when-it-is-needed",
        ),
        pytest.param(lambda e: e.settings({"pluginConfigs": []}), id="pluginConfigs-not-an-object"),
    ],
)
def test_files_and_settings_unknowable_intent_fails_closed(env: Env, mutate, capsys: pytest.CaptureFixture[str]) -> None:
    env.machine_file("[telemetry]\nshadow = true\n")  # a lower layer that would say on
    mutate(env)
    d = env.get("shadow")
    assert d.enabled is False, "failing open would turn the user's off into the shadow default"
    assert d.layer == "plugin option (unreadable)"
    assert d.error and str(env.config_dir / "settings.json") in d.error
    assert d.ok is False
    assert "treating maraxiom shadow as off" in capsys.readouterr().err


def test_files_and_settings_fail_closed_notice_is_printed_once_per_process(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.settings(None, raw="{broken")
    env.get("shadow")
    env.get("shadow")
    assert capsys.readouterr().err.count("treating maraxiom shadow as off") == 1


def test_files_and_settings_claude_config_dir_is_honoured_from_the_environment(env: Env, tmp_path: Path) -> None:
    other = tmp_path / "other-claude"
    other.mkdir()
    (other / "settings.json").write_text(
        json.dumps(
            {
                "enabledPlugins": {"maraxiom@x": True},
                "pluginConfigs": {"maraxiom@x": {"options": {"telemetry_shadow": "off"}}},
            }
        ),
        encoding="utf-8",
    )
    d = telemetry_setting(
        "maraxiom",
        "shadow",
        registration=REG,
        repo_root=env.root,
        user_config_file=env.machine,
        environ={"CLAUDE_CONFIG_DIR": str(other)},
    )
    assert (d.enabled, d.layer, d.source) == (False, "saved plugin option", other / "settings.json")


def test_files_and_settings_cache_follows_the_file(env: Env) -> None:
    env.plugin_option("telemetry_shadow", "off")
    assert env.get("shadow").enabled is False
    env.plugin_option("telemetry_shadow", "on")  # different size/mtime
    assert env.get("shadow").enabled is True


def test_files_and_settings_real_install_probe_fixture(tmp_path: Path) -> None:
    """The shape Claude Code actually wrote for a marketplace-installed plugin (RESULTS row 13)."""
    claude = tmp_path / "claude"
    claude.mkdir()
    shutil.copy(FIXTURE, claude / "settings.json")
    reg = {
        "plugin": "tprobe",
        "spans_option": "telemetry_mode",
        "shadow_option": "telemetry_shadow",
        "defaults": {"spans": True, "shadow": True},
    }
    common = {"registration": reg, "config_dir": claude, "repo_root": tmp_path, "user_config_file": tmp_path / "none.toml", "environ": {}}
    spans = telemetry_setting("tprobe", "spans", **common)
    shadow = telemetry_setting("tprobe", "shadow", **common)
    assert (spans.enabled, spans.layer) == (False, "saved plugin option")  # saved "off" beats default on
    assert (shadow.enabled, shadow.layer) == (True, "registered default")  # option never saved


def test_files_and_settings_settings_are_not_read_without_a_registration(env: Env) -> None:
    env.settings(None, raw="{broken")
    d = env.get("shadow", consumer="bathos", registration=None)
    assert d.ok and d.layer == "off (no registered default)"


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_from_mapping_validates() -> None:
    reg = Registration.from_mapping(REG)
    assert (reg.plugin, reg.option_for("spans"), reg.default_for("shadow")) == ("maraxiom", "telemetry_spans", True)
    for bad in ({}, {**REG, "plugin": ""}, {**REG, "defaults": 3}, {**REG, "defaults": {"spans": "no"}}):
        with pytest.raises(TelemetrySettingError):
            Registration.from_mapping(bad)


def test_registry_discovery_ignores_other_names_and_survives_a_failing_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> object:
        raise RuntimeError("cannot import")

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [SimpleNamespace(name="other", load=lambda: REG), SimpleNamespace(name="maraxiom", load=boom)],
    )
    assert discover_registration("maraxiom") is None
    assert "failed to load" in capsys.readouterr().err
    assert discover_registration("missing") is None


def test_registry_module_level_imports_are_standard_library_only() -> None:
    """The resolver must not pull cisternal.telemetry or the cisternal.shadow package in (resolution.py:18-21)."""
    tree = ast.parse(Path(ts.__file__).read_text(encoding="utf-8"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    assert names, "expected some imports"
    assert all(n == "__future__" or n in sys.stdlib_module_names for n in names), names


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------


def test_writer_creates_the_file_and_the_resolver_reads_it_back(env: Env) -> None:
    path = set_machine_value("maraxiom", "shadow", False, user_config_file=env.machine)
    assert path == env.machine
    d = env.get("shadow")
    assert (d.enabled, d.layer) == (False, "machine file [telemetry.maraxiom]")


def test_writer_preserves_every_other_line_and_the_top_level_marketplace_key(env: Env) -> None:
    original = (
        "# my config\nplugin_marketplace = \"~/.cisternal/claude-plugin-marketplace\"\n\n"
        "[shadow]\nmode_state_dir = \".praxia/mode_state\"\n\n[telemetry]\nlog_dir = \"~/logs\"\n"
    )
    env.machine_file(original)
    set_machine_value("maraxiom", "spans", True, user_config_file=env.machine)
    text = env.machine.read_text(encoding="utf-8")
    assert text.startswith(original.rstrip("\n"))
    assert text.endswith("[telemetry.maraxiom]\nspans = true\n")


def test_writer_replaces_an_existing_key_and_inserts_a_missing_one(env: Env) -> None:
    env.machine_file("[telemetry.maraxiom]\n# keep me\nspans = false\nrecords_dir = \"~/r\"\n[other]\nspans = 1\n")
    set_machine_value("maraxiom", "spans", True, user_config_file=env.machine)
    set_machine_value("maraxiom", "shadow", False, user_config_file=env.machine)
    text = env.machine.read_text(encoding="utf-8")
    assert "spans = true" in text and "spans = false" not in text
    assert "# keep me" in text and 'records_dir = "~/r"' in text
    assert "[other]\nspans = 1\n" in text  # another table's key of the same name is untouched
    assert env.get("shadow").enabled is False


def test_writer_writes_string_values_for_records_dir(env: Env) -> None:
    set_machine_value("maraxiom", "records_dir", "~/.local/state/cisternal/maraxiom/records", user_config_file=env.machine)
    assert 'records_dir = "~/.local/state/cisternal/maraxiom/records"' in env.machine.read_text(encoding="utf-8")


def test_writer_refuses_an_edit_that_would_corrupt_the_file_and_changes_nothing(env: Env) -> None:
    original = "[telemetry]\nmaraxiom = 1\n"  # a scalar where the subtable would have to go
    env.machine_file(original)
    with pytest.raises(TelemetrySettingError, match="nothing changed"):
        set_machine_value("maraxiom", "spans", True, user_config_file=env.machine)
    assert env.machine.read_text(encoding="utf-8") == original


def test_writer_writes_through_a_symlink(env: Env, tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "config.toml"
    target.parent.mkdir()
    target.write_text("[shadow]\nmode_state_dir = \"m\"\n", encoding="utf-8")
    env.machine.parent.mkdir(parents=True)
    env.machine.symlink_to(target)
    set_machine_value("maraxiom", "spans", True, user_config_file=env.machine)
    assert env.machine.is_symlink()
    assert "spans = true" in target.read_text(encoding="utf-8")
    assert 'mode_state_dir = "m"' in target.read_text(encoding="utf-8")


def test_writer_leaves_no_temp_files_behind(env: Env) -> None:
    set_machine_value("maraxiom", "spans", True, user_config_file=env.machine)
    assert [p.name for p in env.machine.parent.iterdir()] == ["config.toml"]


def _set(env: Env, behaviour: str, enabled: bool):
    return set_telemetry_setting(
        "maraxiom",
        behaviour,
        enabled,
        registration=REG,
        config_dir=env.config_dir,
        repo_root=env.root,
        user_config_file=env.machine,
        environ=env.environ,
    )


def test_set_setting_reports_the_machine_file_as_the_decider_when_nothing_outranks_it(env: Env) -> None:
    result = _set(env, "shadow", False)
    assert result.overridden is False
    assert (result.decision.enabled, result.decision.layer) == (False, "machine file [telemetry.maraxiom]")


@pytest.mark.parametrize(
    ("arrange", "layer"),
    [
        pytest.param(lambda e: e.environ.update({"CISTERNAL_TELEMETRY_SHADOW": "on"}), "environment variable CISTERNAL_TELEMETRY_SHADOW", id="env"),
        pytest.param(lambda e: e.pyproject("[tool.cisternal.telemetry]\nshadow = true\n"), "pyproject.toml [tool.cisternal.telemetry]", id="pyproject"),
        pytest.param(lambda e: e.plugin_option("telemetry_shadow", "on"), "saved plugin option", id="plugin-option"),
    ],
)
def test_set_setting_reports_an_overriding_layer_but_still_writes(env: Env, arrange, layer: str) -> None:
    arrange(env)
    result = _set(env, "shadow", False)
    assert result.overridden is True
    assert result.decision.layer == layer and result.decision.enabled is True
    assert "shadow = false" in env.machine.read_text(encoding="utf-8")  # the owner's preference is recorded


def test_set_setting_treats_an_unreadable_plugin_option_as_overriding(env: Env) -> None:
    env.settings(None, raw="{broken")
    result = _set(env, "shadow", True)
    assert result.overridden is True and result.decision.error is not None


def test_set_setting_rejects_an_unknown_behaviour(env: Env) -> None:
    with pytest.raises(TelemetrySettingError):
        _set(env, "everything", True)
    assert not env.machine.exists()
