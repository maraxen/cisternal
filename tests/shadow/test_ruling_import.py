"""Tests for `cisternal shadow import-labels` and the cisternal.records adapter (Task 5).

Covers: origin refusal (and the --labels-out escape), changed-subject refusal,
version idempotence and supersession, the sheet --confirm-owner gate, read-back
after drain (not_written), the --page-url requirement (R15), and the evidence
fields carried on written labels (ruling_page = URL, source_path = file).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

import cisternal.shadow.ruling.adapters as adapters_mod
import cisternal.shadow.ruling.records_adapter as records_mod
from cisternal.cli import app
from cisternal.shadow.ruling.importer import import_labels, read_rulings
from cisternal.shadow.ruling.packet import Origin, RulingItem, RulingPacket
from cisternal.shadow.ruling.records_adapter import RecordsAdapter

PACKET_ID = "pkt_0123456789abcdef"
ZERO = "0" * 64
CURRENT = "f" * 64
PAGE_URL = "https://claude.ai/artifact/test-ruling-page"


def _item(key: str = "k1", *, sha: str = ZERO) -> RulingItem:
    return RulingItem(
        item_id=f"feat|{key}",
        feature="feat",
        subject_key=key,
        is_probe=False,
        inputs_sha256=sha,
        answer={"kind": "binary", "positive": "present", "negative": "absent"},
        show={"text": f"text {key}"},
        adapter="cisternal.records",
    )


def _packet(records_dir: Path, *, host: str | None = None, items: list[RulingItem] | None = None) -> RulingPacket:
    return RulingPacket(
        packet_id=PACKET_ID,
        created_at="2026-11-24T00:00:00+00:00",
        origin=Origin(
            host=host or socket.gethostname(),
            store_kind="cisternal_records",
            store_path=str(records_dir.resolve()),
            session_id="sess-1",
            task_id="261124_shadow-ruling-ui",
        ),
        items=items if items is not None else [_item()],
        sheet_only=[],
        sheet_items=[],
    )


def _write_verdict(records_dir: Path, key: str, sha: str, ts: float = 1.0) -> None:
    records_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "name": "shadow.verdict",
        "ts": ts,
        "fields": {
            "feature": "feat",
            "subject_key": key,
            "verdict": True,
            "inputs_sha256": sha,
        },
    }
    with (records_dir / "events.verdict.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def _write_page_doc(
    source: Path,
    doc_id: str,
    *,
    item_id: str = "feat|k1",
    value: str = "present",
    version: int | None = 1,
    packet_id: str = PACKET_ID,
    nested: bool = False,
) -> None:
    target = source / "cisternal_rulings"
    target.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "item_id": item_id,
        "packet_id": packet_id,
        "answer": {"value": value},
        "rewrite": None,
        "viewer_id": "viewer-1",
        "ruled_at": "2026-11-24T10:00:00+00:00",
    }
    if nested:
        payload: dict[str, Any] = {"data": doc}
        if version is not None:
            payload["version"] = version
    else:
        payload = {**doc}
        if version is not None:
            payload["version"] = version
    (target / f"{doc_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _labels(records_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(records_dir.glob("events.*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("name") == "shadow.label":
                out.append(rec.get("fields", rec))
    return out


@pytest.fixture(autouse=True)
def _no_pipeline_leak() -> Any:
    from cisternal.telemetry.pipeline import shutdown_pipeline

    shutdown_pipeline()
    yield
    shutdown_pipeline()


def _run_cli(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exit_info:
        app(["shadow", "import-labels", *argv])
    return int(exit_info.value.code or 0)


def test_import_refuses_origin_mismatch(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", CURRENT)
    packet = _packet(records, host="engaging-login")
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)

    report = import_labels(
        source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )

    assert report.refused == {"feat|k1": "origin_mismatch"}
    assert report.imported == []
    assert _labels(records) == []


def test_origin_mismatch_exits_1_from_cli(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", CURRENT)
    packet_path = tmp_path / "ruling_packet.json"
    packet_path.write_text(_packet(records, host="engaging-login").to_json(), encoding="utf-8")
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)

    code = _run_cli(
        [
            "--packet", str(packet_path), str(source),
            "--records-dir", str(records), "--page-url", PAGE_URL,
        ]
    )
    assert code == 1


def test_origin_mismatch_with_labels_out_writes_standalone_file(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    packet = _packet(records, host="engaging-login")
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)
    labels_out = tmp_path / "labels.jsonl"

    report = import_labels(
        source,
        packet,
        confirm_owner=False,
        labels_out=labels_out,
        records_dir=records,
        page_url=PAGE_URL,
    )

    assert report.refused == {}
    assert report.imported == ["feat|k1"]
    lines = [json.loads(x) for x in labels_out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["fields"]["label"] is True
    assert lines[0]["fields"]["packet_id"] == PACKET_ID
    assert lines[0]["fields"]["ruling_page"] == PAGE_URL
    assert not records.exists() or _labels(records) == []


def test_import_refuses_changed_subject(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", CURRENT)
    packet = _packet(records)
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)

    report = import_labels(
        source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )

    assert report.refused == {"feat|k1": "subject_changed"}
    assert _labels(records) == []


def test_import_version_idempotent_and_supersedes(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet = _packet(records)
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=2)

    first = import_labels(
        source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )
    assert first.imported == ["feat|k1"]

    second = import_labels(
        source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )
    assert second.skipped == ["feat|k1"]
    assert second.imported == []
    assert len(_labels(records)) == 1

    newer_source = tmp_path / "page2"
    _write_page_doc(newer_source, "doc1", value="absent", version=3)
    third = import_labels(
        newer_source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )
    assert third.imported == ["feat|k1"]
    labels = _labels(records)
    assert len(labels) == 2
    assert {lab["ruling_doc_version"] for lab in labels} == {2, 3}


def test_sheet_import_requires_confirm_owner(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet_path = tmp_path / "ruling_packet.json"
    packet_path.write_text(_packet(records).to_json(), encoding="utf-8")
    sheet = tmp_path / "labels.json"
    sheet.write_text(
        json.dumps(
            {
                "packet_id": PACKET_ID,
                "rulings": [
                    {
                        "item_id": "feat|k1",
                        "answer": {"value": "present"},
                        "rewrite": None,
                        "viewer_id": None,
                        "ruled_at": "2026-11-24T10:00:00+00:00",
                        "doc_version": None,
                        "source_path": "sheet",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = _run_cli(
        ["--packet", str(packet_path), str(sheet), "--records-dir", str(records)]
    )
    assert code == 2
    assert _labels(records) == []


def test_sheet_import_with_confirm_owner_imports(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet_path = tmp_path / "ruling_packet.json"
    packet_path.write_text(_packet(records).to_json(), encoding="utf-8")
    sheet = tmp_path / "labels.json"
    sheet.write_text(
        json.dumps(
            {
                "packet_id": PACKET_ID,
                "rulings": [
                    {
                        "item_id": "feat|k1",
                        "answer": {"value": "absent"},
                        "rewrite": None,
                        "viewer_id": None,
                        "ruled_at": "2026-11-24T10:00:00+00:00",
                        "doc_version": None,
                        "source_path": "sheet",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = _run_cli(
        [
            "--packet", str(packet_path), str(sheet),
            "--records-dir", str(records), "--confirm-owner",
        ]
    )
    assert code == 0
    labels = _labels(records)
    assert len(labels) == 1
    assert labels[0]["label"] is False


def test_import_reads_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet = _packet(records)
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)

    # Simulate an enqueued label that the store never keeps: emit reports success,
    # nothing is written, so read-back after drain must find nothing.
    monkeypatch.setattr(records_mod, "emit_label", lambda *a, **k: True)

    report = import_labels(
        source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )
    assert report.not_written == ["feat|k1"]
    assert report.imported == []


def test_import_not_written_exits_1_from_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet_path = tmp_path / "ruling_packet.json"
    packet_path.write_text(_packet(records).to_json(), encoding="utf-8")
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)
    monkeypatch.setattr(records_mod, "emit_label", lambda *a, **k: True)

    code = _run_cli(
        [
            "--packet", str(packet_path), str(source),
            "--records-dir", str(records), "--page-url", PAGE_URL,
        ]
    )
    assert code == 1


def test_page_import_without_page_url_exits_2(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet_path = tmp_path / "ruling_packet.json"
    packet_path.write_text(_packet(records).to_json(), encoding="utf-8")
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", version=1)

    code = _run_cli(
        ["--packet", str(packet_path), str(source), "--records-dir", str(records)]
    )
    assert code == 2
    assert _labels(records) == []


def test_sheet_import_with_page_url_exits_2(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet_path = tmp_path / "ruling_packet.json"
    packet_path.write_text(_packet(records).to_json(), encoding="utf-8")
    sheet = tmp_path / "labels.json"
    sheet.write_text(
        json.dumps({"packet_id": PACKET_ID, "rulings": []}), encoding="utf-8"
    )

    code = _run_cli(
        [
            "--packet", str(packet_path), str(sheet), "--records-dir", str(records),
            "--confirm-owner", "--page-url", PAGE_URL,
        ]
    )
    assert code == 2


def test_page_import_carries_evidence(tmp_path: Path) -> None:
    records = tmp_path / "logs"
    _write_verdict(records, "k1", ZERO)
    packet = _packet(records)
    source = tmp_path / "page"
    _write_page_doc(source, "doc1", value="present", version=4, nested=True)

    report = import_labels(
        source, packet, confirm_owner=False, labels_out=None, records_dir=records,
        page_url=PAGE_URL,
    )
    assert report.imported == ["feat|k1"]

    labels = _labels(records)
    assert len(labels) == 1
    label = labels[0]
    assert label["label_source"] == "owner_confirmed"
    assert label["label"] is True
    assert label["packet_id"] == PACKET_ID
    assert label["ruling_doc_version"] == 4
    assert label["ruling_page"] == PAGE_URL
    assert label["source_path"] == str(source / "cisternal_rulings" / "doc1.json")
    assert label["labeller"] == "viewer-1"


def test_read_rulings_accepts_flat_and_nested_documents(tmp_path: Path) -> None:
    source = tmp_path / "page"
    _write_page_doc(source, "flat", item_id="feat|a", version=5)
    _write_page_doc(source, "nested", item_id="feat|b", version=6, nested=True)

    rulings, mode = read_rulings(source)

    assert mode == "page"
    by_id = {r.item_id: r for r in rulings}
    assert by_id["feat|a"].doc_version == 5
    assert by_id["feat|b"].doc_version == 6
    assert by_id["feat|b"].answer == {"value": "present"}


def test_records_adapter_registered_under_entry_point_name(monkeypatch: pytest.MonkeyPatch) -> None:
    class _EP:
        name = "cisternal.records"

        def load(self) -> type[RecordsAdapter]:
            return RecordsAdapter

    monkeypatch.setattr(
        adapters_mod,
        "entry_points",
        lambda group: [_EP()] if group == adapters_mod.ADAPTER_GROUP else [],
    )
    adapter = adapters_mod.load_adapter("cisternal.records")
    assert isinstance(adapter, RecordsAdapter)
    assert adapter.name == "cisternal.records"
    assert adapter.store_kind == "cisternal_records"
