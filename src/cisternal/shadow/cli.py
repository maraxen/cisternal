"""Cisternal shadow CLI commands (spec §3.2).

Provides:
- shadow score <feature>: Join and score verdicts against labels with Wilson CI.
- shadow packet: Write a ruling packet of open items from one shadow store.
- shadow page / shadow sheet: Render a ruling packet as an Artifact page or offline HTML sheet.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import cyclopts

from cisternal.shadow.mode_state import GateCheckError, check_mode_state
from cisternal.shadow.resolution import ResolutionError, resolve_log_dir
from cisternal.shadow.ruling.adapters import load_adapter
from cisternal.shadow.ruling.importer import ImportUsageError, import_labels, report_dict
from cisternal.shadow.ruling.packet import (
    DEFAULT_CAP,
    Origin,
    PacketError,
    build_packet,
    load_packet,
)
from cisternal.shadow.ruling.render import render
from cisternal.shadow.scoring import ScoringRefusalError, score_feature

shadow_app = cyclopts.App(
    name="shadow",
    help="Shadow-development lifecycle commands (score, check, packet).",
    version_flags=[],
)


@shadow_app.command(name="score")
def shadow_score(
    feature: str,
    *,
    records_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--records-dir"],
            help="Directory containing events.*.jsonl files.",
        ),
    ] = None,
    verdicts_file: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--verdicts-file"],
            help="Specific verdicts JSONL file override.",
        ),
    ] = None,
    labels_file: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--labels-file"],
            help="Specific labels JSONL file override.",
        ),
    ] = None,
    positive_label: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--positive-label"],
            help="Positive label definition (default: true).",
        ),
    ] = None,
    confidence: Annotated[
        float,
        cyclopts.Parameter(
            name=["--confidence"],
            help="Confidence level for Wilson intervals (default: 0.95).",
        ),
    ] = 0.95,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON report.",
        ),
    ] = False,
) -> None:
    """Score shadow verdicts against ground truth labels."""
    if confidence <= 0.0 or confidence >= 1.0:
        print(f"Error: confidence must be strictly between 0.0 and 1.0, got {confidence}", file=sys.stderr)
        raise SystemExit(2)

    resolved_pos: Any = True
    if positive_label is not None:
        low = positive_label.strip().lower()
        if low in ("true", "1", "yes", "pass", "clean"):
            resolved_pos = True
        elif low in ("false", "0", "no", "fail", "drifted"):
            resolved_pos = False
        else:
            resolved_pos = positive_label

    effective_records_dir = records_dir
    if records_dir is None and verdicts_file is None and labels_file is None:
        try:
            res_log = resolve_log_dir(cli_arg=None)
        except ResolutionError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(exc.exit_code) from exc
        effective_records_dir = res_log.path
        # `provenance` already reads "resolved log_dir from ...": print it once.
        print(res_log.provenance, file=sys.stderr)
    elif records_dir is not None:
        print(f"resolved log_dir from CLI argument ({records_dir})", file=sys.stderr)

    try:
        result = score_feature(
            feature=feature,
            records_dir=effective_records_dir,
            verdicts_file=verdicts_file,
            labels_file=labels_file,
            positive_label=resolved_pos,
            confidence=confidence,
        )
    except (ScoringRefusalError, ResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc

    if json_output:
        print(json.dumps(result.to_dict(), indent=2))
        return

    # Text report
    prec_str = (
        f"{result.precision:.4f} [Wilson {confidence*100:.0f}% CI: {result.precision_ci_lower:.4f} .. {result.precision_ci_upper:.4f}]"
        if result.precision is not None and result.precision_ci_lower is not None and result.precision_ci_upper is not None
        else "n/a (no positive predictions)"
    )
    rec_str = (
        f"{result.recall:.4f} [Wilson {confidence*100:.0f}% CI: {result.recall_ci_lower:.4f} .. {result.recall_ci_upper:.4f}]"
        if result.recall is not None and result.recall_ci_lower is not None and result.recall_ci_upper is not None
        else "n/a (no positive labels)"
    )
    fpr_str = f"{result.fp_rate:.4f}" if result.fp_rate is not None else "n/a (no negative labels)"
    exceeds_str = (
        "Yes" if result.precision_exceeds_base_rate is True
        else ("No" if result.precision_exceeds_base_rate is False else "n/a")
    )

    print(f"Feature: {result.feature}")
    print(f"  Verdicts Total:      {result.verdicts_total} (Unlabelled: {result.unlabelled_verdicts})")
    print(f"  Labels Total:        {result.labels_total} (Invalid Records: {result.invalid_records}, Malformed Lines: {result.malformed_lines})")
    print(f"  Confusion Matrix:    TP={result.tp}, FP={result.fp}, TN={result.tn}, FN={result.fn}")
    print(f"  Base Rate:           {result.base_rate:.4f}")
    print(f"  Precision:           {prec_str}")
    print(f"  Recall:              {rec_str}")
    print(f"  False Positive Rate: {fpr_str}")
    print(f"  Precision > BaseRate: {exceeds_str}")


@shadow_app.command(name="check")
def shadow_check(
    feature_or_path: str,
    *,
    records_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--records-dir"],
            help="Directory containing events.*.jsonl files.",
        ),
    ] = None,
    verdicts_file: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--verdicts-file"],
            help="Specific verdicts JSONL file override.",
        ),
    ] = None,
    labels_file: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--labels-file"],
            help="Specific labels JSONL file override.",
        ),
    ] = None,
    mode_state_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--mode-state-dir"],
            help="Directory containing mode-state TOML files.",
        ),
    ] = None,
    confidence: Annotated[
        float,
        cyclopts.Parameter(
            name=["--confidence"],
            help="Confidence level for Wilson intervals (default: 0.95).",
        ),
    ] = 0.95,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON report.",
        ),
    ] = False,
) -> None:
    """Evaluate promotion readiness of a shadow feature (read-only)."""
    if confidence <= 0.0 or confidence >= 1.0:
        print(f"Error: confidence must be strictly between 0.0 and 1.0, got {confidence}", file=sys.stderr)
        raise SystemExit(2)

    try:
        result = check_mode_state(
            feature_or_path=feature_or_path,
            records_dir=records_dir,
            verdicts_file=verdicts_file,
            labels_file=labels_file,
            mode_state_dir=mode_state_dir,
            confidence=confidence,
        )
    except (GateCheckError, ResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc
    except (TypeError, ValueError) as exc:
        # Unexpected configuration shape must never surface as a traceback.
        print(f"Mode-state configuration error: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc

    if result.log_dir_provenance:
        print(result.log_dir_provenance, file=sys.stderr)

    if json_output:
        print(json.dumps(result.to_dict(), indent=2))
        raise SystemExit(result.exit_code)

    # Human-readable report
    status_str = "PERMITTED" if result.promotion_permitted else "BLOCKED"
    print(f"Feature: {result.feature} (Stage: {result.current_stage} -> Target: {result.target_stage})")
    print(f"  Promotion Status: {status_str} (Exit Code: {result.exit_code})")
    if result.blocking_reasons:
        print("  Blocking Reasons:")
        for reason in result.blocking_reasons:
            print(f"    - {reason}")
    else:
        print("  Blocking Reasons: none")

    m = result.metrics
    print("  Metrics:")
    print(f"    Verdicts Total: {m.get('verdicts_total')} | Labels Total: {m.get('labels_total')}")
    print(f"    Confusion Matrix: TP={m.get('tp')}, FP={m.get('fp')}, TN={m.get('tn')}, FN={m.get('fn')}")
    print(f"    Base Rate: {m.get('base_rate')}")
    print(f"    Precision: {m.get('precision')} [CI: {m.get('precision_ci_lower')} .. {m.get('precision_ci_upper')}]")
    print(f"    Recall:    {m.get('recall')} [CI: {m.get('recall_ci_lower')} .. {m.get('recall_ci_upper')}]")
    print(f"    FP Rate:   {m.get('fp_rate')}")
    print(f"    Isolation Violations: {m.get('isolation_violations')}")
    print(f"    Invalid Records: {m.get('invalid_records')} | Malformed Lines: {m.get('malformed_lines')}")

    raise SystemExit(result.exit_code)


@shadow_app.command(name="packet")
def shadow_packet(
    *,
    adapter: Annotated[
        str,
        cyclopts.Parameter(
            name=["--adapter"],
            help="Ruling adapter name (cisternal.ruling_adapters entry point).",
        ),
    ],
    store: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--store"],
            help="Shadow store the adapter reads open items from.",
        ),
    ],
    limit: Annotated[
        int,
        cyclopts.Parameter(
            name=["--limit"],
            help="Maximum items to consider for one packet (default: 40).",
        ),
    ] = DEFAULT_CAP,
    out: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--out"],
            help="Path to write the packet JSON (default: ruling_packet.json).",
        ),
    ] = Path("ruling_packet.json"),
    session_id: Annotated[
        str,
        cyclopts.Parameter(name=["--session-id"], help="Session that built the packet."),
    ],
    task_id: Annotated[
        str,
        cyclopts.Parameter(name=["--task-id"], help="Task id (YYMMDD_slug)."),
    ],
) -> None:
    """Write a ruling packet of open items from one shadow store."""
    try:
        ruling_adapter = load_adapter(adapter)
    except KeyError as exc:
        print(str(exc.args[0]) if exc.args else str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    store_path = store.resolve()
    raw_items = ruling_adapter.open_items(store_path, limit)
    if not raw_items:
        print(json.dumps({"packet": None, "message": "nothing to rule"}, indent=2))
        return

    origin = Origin(
        host=socket.gethostname(),
        store_kind=ruling_adapter.store_kind,
        store_path=str(store_path),
        session_id=session_id,
        task_id=task_id,
    )
    packet = build_packet(raw_items, origin, cap=limit)
    out_path = out.resolve()
    out_path.write_text(packet.to_json() + "\n", encoding="utf-8")

    summary = {
        "packet": str(out_path),
        "items": len(packet.items),
        "probes": sum(1 for it in packet.items if it.is_probe),
        "sheet_only": len(packet.sheet_only),
    }
    print(json.dumps(summary, indent=2))


def _write_ruling_html(packet_path: Path, out: Path, mode: Literal["page", "sheet"]) -> None:
    try:
        packet = load_packet(packet_path)
    except PacketError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    out_path = out.resolve()
    out_path.write_text(render(packet, mode), encoding="utf-8")
    summary = {
        "mode": mode,
        "html": str(out_path),
        "items": len(packet.items),
        "sheet_only": len(packet.sheet_only),
    }
    print(json.dumps(summary, indent=2))


@shadow_app.command(name="page")
def shadow_page(
    *,
    packet: Annotated[
        Path,
        cyclopts.Parameter(name=["--packet"], help="Ruling packet JSON written by `shadow packet`."),
    ],
    out: Annotated[
        Path,
        cyclopts.Parameter(name=["--out"], help="Path to write the ruling page HTML (default: ruling_page.html)."),
    ] = Path("ruling_page.html"),
) -> None:
    """Write the owner ruling page (Path A) for a packet, to publish as an Artifact."""
    _write_ruling_html(packet, out, "page")


@shadow_app.command(name="sheet")
def shadow_sheet(
    *,
    packet: Annotated[
        Path,
        cyclopts.Parameter(name=["--packet"], help="Ruling packet JSON written by `shadow packet`."),
    ],
    out: Annotated[
        Path,
        cyclopts.Parameter(name=["--out"], help="Path to write the offline sheet HTML (default: ruling_sheet.html)."),
    ] = Path("ruling_sheet.html"),
) -> None:
    """Write the offline ruling sheet (Path B) for a packet; no capabilities."""
    _write_ruling_html(packet, out, "sheet")


@shadow_app.command(name="import-labels")
def shadow_import_labels(
    source: Path,
    *,
    packet: Annotated[
        Path,
        cyclopts.Parameter(name=["--packet"], help="Ruling packet JSON the rulings answer."),
    ],
    confirm_owner: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--confirm-owner"],
            help="Required for a sheet (labels.json) source: the owner confirms the import.",
        ),
    ] = False,
    labels_out: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--labels-out"],
            help="Write a standalone labels JSONL instead of writing into the store.",
        ),
    ] = None,
    records_dir: Annotated[
        Path | None,
        cyclopts.Parameter(name=["--records-dir"], help="Records directory to write into."),
    ] = None,
    page_url: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--page-url"],
            help="Published ruling page URL. Required for a page directory; refused for a sheet.",
        ),
    ] = None,
) -> None:
    """Import owner rulings from a page export directory or a sheet labels file."""
    try:
        packet_obj = load_packet(packet)
    except PacketError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    effective_records_dir = records_dir
    # Only a records-kind packet writes into the records directory (R23); other
    # stores are read from the packet's own origin path, so no log_dir is needed.
    if labels_out is None and packet_obj.origin.store_kind == "cisternal_records":
        try:
            if records_dir is None:
                res_log = resolve_log_dir(cli_arg=None)
                effective_records_dir = res_log.path
                print(res_log.provenance, file=sys.stderr)
            else:
                print(f"resolved log_dir from CLI argument ({records_dir})", file=sys.stderr)
        except ResolutionError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(exc.exit_code) from exc

    try:
        report = import_labels(
            source,
            packet_obj,
            confirm_owner=confirm_owner,
            labels_out=labels_out,
            records_dir=effective_records_dir,
            page_url=page_url,
        )
    except ImportUsageError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    except ResolutionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc

    print(json.dumps(report_dict(report), indent=2))
    raise SystemExit(1 if report.refused or report.not_written else 0)
