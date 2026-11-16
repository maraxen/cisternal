"""``[plugin.telemetry]`` and ``[plugin.config.*]`` through the manifest, composite and snapshot
(spec 261116_telemetry-config-layers, FR-5/FR-6 loading side)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from cisternal.assets.bundle import ConfigOptionAsset, TelemetryAsset
from cisternal.assets.composite import CompositeAssetSource
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.assets.snapshot import dumps_snapshot, loads_snapshot

BASE = """
[plugin]
name = "demo"
version = "1.0.0"
description = "demo plugin"
requires_praxia = "0.0.0"
"""

TELEMETRY = """
[plugin.telemetry]
consumer = "demo"
plugin = "demo"
spans_option = "telemetry_spans"
shadow_option = "telemetry_shadow"
spans_default = false
shadow_default = true

[plugin.config.telemetry_spans]
type = "string"
title = "Span telemetry"
description = "Record how long calls take. 'inherit' defers to your machine config."
options = ["inherit", "on", "off"]
default = "inherit"

[plugin.config.telemetry_shadow]
type = "string"
title = "Shadow records"
description = "Collect local verdict records."
options = ["inherit", "on", "off"]
default = "inherit"
"""


def _load(tmp_path: Path, body: str):
    praxia = tmp_path / "plugin" / ".praxia"
    praxia.mkdir(parents=True, exist_ok=True)
    manifest = praxia / "manifest.toml"
    manifest.write_text((BASE + body).strip() + "\n", encoding="utf-8")
    return manifest, ManifestAssetSource(manifest).load()


def test_manifest_reads_the_telemetry_and_config_tables(tmp_path: Path) -> None:
    _, report = _load(tmp_path, TELEMETRY)
    assert report.warnings == ()
    assert report.bundle.telemetry == TelemetryAsset(
        consumer="demo",
        plugin="demo",
        spans_option="telemetry_spans",
        shadow_option="telemetry_shadow",
        spans_default=False,
        shadow_default=True,
    )
    options = report.bundle.config_options
    assert [o.key for o in options] == ["telemetry_shadow", "telemetry_spans"]  # sorted by key
    spans = options[1]
    assert (spans.type, spans.title, spans.options, spans.default) == (
        "string",
        "Span telemetry",
        ("inherit", "on", "off"),
        "inherit",
    )


def test_manifest_without_the_tables_is_unchanged(tmp_path: Path) -> None:
    _, report = _load(tmp_path, "")
    assert report.warnings == ()
    assert report.bundle.telemetry is None and report.bundle.config_options == ()


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ('[plugin.config.x]\ntype = "color"\ndescription = "d"\n', "is not one of"),
        ('[plugin.config.x]\ntype = "boolean"\ndescription = "d"\noptions = ["a"]\n', "only valid on a string option"),
        ('[plugin.config.x]\ntype = "string"\ndescription = "d"\noptions = [1, 2]\n', "must be a list of strings"),
        ('[plugin.config.x]\ntype = "string"\ndescription = "d"\noptions = ["a"]\ndefault = "b"\n', "is not one of options"),
        ('[plugin.config.x]\ntype = "string"\n', "description is empty"),
        ('[plugin.config.x]\ntype = "string"\ndescription = "d"\ndefault = [1]\n', "default must be a string, number or boolean"),
        ("[plugin]\nconfig = 3\n", "plugin.config must be a table"),
    ],
)
def test_manifest_invalid_config_options_warn_and_never_raise(tmp_path: Path, body: str, needle: str) -> None:
    praxia = tmp_path / "plugin" / ".praxia"
    praxia.mkdir(parents=True)
    manifest = praxia / "manifest.toml"
    # the last [plugin] test case adds a key to [plugin]; everything else appends tables
    text = BASE.strip() + "\n" + (body.split("\n", 1)[1] if body.startswith("[plugin]\n") else body)
    manifest.write_text(text + "\n", encoding="utf-8")
    report = ManifestAssetSource(manifest).load()
    assert any(needle in w for w in report.warnings), report.warnings


def test_manifest_a_skipped_option_is_not_in_the_bundle(tmp_path: Path) -> None:
    _, report = _load(tmp_path, '[plugin.config.bad]\ntype = "color"\ndescription = "d"\n' + TELEMETRY)
    assert [o.key for o in report.bundle.config_options] == ["telemetry_shadow", "telemetry_spans"]


def test_manifest_missing_title_falls_back_to_the_key(tmp_path: Path) -> None:
    _, report = _load(tmp_path, '[plugin.config.x]\ntype = "string"\ndescription = "d"\n')
    assert report.bundle.config_options[0].title == "x"


@pytest.mark.parametrize("missing", ["consumer", "plugin", "spans_option", "shadow_option"])
def test_manifest_telemetry_table_missing_a_name_is_skipped_with_a_warning(tmp_path: Path, missing: str) -> None:
    lines = [ln for ln in TELEMETRY.splitlines() if not ln.startswith(f"{missing} =")]
    _, report = _load(tmp_path, "\n".join(lines))
    assert report.bundle.telemetry is None
    assert any(f"plugin.telemetry.{missing}" in w for w in report.warnings)


def test_manifest_telemetry_naming_an_undeclared_option_warns(tmp_path: Path) -> None:
    body = TELEMETRY.replace("[plugin.config.telemetry_shadow]", "[plugin.config.other]")
    _, report = _load(tmp_path, body)
    assert any("has no [plugin.config.telemetry_shadow] declaration" in w for w in report.warnings)
    assert report.bundle.telemetry is not None  # still loaded; the warning is the signal


def test_manifest_telemetry_default_must_be_a_bool(tmp_path: Path) -> None:
    _, report = _load(tmp_path, TELEMETRY.replace("spans_default = false", 'spans_default = "no"'))
    assert report.bundle.telemetry.spans_default is False
    assert any("spans_default must be true or false" in w for w in report.warnings)


def test_composite_keeps_the_telemetry_and_config_options(tmp_path: Path) -> None:
    manifest, plain = _load(tmp_path, TELEMETRY)
    composite = CompositeAssetSource(manifest).load()
    assert composite.bundle.telemetry == plain.bundle.telemetry
    assert composite.bundle.config_options == plain.bundle.config_options


def test_snapshot_round_trips_the_new_fields(tmp_path: Path) -> None:
    _, report = _load(tmp_path, TELEMETRY)
    restored = loads_snapshot(dumps_snapshot(report.bundle))
    assert restored.telemetry == report.bundle.telemetry
    assert restored.config_options == report.bundle.config_options


def test_snapshot_without_the_new_fields_is_byte_identical_to_before(tmp_path: Path) -> None:
    """Late defaults: a bundle that does not use the fields must not make committed snapshots stale."""
    _, report = _load(tmp_path, TELEMETRY)
    bare = replace(report.bundle, telemetry=None, config_options=())
    text = dumps_snapshot(bare)
    assert '"telemetry"' not in text and '"config_options"' not in text
    assert loads_snapshot(text).config_options == ()


def test_snapshot_option_default_and_options_survive_even_when_empty(tmp_path: Path) -> None:
    option = ConfigOptionAsset(key="flag", type="boolean", title="Flag", description="d", default=False)
    _, report = _load(tmp_path, "")
    bundle = replace(report.bundle, config_options=(option,))
    restored = loads_snapshot(dumps_snapshot(bundle))
    assert restored.config_options == (option,)
    assert restored.config_options[0].default is False  # False is a real default, not "absent"
