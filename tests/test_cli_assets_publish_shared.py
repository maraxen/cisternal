"""Tests for `cisternal assets publish-shared`."""

from __future__ import annotations

import json
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


def test_publish_shared_writes_bundle_and_marketplace_entry(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"

    _invoke_app(
        [
            "assets",
            "publish-shared",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--marketplace",
            str(marketplace),
        ]
    )

    out = marketplace / "plugins" / "fixture-plugin"
    assert (out / ".claude-plugin" / "plugin.json").is_file()
    assert (out / "skills" / "demo-skill" / "SKILL.md").is_file()
    assert (out / "agents" / "recon.md").is_file()

    doc = json.loads(
        (marketplace / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    entries = [p for p in doc["plugins"] if p["name"] == "fixture-plugin"]
    assert len(entries) == 1
    assert entries[0]["source"] == "./plugins/fixture-plugin"

    plugin_json = json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_json["name"] == "fixture-plugin"
    assert plugin_json["version"].startswith("1.2.3+")


def test_publish_shared_is_idempotent_and_prunes_stale_files(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"
    args = [
        "assets",
        "publish-shared",
        "--manifest",
        str(FIXTURE_MANIFEST),
        "--marketplace",
        str(marketplace),
    ]

    _invoke_app(args)
    out = marketplace / "plugins" / "fixture-plugin"
    first_version = json.loads(
        (out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]

    stray = out / "STALE_FILE.txt"
    stray.write_text("leftover", encoding="utf-8")

    _invoke_app(args)

    assert not stray.exists()
    second_version = json.loads(
        (out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    assert first_version == second_version

    doc = json.loads(
        (marketplace / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert [p["name"] for p in doc["plugins"]].count("fixture-plugin") == 1


def test_publish_shared_preserves_other_marketplace_entries(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"
    marketplace_json = marketplace / ".claude-plugin" / "marketplace.json"
    marketplace_json.parent.mkdir(parents=True)
    marketplace_json.write_text(
        json.dumps(
            {
                "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
                "name": "cisternal-local",
                "description": "d",
                "owner": {"name": "cisternal"},
                "plugins": [
                    {"name": "other-tool", "source": "./plugins/other-tool", "description": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )

    _invoke_app(
        [
            "assets",
            "publish-shared",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--marketplace",
            str(marketplace),
        ]
    )

    doc = json.loads(marketplace_json.read_text(encoding="utf-8"))
    names = sorted(p["name"] for p in doc["plugins"])
    assert names == ["fixture-plugin", "other-tool"]


def test_publish_shared_name_override(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"

    _invoke_app(
        [
            "assets",
            "publish-shared",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--marketplace",
            str(marketplace),
            "--name",
            "renamed",
        ]
    )

    assert (marketplace / "plugins" / "renamed" / ".claude-plugin" / "plugin.json").is_file()
    doc = json.loads(
        (marketplace / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert [p["name"] for p in doc["plugins"]] == ["renamed"]
