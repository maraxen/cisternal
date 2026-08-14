#!/usr/bin/env python3
"""Emit a real cisternal telemetry event for a customization decision or a
Rust-migration pipeline stage.

This is the thing that makes "flows the telemetry through a pipeline" true
rather than aspirational: it does not invent a new telemetry format for this
skill, it calls cisternal's own `cisternal.telemetry` substrate — the same
event pipeline every other cisternal-family tool (bathos, contemplex,
xperiri, myxcel) already emits through. A decision or migration stage
recorded here lands in the same JSONL stream (`~/.cisternal/logs/` by
default, or wherever `CISTERNAL_LOG_DIR`/OTLP export points) as everything
else cisternal instruments, so it is queryable and auditable the same way.

Usage:
    # A decision-matrix verdict, once made:
    uv run python scripts/record_decision.py decision \\
        --option accept_dependency --target "httpx for the outbound HTTP client" \\
        --confidence 0.8 --note "actively maintained, MIT, small transitive closure"

    # A Rust-migration pipeline stage:
    uv run python scripts/record_decision.py migration-stage \\
        --stage scaffold --target "cisternal.export.write" \\
        --note "maturin mixed layout, abi3-py313 floor"

Exit code is always 0 (telemetry emission must never fail the caller's real
work) — check stderr for a warning if the pipeline could not be reached.
"""

from __future__ import annotations

import argparse
import sys

_VALID_OPTIONS = (
    "accept_dependency",
    "vendor",
    "cherry_pick",
    "reimplement",
    "derive_inspiration",
    "derive_lessons",
)
_VALID_STAGES = ("assess", "scaffold", "build", "parity_test", "cutover")


def _emit_one_shot(name: str, **fields) -> None:  # noqa: ANN003
    """Init the pipeline, emit one record, then shut down so it actually flushes.

    init_pipeline()'s consumer thread is a daemon thread: if this short-lived
    script's process exits right after emit() (a non-blocking enqueue), the
    thread can be killed before it ever dequeues and writes the event —
    verified live: a first version of this script without the shutdown()
    call produced a real telemetry event that silently never reached disk.
    shutdown_pipeline() drains the queue and joins the listener (bounded by
    its own timeout) before returning, so the event is durable before this
    process exits.
    """
    from cisternal.telemetry.context import _build_record
    from cisternal.telemetry.pipeline import get_pipeline, init_pipeline, shutdown_pipeline

    init_pipeline()
    pipeline = get_pipeline()
    if pipeline is None:
        print("[record_decision] telemetry pipeline unavailable; not recorded", file=sys.stderr)
        return

    record = _build_record(name, **fields)
    if record is not None:
        pipeline.emit(record)
    shutdown_pipeline()


def _record_decision(
    *, option: str, target: str, confidence: float, note: str | None
) -> None:
    _emit_one_shot(
        "customize_tools.decision",
        option=option,
        target=target,
        confidence=confidence,
        note=note or "",
    )


def _record_migration_stage(*, stage: str, target: str, note: str | None) -> None:
    _emit_one_shot(
        "customize_tools.migration_stage",
        stage=stage,
        target=target,
        note=note or "",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    decision = subparsers.add_parser("decision", help="Record a decision-matrix verdict.")
    decision.add_argument("--option", required=True, choices=_VALID_OPTIONS)
    decision.add_argument("--target", required=True, help="What was being decided about.")
    decision.add_argument("--confidence", type=float, required=True, help="0.0-1.0")
    decision.add_argument("--note", default=None, help="One-line rationale.")

    stage = subparsers.add_parser("migration-stage", help="Record a migration pipeline stage.")
    stage.add_argument("--stage", required=True, choices=_VALID_STAGES)
    stage.add_argument("--target", required=True, help="The module/surface being migrated.")
    stage.add_argument("--note", default=None, help="One-line detail.")

    args = parser.parse_args(argv)

    if args.command == "decision":
        if not 0.0 <= args.confidence <= 1.0:
            print("--confidence must be between 0.0 and 1.0", file=sys.stderr)
            return 2
        _record_decision(
            option=args.option,
            target=args.target,
            confidence=args.confidence,
            note=args.note,
        )
    else:
        _record_migration_stage(stage=args.stage, target=args.target, note=args.note)

    return 0


if __name__ == "__main__":
    sys.exit(main())
