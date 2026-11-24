"""Tests for cisternal.shadow.ruling packet model, SVG sanitizer and adapter protocol.

Covers the Task 1 contract: probes-first ordering with a cap, verdict-key
rejection in `show`, SVG allowlist sanitizing, the per-item and per-packet SVG
budgets with sheet-only overflow, and packet JSON round-trip with version gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.shadow.ruling.packet import (
    Origin,
    PacketError,
    RulingItem,
    build_packet,
    load_packet,
)
from cisternal.shadow.ruling.svg import SvgRejected, sanitize_svg

ORIGIN = Origin(
    host="test-host",
    store_kind="file",
    store_path="/tmp/store",
    session_id="sess-1",
    task_id="261124_shadow-ruling-ui",
)


def _item(i: int, *, probe: bool = False, show: dict | None = None) -> RulingItem:
    return RulingItem(
        item_id=f"feat|k{i}",
        feature="feat",
        subject_key=f"k{i}",
        is_probe=probe,
        inputs_sha256="0" * 64,
        answer={"kind": "binary", "positive": "present", "negative": "absent"},
        show=show if show is not None else {"text": f"text {i}"},
        adapter="maraxiom.prose",
    )


def _svg_of_bytes(n: int) -> str:
    """Return a well-formed SVG whose serialized size is exactly n bytes or more."""
    head = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    tail = "</svg>"
    filler_len = max(0, n - len(head) - len(tail) - len('<desc>""</desc>'))
    return f"{head}<desc>{'x' * filler_len}</desc>{tail}"


def test_build_packet_orders_probes_first_and_caps() -> None:
    items = [_item(i) for i in range(40)] + [
        _item(100 + i, probe=True) for i in range(5)
    ]
    packet = build_packet(items, ORIGIN)
    assert len(packet.items) == 40
    assert all(it.is_probe for it in packet.items[:5])
    assert not any(it.is_probe for it in packet.items[5:])


def test_show_rejects_verdict_keys() -> None:
    for key in ("verdict", "tag", "severity", "hint", "relayed"):
        bad = _item(0, show={"text": "ok", key: "leak"})
        with pytest.raises(PacketError):
            build_packet([bad], ORIGIN)


def test_svg_sanitize_strips_script_and_external_href() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        "<script>alert(1)</script>"
        "<foreignObject><div>x</div></foreignObject>"
        '<a href="http://evil.example/x"><rect width="5" height="5"/></a>'
        '<image href="http://evil.example/i.png"/>'
        '<rect width="3" height="3" onclick="bad()"/>'
        "</svg>"
    )
    out = sanitize_svg(svg)
    assert "<script" not in out
    assert "foreignObject" not in out
    assert 'href="http' not in out
    assert "onclick" not in out
    assert "<rect" in out


def test_svg_sanitize_rejects_unparseable() -> None:
    with pytest.raises(SvgRejected):
        sanitize_svg("<svg><not-closed")


def test_svg_budget_moves_oversize_to_sheet_only() -> None:
    oversize = _item(0, show={"text": "big", "image_svg": _svg_of_bytes(301 * 1024)})
    small = _item(1, show={"text": "small", "image_svg": _svg_of_bytes(1024)})
    packet = build_packet([oversize, small], ORIGIN)
    assert oversize.item_id not in [it.item_id for it in packet.items]
    assert oversize.item_id in packet.sheet_only
    assert small.item_id in [it.item_id for it in packet.items]


def test_svg_packet_budget_trims_from_end_into_sheet_only() -> None:
    # Each item is just under the 300 KB per-item cap; 30 of them exceed 8 MB total.
    items = [
        _item(i, show={"text": "t", "image_svg": _svg_of_bytes(290 * 1024)})
        for i in range(30)
    ]
    packet = build_packet(items, ORIGIN)
    kept_bytes = sum(len(it.show["image_svg"].encode("utf-8")) for it in packet.items)
    assert kept_bytes <= 8 * 1024 * 1024
    assert packet.items and packet.sheet_only
    assert packet.items[0].item_id == items[0].item_id
    assert packet.sheet_only[-1] == items[-1].item_id


def test_packet_roundtrip_and_unknown_version(tmp_path: Path) -> None:
    items = [_item(i) for i in range(3)]
    packet = build_packet(items, ORIGIN)
    path = tmp_path / "packet.json"
    path.write_text(packet.to_json(), encoding="utf-8")
    assert load_packet(path) == packet

    bumped = packet.to_json().replace('"packet_v": 1', '"packet_v": 2')
    path.write_text(bumped, encoding="utf-8")
    with pytest.raises(PacketError):
        load_packet(path)
