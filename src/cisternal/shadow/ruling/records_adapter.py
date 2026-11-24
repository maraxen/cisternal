"""Built-in ruling adapter for cisternal shadow records (spec §5.4).

Binary owner rulings become `shadow.label` records with
`label_source="owner_confirmed"`, written through the telemetry pipeline. An
import is confirmed only after the pipeline is drained and the label is found
again by reading the records directory back (spec A12).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from cisternal.shadow.events import emit_label
from cisternal.shadow.ruling.adapters import ImportReport, OwnerRuling
from cisternal.shadow.ruling.packet import RulingItem, RulingPacket
from cisternal.shadow.scoring import LABEL_NAME, VERDICT_NAME, _unwrap_record, gather_files
from cisternal.telemetry.pipeline import init_pipeline, shutdown_pipeline

ADAPTER_NAME = "cisternal.records"
STORE_KIND = "cisternal_records"
LABEL_SOURCE = "owner_confirmed"

Key = tuple[str, str]


def item_index(packet: RulingPacket) -> dict[str, RulingItem]:
    """Items a ruling may target: the page items and the sheet-only items."""
    index: dict[str, RulingItem] = {}
    for item in [*packet.items, *packet.sheet_items]:
        index.setdefault(item.item_id, item)
    return index


def binary_label(ruling: OwnerRuling, item: RulingItem) -> tuple[bool | None, str | None]:
    """Map a ruling onto a binary label.

    Returns:
        (label, None) on success, or (None, reason) when the ruling cannot be
        written as a binary label. Tag items and tag answers are refused here.
    """
    if item.answer.get("kind") != "binary" or "tags" in ruling.answer:
        return None, "unsupported_answer_kind"
    value = ruling.answer.get("value")
    positive = item.answer.get("positive")
    negative = item.answer.get("negative")
    if value not in (positive, negative):
        return None, "bad_answer"
    return value == positive, None


def _scan(records_dir: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (name, fields) for every parseable record, using the scorer's unwrap."""
    for path in gather_files(records_dir):
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                name, _ts, fields = _unwrap_record(record)
                yield name, fields


def current_verdict_hashes(records_dir: Path) -> dict[Key, str]:
    """Latest `inputs_sha256` per (feature, subject_key) among shadow.verdict records."""
    latest: dict[Key, tuple[float, str]] = {}
    for path in gather_files(records_dir):
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                name, ts, fields = _unwrap_record(record)
                if name != VERDICT_NAME:
                    continue
                key = (str(fields.get("feature", "")), str(fields.get("subject_key", "")))
                sha = str(fields.get("inputs_sha256") or "")
                if key not in latest or ts >= latest[key][0]:
                    latest[key] = (ts, sha)
    return {key: sha for key, (_ts, sha) in latest.items()}


def _owner_labels(records_dir: Path, packet_id: str) -> Iterator[dict[str, Any]]:
    for name, fields in _scan(records_dir):
        if (
            name == LABEL_NAME
            and fields.get("label_source") == LABEL_SOURCE
            and fields.get("packet_id") == packet_id
        ):
            yield fields


def existing_owner_versions(records_dir: Path, packet_id: str) -> dict[Key, list[int | None]]:
    """Document versions already imported for this packet, per (feature, subject_key)."""
    seen: dict[Key, list[int | None]] = {}
    for fields in _owner_labels(records_dir, packet_id):
        key = (str(fields.get("feature", "")), str(fields.get("subject_key", "")))
        version = fields.get("ruling_doc_version")
        seen.setdefault(key, []).append(version if isinstance(version, int) else None)
    return seen


def _already_imported(versions: list[int | None] | None, doc_version: int | None) -> bool:
    """Skip when this version is not newer than one already imported."""
    if versions is None:
        return False
    if doc_version is None:
        return True
    return any(v is not None and doc_version <= v for v in versions)


class RecordsAdapter:
    """Ruling adapter for cisternal shadow records in one records directory."""

    name = ADAPTER_NAME
    store_kind = STORE_KIND

    def __init__(self, records_dir: Path | None = None) -> None:
        self.records_dir = Path(records_dir).resolve() if records_dir is not None else None

    def open_items(self, store: Path, limit: int) -> list[RulingItem]:
        """Not implemented: packets for cisternal records are not built yet."""
        raise NotImplementedError("cisternal.records does not build packets yet")

    def import_rulings(
        self,
        rulings: list[OwnerRuling],
        packet: RulingPacket,
        *,
        page_url: str | None = None,
    ) -> ImportReport:
        """Write binary rulings as owner_confirmed labels and report what reads back.

        `page_url` is the published ruling page; it becomes `ruling_page`. The
        file the ruling came from is kept as `source_path`.
        """
        if self.records_dir is None:
            raise ValueError("RecordsAdapter needs a records_dir to import rulings")
        records_dir = self.records_dir
        report = ImportReport()
        items = item_index(packet)
        verdicts = current_verdict_hashes(records_dir)
        existing = existing_owner_versions(records_dir, packet.packet_id)

        pending: list[tuple[str, Key, str]] = []
        ruled: set[str] = set()
        for ruling in rulings:
            item = items.get(ruling.item_id)
            if item is None:
                report.refused[ruling.item_id] = "unknown_item"
                continue
            ruled.add(ruling.item_id)
            label, reason = binary_label(ruling, item)
            if reason is not None:
                report.refused[ruling.item_id] = reason
                continue
            key = (item.feature, item.subject_key)
            if verdicts.get(key) != item.inputs_sha256:
                reason = "subject_changed" if key in verdicts else "no_current_verdict"
                report.refused[ruling.item_id] = reason
                continue
            if _already_imported(existing.get(key), ruling.doc_version):
                report.skipped.append(ruling.item_id)
                continue
            import_id = uuid.uuid4().hex
            pending.append((ruling.item_id, key, import_id))
            init_pipeline(log_dir=records_dir)
            queued = emit_label(
                item.feature,
                item.subject_key,
                label,
                label_source=LABEL_SOURCE,
                labeller=ruling.viewer_id or "owner",
                ruling_page=page_url or ruling.source_path,
                source_path=ruling.source_path,
                ruling_doc_version=ruling.doc_version,
                packet_id=packet.packet_id,
                inputs_sha256=item.inputs_sha256,
                ruled_at=ruling.ruled_at,
                owner_rewrite=ruling.rewrite,
                import_id=import_id,
            )
            if not queued:
                pending.pop()
                report.not_written.append(ruling.item_id)

        shutdown_pipeline()
        written = {
            (str(f.get("import_id")), str(f.get("feature")), str(f.get("subject_key")))
            for _name, f in _scan(records_dir)
            if _name == LABEL_NAME
            and f.get("label_source") == LABEL_SOURCE
            and f.get("packet_id") == packet.packet_id
        }
        for item_id, (feature, subject_key), import_id in pending:
            if (import_id, feature, subject_key) in written:
                report.imported.append(item_id)
            else:
                report.not_written.append(item_id)

        report.still_open = [
            item.item_id for item in [*packet.items, *packet.sheet_items] if item.item_id not in ruled
        ]
        return report


__all__ = [
    "ADAPTER_NAME",
    "LABEL_SOURCE",
    "STORE_KIND",
    "RecordsAdapter",
    "binary_label",
    "current_verdict_hashes",
    "existing_owner_versions",
    "item_index",
]
