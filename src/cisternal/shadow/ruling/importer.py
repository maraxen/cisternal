"""Import owner rulings from a page export or an offline sheet (spec §5.4).

Two sources:
- Path A: a directory in ArtifactData `out_dir` layout, `<dir>/cisternal_rulings/*.json`.
- Path B: a `labels.json` sheet export, which needs `--confirm-owner`.
"""

from __future__ import annotations

import json
import socket
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from cisternal.shadow.resolution import ResolutionError, resolve_log_dir
from cisternal.shadow.ruling.adapters import ImportReport, OwnerRuling, RulingAdapter, load_adapter
from cisternal.shadow.ruling.packet import RulingPacket
from cisternal.shadow.ruling.records_adapter import (
    ADAPTER_NAME as RECORDS_ADAPTER_NAME,
    LABEL_SOURCE,
    STORE_KIND as RECORDS_STORE_KIND,
    RecordsAdapter,
    binary_label,
    item_index,
    packet_refusal,
)

PAGE_COLLECTION = "cisternal_rulings"


class ImportUsageError(ValueError):
    """Bad source, malformed document, or a missing required flag (exit 2)."""


def _records_dir_or_resolve(records_dir: Path | None) -> Path:
    """The records directory: the explicit argument, else resolved from config.

    Raises:
        ResolutionError: No argument and no configured log_dir.
    """
    if records_dir is not None:
        return Path(records_dir)
    return resolve_log_dir(cli_arg=None).path


def _refuse_all(
    report: ImportReport, rulings: list[OwnerRuling], packet: RulingPacket, reason: str
) -> ImportReport:
    """Refuse every ruling with one reason; every item stays open."""
    for ruling in rulings:
        report.refused[ruling.item_id] = reason
    report.still_open = [item.item_id for item in [*packet.items, *packet.sheet_items]]
    return report


def _merge_into(report: ImportReport, sub: ImportReport) -> None:
    report.imported.extend(sub.imported)
    report.skipped.extend(sub.skipped)
    report.refused.update(sub.refused)
    report.not_written.extend(sub.not_written)


def _version_of(raw: dict[str, Any], data: dict[str, Any]) -> int | None:
    version = raw.get("version", data.get("version"))
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version


def _ruling_from_fields(
    data: dict[str, Any],
    *,
    doc_version: int | None,
    source_path: str,
    packet_id: str | None,
) -> OwnerRuling:
    if not isinstance(data.get("item_id"), str) or not isinstance(data.get("answer"), dict):
        raise ImportUsageError(f"malformed ruling document {source_path}: needs item_id and answer")
    return OwnerRuling(
        item_id=data["item_id"],
        answer=data["answer"],
        rewrite=data.get("rewrite"),
        viewer_id=data.get("viewer_id"),
        ruled_at=str(data.get("ruled_at", "")),
        doc_version=doc_version,
        source_path=source_path,
        packet_id=packet_id,
    )


def _read_page(source: Path) -> list[tuple[str | None, OwnerRuling]]:
    docs_dir = source / PAGE_COLLECTION
    if not docs_dir.is_dir():
        return []
    entries: list[tuple[str | None, OwnerRuling]] = []
    for path in sorted(docs_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportUsageError(f"cannot read ruling document {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ImportUsageError(f"malformed ruling document {path}: not an object")
        # ArtifactData may nest the fields under "data"; accept both shapes.
        data = raw["data"] if isinstance(raw.get("data"), dict) else raw
        packet_id = data.get("packet_id")
        packet_id = packet_id if isinstance(packet_id, str) else None
        ruling = _ruling_from_fields(
            data,
            doc_version=_version_of(raw, data),
            source_path=str(path),
            packet_id=packet_id,
        )
        entries.append((packet_id, ruling))
    return entries


def _read_sheet(source: Path) -> list[tuple[str | None, OwnerRuling]]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportUsageError(f"cannot read labels file {source}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rulings"), list):
        raise ImportUsageError(f"labels file {source} needs a 'rulings' list")
    packet_id = payload.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id:
        raise ImportUsageError(f"labels file {source} needs a top-level string packet_id")
    entries: list[tuple[str | None, OwnerRuling]] = []
    for raw in payload["rulings"]:
        if not isinstance(raw, dict):
            raise ImportUsageError(f"malformed sheet ruling in {source}: not an object")
        doc_version = raw.get("doc_version")
        ruling = _ruling_from_fields(
            raw,
            doc_version=doc_version if isinstance(doc_version, int) else None,
            source_path=str(raw.get("source_path") or "sheet"),
            packet_id=packet_id,
        )
        entries.append((packet_id, ruling))
    return entries


def _read_with_packets(
    source: Path,
) -> tuple[list[tuple[str | None, OwnerRuling]], Literal["page", "sheet"]]:
    if source.is_dir():
        return _read_page(source), "page"
    if source.is_file():
        return _read_sheet(source), "sheet"
    raise ImportUsageError(f"no such ruling source: {source}")


def read_rulings(source: Path) -> tuple[list[OwnerRuling], Literal["page", "sheet"]]:
    """Read rulings from a page export directory or a sheet `labels.json` file.

    Raises:
        ImportUsageError: The source is missing or a document is malformed.
    """
    entries, mode = _read_with_packets(Path(source))
    return [ruling for _pid, ruling in entries], mode


def _origin_matches(packet: RulingPacket, store: Path) -> bool:
    origin = packet.origin
    return origin.host == socket.gethostname() and Path(origin.store_path).resolve() == store.resolve()


def _write_labels_file(
    labels_out: Path,
    rulings: list[OwnerRuling],
    packet: RulingPacket,
    report: ImportReport,
    page_url: str | None,
) -> ImportReport:
    """Write a standalone labels JSONL for the scorer; no store is consulted."""
    items = item_index(packet)
    lines: list[str] = []
    for ruling in rulings:
        item = items.get(ruling.item_id)
        if item is None:
            report.refused[ruling.item_id] = "unknown_item"
            continue
        label, reason = binary_label(ruling, item)
        if reason is not None:
            report.refused[ruling.item_id] = reason
            continue
        fields = {
            "feature": item.feature,
            "subject_key": item.subject_key,
            "label": label,
            "label_source": LABEL_SOURCE,
            "labeller": ruling.viewer_id or "owner",
            "ruling_page": page_url or ruling.source_path,
            "source_path": ruling.source_path,
            "ruling_doc_version": ruling.doc_version,
            "packet_id": ruling.packet_id,
            "inputs_sha256": item.inputs_sha256,
            "ruled_at": ruling.ruled_at,
            "owner_rewrite": ruling.rewrite,
            "import_id": uuid.uuid4().hex,
        }
        lines.append(json.dumps({"name": "shadow.label", "ts": time.time(), "fields": fields}))
        report.imported.append(ruling.item_id)
    labels_out.resolve().parent.mkdir(parents=True, exist_ok=True)
    labels_out.resolve().write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    report.still_open = [
        item.item_id
        for item in [*packet.items, *packet.sheet_items]
        if item.item_id not in {r.item_id for r in rulings}
    ]
    return report


def import_labels(
    source: Path,
    packet: RulingPacket,
    *,
    confirm_owner: bool,
    labels_out: Path | None,
    records_dir: Path | None,
    page_url: str | None = None,
) -> ImportReport:
    """Fold owner rulings from `source` into the store the packet came from.

    Args:
        source: Page export directory, or a sheet `labels.json`.
        packet: The packet the rulings answer.
        confirm_owner: Required for a sheet source (owner-typed `!` line).
        labels_out: Write a standalone labels JSONL instead of touching the store.
        records_dir: Records directory to write into; resolved from config when None.
        page_url: Published ruling page URL. Required for a page source, refused
            for a sheet source; becomes `ruling_page` on the written labels.

    Raises:
        ImportUsageError: Sheet without `confirm_owner`, a page without
            `page_url`, `page_url` on a sheet, or a malformed source.
        ResolutionError: The records directory cannot be resolved.
    """
    entries, mode = _read_with_packets(Path(source))
    if mode == "sheet" and not confirm_owner:
        raise ImportUsageError(
            "sheet import writes owner_confirmed labels; pass --confirm-owner"
        )
    if mode == "page" and not page_url:
        raise ImportUsageError(
            "page import needs --page-url <the published ruling page URL>"
        )
    if mode == "sheet" and page_url:
        raise ImportUsageError("--page-url applies to a page directory, not a sheet labels.json")

    report = ImportReport()
    rulings: list[OwnerRuling] = []
    for _packet_id, ruling in entries:
        reason = packet_refusal(ruling, packet)
        if reason is not None:
            report.refused[ruling.item_id] = reason
        else:
            rulings.append(ruling)

    if labels_out is not None:
        return _write_labels_file(Path(labels_out), rulings, packet, report, page_url)

    # The store follows the packet's origin (R23): a records packet writes into
    # the records directory; any other kind writes into its origin store path.
    is_records = packet.origin.store_kind == RECORDS_STORE_KIND
    if is_records:
        store = _records_dir_or_resolve(records_dir)
    else:
        store = Path(packet.origin.store_path)
        if not store.exists():
            return _refuse_all(report, rulings, packet, "store_missing")
    if not _origin_matches(packet, store):
        return _refuse_all(report, rulings, packet, "origin_mismatch")

    # Route each ruling to the adapter named by its item.
    index = item_index(packet)
    groups: dict[str, list[OwnerRuling]] = {}
    for ruling in rulings:
        item = index.get(ruling.item_id)
        if item is None:
            report.refused[ruling.item_id] = "unknown_item"
            continue
        groups.setdefault(item.adapter, []).append(ruling)

    routed: set[str] = set()
    for adapter_name, group in groups.items():
        if adapter_name == RECORDS_ADAPTER_NAME:
            # Resolved lazily: a non-records packet needs no records dir unless
            # one of its items is a records item.
            try:
                records_store = store if is_records else _records_dir_or_resolve(records_dir)
            except ResolutionError:
                for ruling in group:
                    report.refused[ruling.item_id] = "records_dir_unresolved"
                continue
            adapter: RulingAdapter = RecordsAdapter(records_dir=records_store)
        else:
            try:
                adapter = load_adapter(adapter_name)
            except KeyError:
                for ruling in group:
                    report.refused[ruling.item_id] = "unknown_adapter"
                continue
        routed.update(ruling.item_id for ruling in group)
        _merge_into(report, adapter.import_rulings(group, packet, page_url=page_url))

    report.still_open = [
        item.item_id
        for item in [*packet.items, *packet.sheet_items]
        if item.item_id not in routed
    ]
    return report


def report_dict(report: ImportReport) -> dict[str, Any]:
    """JSON-ready view of an import report."""
    return asdict(report)


__all__ = [
    "ImportUsageError",
    "import_labels",
    "read_rulings",
    "report_dict",
]
