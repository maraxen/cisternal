#!/usr/bin/env python3
"""Detect stale crate-version stamps in this skill's references/*.md files.

Each Rust-migration reference doc (references/pyo3.md, orx-parallel.md,
rayon.md, wasm.md, webgpu.md) opens with a machine-parseable comment:

    <!-- ref-crate-versions: pyo3=0.29.2; maturin=1.14.1; checked=2026-08-13 -->

This script re-fetches each named crate's current max_stable_version from
crates.io and reports any drift. It does NOT regenerate reference content —
that requires research (WebSearch/WebFetch) an unattended script cannot do
credibly. Its only job is the deterministic half: telling you WHICH
references need a fresh research pass, so that pass isn't guesswork or a
blind full re-run of all five.

Usage:
    uv run python scripts/update_references.py            # human-readable report
    uv run python scripts/update_references.py --json      # machine-readable
    uv run python scripts/update_references.py --check     # exit 1 if any stale (CI gate)

Exit codes: 0 = all references current (or --check not passed and nothing
fatal happened); 1 = at least one crate has drifted AND --check was passed,
or a fatal error occurred (bad header, network failure with no cached data).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("update_references")

_HEADER_RE = re.compile(r"<!--\s*ref-crate-versions:\s*(?P<body>.*?)\s*-->")
_CRATES_API = "https://crates.io/api/v1/crates/{name}"
_USER_AGENT = "cisternal-customizing-tools-skill (update_references.py)"


@dataclass(frozen=True, slots=True)
class CrateStamp:
    """One `name=version` pair parsed from a reference doc's header."""

    name: str
    stamped_version: str


@dataclass(frozen=True, slots=True)
class StalenessResult:
    """Comparison of one crate's stamped version against crates.io."""

    doc: str
    crate: str
    stamped_version: str
    live_version: str | None
    error: str | None

    @property
    def is_stale(self) -> bool:
        return self.live_version is not None and self.live_version != self.stamped_version


def parse_header(path: Path) -> tuple[list[CrateStamp], str | None]:
    """Parse a reference doc's `ref-crate-versions` header.

    Returns (stamps, checked_date). Raises ValueError if the file has no
    header at all — every reference doc in this skill must carry one.
    """
    with path.open(encoding="utf-8") as f:
        # The header is always on line 1; read just enough to find it.
        head = f.read(2048)

    match = _HEADER_RE.search(head)
    if match is None:
        msg = f"{path}: no `<!-- ref-crate-versions: ... -->` header found"
        raise ValueError(msg)

    body = match.group("body")
    checked_date: str | None = None
    stamps: list[CrateStamp] = []
    for field in body.split(";"):
        field = field.strip()
        if not field:
            continue
        if field.startswith("checked="):
            checked_date = field.removeprefix("checked=").strip()
            continue
        if "=" not in field:
            _log.warning("%s: skipping malformed header field %r", path, field)
            continue
        name, _, version = field.partition("=")
        stamps.append(CrateStamp(name=name.strip(), stamped_version=version.strip()))

    return stamps, checked_date


def fetch_live_version(crate: str, *, timeout: float = 10.0) -> str:
    """Fetch a crate's current max_stable_version from crates.io.

    Raises urllib.error.URLError / ValueError on any failure — callers
    decide whether that's fatal or just "couldn't check this one".
    """
    url = _CRATES_API.format(name=crate)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    try:
        return payload["crate"]["max_stable_version"]
    except (KeyError, TypeError) as exc:
        msg = f"unexpected crates.io response shape for {crate!r}"
        raise ValueError(msg) from exc


def check_references(references_dir: Path) -> list[StalenessResult]:
    """Check every references/*.md file's stamped crate versions against live data."""
    results: list[StalenessResult] = []
    for path in sorted(references_dir.glob("*.md")):
        try:
            stamps, _checked = parse_header(path)
        except ValueError as exc:
            _log.warning("%s", exc)
            continue
        for stamp in stamps:
            try:
                live = fetch_live_version(stamp.name)
                error = None
            except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                live = None
                error = str(exc)
            results.append(
                StalenessResult(
                    doc=path.name,
                    crate=stamp.name,
                    stamped_version=stamp.stamped_version,
                    live_version=live,
                    error=error,
                )
            )
    return results


def _print_report(results: list[StalenessResult]) -> None:
    stale = [r for r in results if r.is_stale]
    errored = [r for r in results if r.error is not None]
    current = [r for r in results if not r.is_stale and r.error is None]

    for r in current:
        print(f"  current   {r.doc:<20} {r.crate:<16} {r.stamped_version}")
    for r in stale:
        print(f"  STALE     {r.doc:<20} {r.crate:<16} {r.stamped_version} -> {r.live_version}")
    for r in errored:
        print(f"  ERROR     {r.doc:<20} {r.crate:<16} could not check: {r.error}")

    print()
    if stale:
        print(f"{len(stale)} crate(s) drifted — re-run the research workflow for:")
        for doc_name in sorted({r.doc for r in stale}):
            print(f"  - references/{doc_name}")
    else:
        print("All stamped crate versions match crates.io.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--references-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "references",
        help="Directory containing this skill's reference docs (default: ../references).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any reference is stale (for a CI staleness gate).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    results = check_references(args.references_dir)
    if not results:
        _log.error("no ref-crate-versions headers found under %s", args.references_dir)
        return 1

    if args.json:
        payload = [
            {
                "doc": r.doc,
                "crate": r.crate,
                "stamped_version": r.stamped_version,
                "live_version": r.live_version,
                "stale": r.is_stale,
                "error": r.error,
            }
            for r in results
        ]
        print(json.dumps(payload, indent=2))
    else:
        _print_report(results)

    any_stale = any(r.is_stale for r in results)
    any_fatal_error = any(r.error is not None for r in results) and not any(
        r.live_version is not None for r in results
    )
    if any_fatal_error:
        return 1
    if args.check and any_stale:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
