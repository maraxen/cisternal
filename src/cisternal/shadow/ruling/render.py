"""Render the owner ruling page (Path A) or offline sheet (Path B), spec §5.2 and §5.5.

Both modes share one HTML template (`template.html`, shipped as package data).
Blocks marked `/*@page*/ ... /*@/page*/` are kept only for the page, and
`/*@sheet*/ ... /*@/sheet*/` only for the sheet, so the sheet carries no
capability code. The packet is embedded as JSON with every `<`, `>` and `&`
written as a `\\uXXXX` escape, so packet text can never close the script tag.
"""

from __future__ import annotations

import importlib.resources
import re
from typing import Literal

from cisternal.shadow.ruling.packet import RulingPacket

Mode = Literal["page", "sheet"]

_PAGE_BLOCK = re.compile(r"/\*@page\*/.*?/\*@/page\*/", re.S)
_SHEET_BLOCK = re.compile(r"/\*@sheet\*/.*?/\*@/sheet\*/", re.S)
_KEEP_PAGE = re.compile(r"/\*@page\*/(.*?)/\*@/page\*/", re.S)
_KEEP_SHEET = re.compile(r"/\*@sheet\*/(.*?)/\*@/sheet\*/", re.S)
_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}
_SHEET_HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
)


def _template_text() -> str:
    resource = importlib.resources.files("cisternal.shadow.ruling").joinpath("template.html")
    return resource.read_text(encoding="utf-8")


def _embed_json(packet: RulingPacket) -> str:
    text = packet.to_json()
    for char, escape in _ESCAPES.items():
        text = text.replace(char, escape)
    return text


def render(packet: RulingPacket, mode: Mode) -> str:
    """Return a standalone HTML document for `packet` in `mode`.

    Args:
        packet: The ruling packet to embed.
        mode: "page" for the Artifact page with db and user capabilities,
            "sheet" for the offline file with no capabilities.

    Raises:
        ValueError: `mode` is neither "page" nor "sheet".
    """
    if mode not in ("page", "sheet"):
        raise ValueError(f"unknown ruling render mode {mode!r}")

    text = _template_text()
    if mode == "page":
        text = _SHEET_BLOCK.sub("", text)
        text = _KEEP_PAGE.sub(lambda m: m.group(1), text)
    else:
        text = _PAGE_BLOCK.sub("", text)
        text = _KEEP_SHEET.sub(lambda m: m.group(1), text)

    # Packet last, so any placeholder text inside packet content is never expanded.
    text = text.replace("__MODE__", mode)
    text = text.replace("__PACKET__", _embed_json(packet))
    if mode == "page":
        return text

    # The sheet opens as a local file, so it is a complete document (R11).
    text = text.replace('<div class="wrap">', '</head>\n<body>\n<div class="wrap">', 1)
    return _SHEET_HEAD + text + "\n</body>\n</html>\n"


__all__ = ["Mode", "render"]
