"""Ruling adapter protocol and registry (spec §5.1).

An adapter owns one shadow feature family. It lists the open items in a store
and folds the owner's rulings back into that store. Adapters are discovered
through the `cisternal.ruling_adapters` entry-point group.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol, runtime_checkable

from cisternal.shadow.ruling.packet import RulingItem, RulingPacket

ADAPTER_GROUP = "cisternal.ruling_adapters"


@dataclass
class OwnerRuling:
    """One owner answer as read from a packet page.

    `answer` is `{"value": "<label>"}` for binary items or
    `{"tags": {"<tag>": "clear" | "mild"}}` for tag items (empty means fine).
    """

    item_id: str
    answer: dict
    rewrite: str | None
    viewer_id: str | None
    ruled_at: str
    doc_version: int | None
    source_path: str


@dataclass
class ImportReport:
    """Outcome of folding rulings back into a store."""

    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)
    not_written: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)


@runtime_checkable
class RulingAdapter(Protocol):
    """Contract every ruling adapter implements."""

    name: str
    # The kind of store this adapter reads, e.g. "cisternal_records" or
    # "maraxiom_rubric". Recorded as the packet origin's store_kind.
    store_kind: str

    def open_items(self, store: Path, limit: int) -> list[RulingItem]:
        """Return up to `limit` items still awaiting a ruling in `store`."""
        ...

    def import_rulings(
        self, rulings: list[OwnerRuling], packet: RulingPacket
    ) -> ImportReport:
        """Record `rulings` against the items of `packet` and report the outcome."""
        ...


def load_adapter(name: str) -> RulingAdapter:
    """Load a registered adapter by entry-point name.

    A class entry point is instantiated with no arguments.

    Raises:
        KeyError: No adapter with that name; the message lists the known names.
    """
    registered = {ep.name: ep for ep in entry_points(group=ADAPTER_GROUP)}
    if name not in registered:
        raise KeyError(f"unknown ruling adapter {name!r}; known: {sorted(registered)}")
    loaded = registered[name].load()
    return loaded() if isinstance(loaded, type) else loaded
