"""Ruling packet model (spec §5.1).

A packet is the unit a reviewer rules on: a bounded, ordered list of items
drawn from one shadow store. Probes come first so the owner sees known-answer
checks before findings. `show` carries only what the owner may read; it never
holds a verdict, judge hint or relayed answer.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cisternal.shadow.ruling.svg import SvgRejected, sanitize_svg

PACKET_VERSION = 1
DEFAULT_CAP = 40
SVG_ITEM_CAP_BYTES = 300 * 1024
SVG_PACKET_CAP_BYTES = 8 * 1024 * 1024
FORBIDDEN_SHOW_KEYS = frozenset({"verdict", "tag", "severity", "hint", "relayed"})


class PacketError(ValueError):
    """Raised for an invalid item, a forbidden `show` key or an unsupported packet version."""


@dataclass(frozen=True)
class Origin:
    """Where a packet's items came from."""

    host: str
    store_kind: str
    store_path: str
    session_id: str
    task_id: str


@dataclass(frozen=True)
class RulingItem:
    """One rulable record. `answer` holds the answer spec, not an owner ruling."""

    item_id: str
    feature: str
    subject_key: str
    is_probe: bool
    inputs_sha256: str
    answer: dict[str, Any]
    show: dict[str, Any]
    adapter: str


@dataclass
class RulingPacket:
    """An ordered, budgeted set of items plus the ids that did not fit the page."""

    packet_id: str
    created_at: str
    origin: Origin
    items: list[RulingItem]
    sheet_only: list[str]
    packet_v: int = PACKET_VERSION

    def to_json(self) -> str:
        """Serialize to a stable JSON document with `packet_v` first."""
        payload = {
            "packet_v": self.packet_v,
            "packet_id": self.packet_id,
            "created_at": self.created_at,
            "origin": asdict(self.origin),
            "items": [asdict(item) for item in self.items],
            "sheet_only": list(self.sheet_only),
        }
        return json.dumps(payload, indent=2, sort_keys=True)


def _validate_item(item: RulingItem) -> None:
    if item.item_id != f"{item.feature}|{item.subject_key}":
        raise PacketError(
            f"item_id {item.item_id!r} does not match feature|subject_key"
        )
    leaked = FORBIDDEN_SHOW_KEYS.intersection(item.show)
    if leaked:
        raise PacketError(
            f"item {item.item_id!r} show carries forbidden keys: {sorted(leaked)}"
        )


def _svg_bytes(item: RulingItem) -> int:
    svg = item.show.get("image_svg")
    return len(svg.encode("utf-8")) if isinstance(svg, str) else 0


def build_packet(
    items: list[RulingItem], origin: Origin, cap: int = DEFAULT_CAP
) -> RulingPacket:
    """Order, cap and budget items into a packet.

    Probes precede findings; each kind keeps its input order. The first `cap`
    items are considered, the rest are dropped from this packet. Each SVG is
    sanitized; an SVG that is unsafe, or over the per-item cap, moves its item
    to `sheet_only`. If the packet's SVG total still exceeds the packet cap,
    items with SVGs are moved to `sheet_only` from the end.

    Raises:
        PacketError: An item's id does not match its feature and subject, or
            its `show` carries a verdict-side key.
    """
    for item in items:
        _validate_item(item)

    ordered = [it for it in items if it.is_probe] + [
        it for it in items if not it.is_probe
    ]
    ordered = ordered[:cap]

    moved: set[str] = set()
    kept: list[RulingItem] = []
    for item in ordered:
        svg = item.show.get("image_svg")
        if isinstance(svg, str):
            try:
                clean = sanitize_svg(svg)
            except SvgRejected:
                moved.add(item.item_id)
                continue
            if len(clean.encode("utf-8")) > SVG_ITEM_CAP_BYTES:
                moved.add(item.item_id)
                continue
            item = replace(item, show={**item.show, "image_svg": clean})
        kept.append(item)

    total = sum(_svg_bytes(it) for it in kept)
    idx = len(kept) - 1
    while total > SVG_PACKET_CAP_BYTES and idx >= 0:
        if _svg_bytes(kept[idx]) > 0:
            dropped = kept.pop(idx)
            total -= _svg_bytes(dropped)
            moved.add(dropped.item_id)
        idx -= 1

    sheet_only = [it.item_id for it in ordered if it.item_id in moved]
    return RulingPacket(
        packet_id=f"pkt_{uuid.uuid4().hex[:16]}",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        origin=origin,
        items=kept,
        sheet_only=sheet_only,
    )


def load_packet(path: Path) -> RulingPacket:
    """Read a packet JSON file.

    Raises:
        PacketError: Unknown `packet_v`, or a document missing required fields.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot read packet {path}: {exc}") from exc

    version = data.get("packet_v")
    if version != PACKET_VERSION:
        raise PacketError(
            f"unsupported packet_v {version!r}; expected {PACKET_VERSION}"
        )
    try:
        return RulingPacket(
            packet_id=data["packet_id"],
            created_at=data["created_at"],
            origin=Origin(**data["origin"]),
            items=[RulingItem(**raw) for raw in data["items"]],
            sheet_only=list(data["sheet_only"]),
            packet_v=version,
        )
    except (KeyError, TypeError) as exc:
        raise PacketError(f"malformed packet {path}: {exc}") from exc


__all__ = [
    "DEFAULT_CAP",
    "FORBIDDEN_SHOW_KEYS",
    "PACKET_VERSION",
    "SVG_ITEM_CAP_BYTES",
    "SVG_PACKET_CAP_BYTES",
    "Origin",
    "PacketError",
    "RulingItem",
    "RulingPacket",
    "build_packet",
    "load_packet",
]
