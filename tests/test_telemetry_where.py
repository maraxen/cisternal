"""``cisternal telemetry where`` (spec 261116_telemetry-config-layers, FR-4)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cisternal import cli
from cisternal.probe.telemetry_where import (
    build_where_report,
    format_where_json,
    format_where_report,
    where_exit_code,
)
from cisternal.telemetry_setting import TelemetrySettingError, consumer_records_dir

REG = {
    "plugin": "maraxiom",
    "spans_option": "telemetry_spans",
    "shadow_option": "telemetry_shadow",
    "defaults": {"spans": False, "shadow": True},
}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "CISTERNAL_TELEMETRY",
        "CISTERNAL_TELEMETRY_SPANS",
        "CISTERNAL_TELEMETRY_SHADOW",
        "CISTERNAL_TELEMETRY_LOG_DIR",
        "CISTERNAL_LOG_DIR",
        "BTH_LOG_DIR",
        "CTXP_LOG_DIR",
        "CISTERNAL_MODE_STATE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.machine = tmp_path / "xdg" / "cisternal" / "config.toml"
        self.claude = tmp_path / "claude"
        self.claude.mkdir()

    def report(self, consumer: str = "maraxiom", **kw):
        kw.setdefault("registration", REG)
        return build_where_report(
            consumer,
            config_dir=self.claude,
            repo_root=self.root,
            user_config_file=self.machine,
            **kw,
        )

    def pyproject(self, body: str) -> None:
        (self.root / "pyproject.toml").write_text(body, encoding="utf-8")

    def machine_file(self, body: str) -> None:
        self.machine.parent.mkdir(parents=True, exist_ok=True)
        self.machine.write_text(body, encoding="utf-8")


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_where_unregistered_consumer_says_so_and_is_off(world: World) -> None:
    report = world.report("nobody", registration=None)
    assert report["registration"] == {"registered": False, "source": "none in this environment"}
    assert report["behaviours"]["spans"]["state"] == "off"
    assert report["behaviours"]["shadow"]["state"] == "off"
    assert report["behaviours"]["shadow"]["layer"] == "off (no registered default)"
    assert where_exit_code(report) == 0


def test_where_shadow_on_is_inert_without_a_mode_state_dir(world: World) -> None:
    report = world.report()
    assert report["behaviours"]["shadow"]["state"] == "on but inert (mode_state_dir unresolved)"
    assert report["behaviours"]["shadow"]["layer"] == "registered default"
    assert report["behaviours"]["spans"]["state"] == "off"


def test_where_shadow_on_is_inert_without_a_records_dir(world: World) -> None:
    world.pyproject('[tool.cisternal.shadow]\nmode_state_dir = ".praxia/mode_state"\n')
    report = world.report()
    assert report["behaviours"]["shadow"]["state"] == "on but inert (records dir not yet generated)"
    assert "mode_state_dir" not in " ".join(report["errors"])


@pytest.mark.parametrize(
    "records_setup",
    ["pyproject_log_dir", "consumer_records_dir"],
)
def test_where_shadow_is_on_when_a_ladder_and_a_records_dir_exist(world: World, records_setup: str) -> None:
    mode = '[tool.cisternal.shadow]\nmode_state_dir = ".praxia/mode_state"\n'
    if records_setup == "pyproject_log_dir":
        world.pyproject(mode + '[tool.cisternal.telemetry]\nlog_dir = ".praxia/records"\n')
    else:
        world.pyproject(mode)
        world.machine_file('[telemetry.maraxiom]\nrecords_dir = "~/.local/state/cisternal/maraxiom/records"\n')
    report = world.report()
    assert report["behaviours"]["shadow"]["state"] == "on"
    if records_setup == "consumer_records_dir":
        assert report["records"]["consumer_records_dir"]["path"] == str(
            Path.home() / ".local/state/cisternal/maraxiom/records"
        )


def test_where_names_the_layer_and_file_that_decided(world: World) -> None:
    world.machine_file("[telemetry]\nspans = true\n")
    spans = world.report()["behaviours"]["spans"]
    assert (spans["state"], spans["layer"], spans["source"]) == ("on", "machine file [telemetry]", str(world.machine))


def test_where_a_broken_settings_file_fails_closed_and_exits_1(world: World) -> None:
    (world.claude / "settings.json").write_text("{nope", encoding="utf-8")
    report = world.report()
    for behaviour in ("spans", "shadow"):
        assert report["behaviours"][behaviour]["state"] == "off (unreadable plugin option)"
    assert report["errors"] and where_exit_code(report) == 1


def test_where_a_malformed_machine_file_exits_3_and_does_not_raise(world: World) -> None:
    world.machine_file("[telemetry]\nspans = \"yes\"\n")
    report = world.report()
    assert report["behaviours"]["spans"]["state"] == "unknown (configuration error)"
    assert report["malformed"] is True and where_exit_code(report) == 3
    assert any("spans must be true or false" in e for e in report["errors"])


def test_where_an_invalid_behaviour_variable_exits_3(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CISTERNAL_TELEMETRY_SHADOW", "maybe")
    report = world.report()
    assert where_exit_code(report) == 3
    assert any("CISTERNAL_TELEMETRY_SHADOW" in e for e in report["errors"])


def test_where_a_placeholder_variable_is_no_opinion_and_exits_0(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CISTERNAL_TELEMETRY_SHADOW", "${CISTERNAL_TELEMETRY_SHADOW:-}")
    report = world.report()
    assert where_exit_code(report) == 0 and not report["errors"]
    assert report["behaviours"]["shadow"]["layer"] == "registered default"


def test_where_how_to_set_lists_every_surface_in_text_and_json(world: World) -> None:
    report = world.report()
    surfaces = [item["surface"] for item in report["how_to_set"]]
    assert surfaces == ["claude", "antigravity", "opencode", "copilot, cursor, jcode, pi", "any surface"]
    text = format_where_report(report)
    assert "how to set it (the same list on every surface):" in text
    for item in report["how_to_set"]:
        assert f"{item['surface']}: {item['route']}" in text
    assert json.loads(format_where_json(report))["how_to_set"] == report["how_to_set"]


def test_where_how_to_set_names_the_asked_consumer_and_nothing_maraxiom_specific(world: World) -> None:
    report = world.report(consumer="bathos")
    routes = " ".join(item["route"] for item in report["how_to_set"])
    assert "[telemetry.bathos]" in routes
    assert "{consumer}" not in routes and "<consumer>" not in routes
    assert "mrx" not in routes and "maraxiom" not in routes.lower()
    assert "apply to every cisternal consumer" in routes


def test_where_how_to_set_never_claims_an_unprobed_surface_is_verified(world: World) -> None:
    routes = " ".join(item["route"] for item in world.report()["how_to_set"]).lower()
    assert "verified" not in routes.replace("unverified", "")
    assert "not probed in a live session" in routes and "second-hand" in routes


def test_where_registration_source_is_labelled(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    given = world.report(registration_source="the maraxiom package")
    assert given["registration"] == {"registered": True, "source": "the maraxiom package"}
    fake = SimpleNamespace(name="maraxiom", load=lambda: REG)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [fake])
    discovered = world.report(registration=None)
    assert discovered["registration"] == {"registered": True, "source": "entry point cisternal.telemetry_consumers"}


def test_where_text_and_json_forms(world: World) -> None:
    report = world.report()
    text = format_where_report(report)
    assert "telemetry for consumer 'maraxiom'" in text
    assert "registered default:" in text and "spans: off; decided by registered default" in text
    assert "mode-state dir:" in text
    assert json.loads(format_where_json(report))["consumer"] == "maraxiom"


def test_where_cli_command_prints_json_and_exits_with_the_report_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as info:
        cli.telemetry_where(consumer="nobody-installed", json_output=True)
    assert info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["registration"]["registered"] is False


def test_where_cli_command_exits_1_on_a_failed_closed_option(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = tmp_path / "claude-cli"
    claude.mkdir()
    (claude / "settings.json").write_text("{nope", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    fake = SimpleNamespace(name="maraxiom", load=lambda: REG)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [fake])
    with pytest.raises(SystemExit) as info:
        cli.telemetry_where(consumer="maraxiom")
    assert info.value.code == 1
    assert "off (unreadable plugin option)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# consumer_records_dir
# ---------------------------------------------------------------------------


def test_consumer_records_dir_unset_cases(tmp_path: Path) -> None:
    missing = tmp_path / "none.toml"
    assert consumer_records_dir("maraxiom", user_config_file=missing) is None
    cfg = tmp_path / "config.toml"
    cfg.write_text("[telemetry]\nlog_dir = \"x\"\n[telemetry.maraxiom]\nspans = true\n", encoding="utf-8")
    assert consumer_records_dir("maraxiom", user_config_file=cfg) is None
    assert consumer_records_dir("bathos", user_config_file=cfg) is None


def test_consumer_records_dir_resolves_relative_to_the_config_dir_and_expands_home(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('[telemetry.maraxiom]\nrecords_dir = "records"\n', encoding="utf-8")
    assert consumer_records_dir("maraxiom", user_config_file=cfg) == ((cfg.parent / "records").resolve(), cfg)
    cfg.write_text('[telemetry.maraxiom]\nrecords_dir = "~/r"\n', encoding="utf-8")
    assert consumer_records_dir("maraxiom", user_config_file=cfg)[0] == (Path.home() / "r").resolve()


@pytest.mark.parametrize("body", ['[telemetry.maraxiom]\nrecords_dir = 3\n', '[telemetry]\nmaraxiom = 1\n'])
def test_consumer_records_dir_malformed_raises(tmp_path: Path, body: str) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(body, encoding="utf-8")
    with pytest.raises(TelemetrySettingError):
        consumer_records_dir("maraxiom", user_config_file=cfg)
