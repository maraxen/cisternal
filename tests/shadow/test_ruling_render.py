"""Tests for the ruling page and offline sheet renderer (Task 3, spec §5.2 and §5.5).

Assertions are on the rendered HTML: the packet is embedded as escaped JSON,
the page-only capability code is absent from the sheet, answer controls are
guarded by the owner check, and nothing is written with innerHTML.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cisternal.cli import app
from cisternal.shadow.ruling.packet import Origin, RulingItem, build_packet, load_packet
from cisternal.shadow.ruling.render import render

ORIGIN = Origin(
    host="test-host",
    store_kind="cisternal_records",
    store_path="/tmp/store",
    session_id="sess-1",
    task_id="261124_shadow-ruling-ui",
)

HOSTILE = "</script><b>x"


def _binary(i: int, text: str = "text") -> RulingItem:
    return RulingItem(
        item_id=f"feat|k{i}",
        feature="feat",
        subject_key=f"k{i}",
        is_probe=False,
        inputs_sha256="0" * 64,
        answer={"kind": "binary", "positive": "present", "negative": "absent"},
        show={"text": text, "context": "ctx", "surface": "surf", "image_svg": None},
        adapter="fake",
    )


def _tags(i: int) -> RulingItem:
    return RulingItem(
        item_id=f"tone|t{i}",
        feature="tone",
        subject_key=f"t{i}",
        is_probe=True,
        inputs_sha256="1" * 64,
        answer={
            "kind": "tags",
            "tags": ["hype", "jargon"],
            "severities": ["clear", "mild"],
            "allow_rewrite": True,
        },
        show={"text": "a sentence", "context": None, "surface": "prose", "image_svg": None},
        adapter="fake",
    )


@pytest.fixture
def packet():
    return build_packet([_binary(1, HOSTILE), _tags(2)], ORIGIN)


def _packet_block(html: str) -> str:
    match = re.search(
        r'<script type="application/json" id="packet">(.*?)</script>', html, re.S
    )
    assert match, "packet JSON block missing"
    return match.group(1)


def _item_json(block: str, item_id: str) -> dict:
    return next(i for i in json.loads(block)["items"] if i["item_id"] == item_id)


def test_render_escapes_markup(packet):
    html = render(packet, "page")

    assert "</script><b>x" not in html
    block = _packet_block(html)
    assert "<" not in block
    assert json.loads(block)["packet_id"] == packet.packet_id
    assert _item_json(block, "feat|k1")["show"]["text"] == HOSTILE


def test_page_mode_uses_db_and_reserved_collection(packet):
    html = render(packet, "page")

    assert 'claude.use("db")' in html
    assert 'claude.use("user")' in html
    assert "cisternal_rulings" in html


def test_page_controls_gated_on_is_owner(packet):
    html = render(packet, "page")

    assert "user.isOwner()" in html
    assert "if (!state.canRule)" in html
    # The controls are only built behind the canRule guard, so the page
    # renders read-only until the owner check resolves true.
    guard_at = html.index("if (!state.canRule)")
    controls_at = html.index("function controlsFor")
    assert controls_at < guard_at


def test_sheet_mode_has_no_capabilities_and_no_os_paths(packet):
    html = render(packet, "sheet")

    assert "claude.use" not in html
    assert "/mnt/c" not in html
    assert "Downloads" not in html
    assert "labels.json" in html


def test_binary_and_tags_controls(packet):
    html = render(packet, "page")
    block = _packet_block(html)

    binary = _item_json(block, "feat|k1")["answer"]
    assert binary == {"kind": "binary", "positive": "present", "negative": "absent"}
    tags = _item_json(block, "tone|t2")["answer"]
    assert tags["severities"] == ["clear", "mild"]
    assert tags["allow_rewrite"] is True
    # Binary buttons and tag chips are built from the packet, not hard-coded.
    assert "answer.positive" in html
    assert "answer.severities" in html
    assert "answer.allow_rewrite" in html


def test_document_id_is_sha256_prefix_and_no_innerhtml(packet):
    html = render(packet, "page")

    assert 'crypto.subtle.digest("SHA-256"' in html
    assert "slice(0, 32)" in html
    assert "innerHTML" not in html
    assert "outerHTML" not in html


def test_svg_is_embedded_as_img_data_url(packet):
    html = render(packet, "sheet")

    assert 'document.createElement("img")' in html
    assert "data:image/svg+xml" in html


def test_no_external_resources(packet):
    for mode in ("page", "sheet"):
        html = render(packet, mode)
        assert not re.search(r'<script[^>]+src=', html)
        assert "<link" not in html
        assert "@import" not in html
        assert "http://" not in html and "https://" not in html


def test_page_head_and_theming(packet):
    html = render(packet, "page")

    assert html.startswith("<title>Shadow rulings</title>")
    assert html.index("<style>") > html.index("<title>")
    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    assert "@media (prefers-color-scheme: dark)" in html


def test_mode_is_embedded_and_sheet_offers_download(packet):
    page = render(packet, "page")
    sheet = render(packet, "sheet")

    assert 'const MODE = "page"' in page
    assert 'const MODE = "sheet"' in sheet
    assert "Download labels.json" in sheet


def test_unknown_mode_is_refused(packet):
    with pytest.raises(ValueError):
        render(packet, "pdf")  # type: ignore[arg-type]


def test_cli_page_and_sheet_write_html(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    packet_file = tmp_path / "ruling_packet.json"
    packet_file.write_text(build_packet([_binary(3)], ORIGIN).to_json(), encoding="utf-8")
    page_out = tmp_path / "page.html"
    sheet_out = tmp_path / "sheet.html"

    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "page", "--packet", str(packet_file), "--out", str(page_out)])
    assert exit_info.value.code in (0, None)
    assert "claude.use" in page_out.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "sheet", "--packet", str(packet_file), "--out", str(sheet_out)])
    assert exit_info.value.code in (0, None)
    assert "claude.use" not in sheet_out.read_text(encoding="utf-8")
    assert load_packet(packet_file).items[0].item_id == "feat|k3"
