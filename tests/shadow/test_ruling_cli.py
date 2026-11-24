"""Tests for the `cisternal shadow packet` command (Task 2 of the ruling UI).

Covers: a packet file written from adapter items with the stdout summary,
the empty-store path (exit 0, no file), and an unknown adapter (exit 2).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import cisternal.shadow.ruling.adapters as adapters_mod
from cisternal.cli import app
from cisternal.shadow.ruling.packet import RulingItem, load_packet


def _item(i: int, *, probe: bool = False) -> RulingItem:
    return RulingItem(
        item_id=f"feat|k{i}",
        feature="feat",
        subject_key=f"k{i}",
        is_probe=probe,
        inputs_sha256="0" * 64,
        answer={"kind": "binary", "positive": "present", "negative": "absent"},
        show={"text": f"text {i}"},
        adapter="fake",
    )


class _FakeAdapter:
    name = "fake"

    def __init__(self, items: list[RulingItem]) -> None:
        self._items = items

    def open_items(self, store: Path, limit: int) -> list[RulingItem]:
        return self._items[:limit]


class _FakeEntryPoint:
    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        return self._obj


@pytest.fixture
def register_adapter(monkeypatch: pytest.MonkeyPatch):
    """Register a fake `fake` adapter behind the entry-point group."""

    def _register(items: list[RulingItem]) -> None:
        eps = [_FakeEntryPoint("fake", _FakeAdapter(items))]
        monkeypatch.setattr(
            adapters_mod,
            "entry_points",
            lambda group: eps if group == adapters_mod.ADAPTER_GROUP else [],
        )

    return _register


def test_packet_cli_writes_packet(
    tmp_path: Path, register_adapter, capsys: pytest.CaptureFixture[str]
) -> None:
    register_adapter([_item(0), _item(1, probe=True), _item(2)])
    store = tmp_path / "store"
    store.mkdir()
    out = tmp_path / "ruling_packet.json"

    with pytest.raises(SystemExit) as exit_info:
        app(
            [
                "shadow", "packet",
                "--adapter", "fake",
                "--store", str(store),
                "--out", str(out),
                "--session-id", "sess-1",
                "--task-id", "261124_shadow-ruling-ui",
            ]
        )
    assert exit_info.value.code in (0, None)

    assert out.exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary["items"] == 3
    assert summary["probes"] == 1
    assert summary["sheet_only"] == 0
    assert summary["packet"] == str(out)

    packet = load_packet(out)
    assert packet.origin.host == socket.gethostname()
    assert Path(packet.origin.store_path).is_absolute()
    assert packet.origin.store_path == str(store.resolve())
    assert packet.origin.session_id == "sess-1"
    assert packet.origin.task_id == "261124_shadow-ruling-ui"
    assert packet.items[0].is_probe  # probes first


def test_packet_cli_nothing_open(
    tmp_path: Path, register_adapter, capsys: pytest.CaptureFixture[str]
) -> None:
    register_adapter([])
    store = tmp_path / "store"
    store.mkdir()
    out = tmp_path / "ruling_packet.json"

    with pytest.raises(SystemExit) as exit_info:
        app(
            [
                "shadow", "packet",
                "--adapter", "fake",
                "--store", str(store),
                "--out", str(out),
                "--session-id", "sess-1",
                "--task-id", "261124_shadow-ruling-ui",
            ]
        )
    assert exit_info.value.code in (0, None)
    assert not out.exists()
    assert json.loads(capsys.readouterr().out) == {
        "packet": None,
        "message": "nothing to rule",
    }


def test_packet_cli_unknown_adapter(
    tmp_path: Path, register_adapter, capsys: pytest.CaptureFixture[str]
) -> None:
    register_adapter([_item(0)])
    store = tmp_path / "store"
    store.mkdir()
    out = tmp_path / "ruling_packet.json"

    with pytest.raises(SystemExit) as exit_info:
        app(
            [
                "shadow", "packet",
                "--adapter", "no-such-adapter",
                "--store", str(store),
                "--out", str(out),
                "--session-id", "sess-1",
                "--task-id", "261124_shadow-ruling-ui",
            ]
        )
    assert exit_info.value.code == 2
    assert not out.exists()
    assert "no-such-adapter" in capsys.readouterr().err
