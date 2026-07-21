"""Shadow harness utilities for testing parity between legacy and cisternal telemetry.

Shadow harness (spec §6.1-6.3) provides:
- capture_legacy: Spy on consumer's stdlib logger without side effects
- assert_parity: Verify legacy and cisternal streams share >= 1 matching tool name
"""

import logging
from contextlib import contextmanager
from typing import Iterator

from cisternal.telemetry.record import Record


@contextmanager
def capture_legacy(consumer: str) -> Iterator[list[logging.LogRecord]]:
    """Attach spy logging.Handler to consumer's logger; yield records; detach after.

    Non-invasive: Adds a handler, yields collected records, and removes handler.
    Logger names verified from source:
    - bathos -> "bathos"
    - contemplex -> "contemplex"
    - xperiri -> "xperiri" (cutover stub; legacy uses event_log stdout today)
    - myxcel -> "myxcel" (cutover stub; HPC + MCP tools)

    Args:
        consumer: Logger name (e.g., "bathos", "contemplex")

    Yields:
        list[logging.LogRecord]: Records captured during the context.
    """
    logger = logging.getLogger(consumer)
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Handler()
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


def assert_parity(
    legacy: list[logging.LogRecord],
    cisternal_records: list[Record],
) -> None:
    """Assert both streams non-empty and share >= 1 matching tool name (spec §6.3).

    Checks: both streams non-empty; tool names from legacy and cisternal overlap.

    Args:
        legacy: list[logging.LogRecord] from capture_legacy
        cisternal_records: list[Record] from ShadowExporter
    """
    assert len(legacy) >= 1, "Legacy stream must have >= 1 record"
    assert len(cisternal_records) >= 1, "Cisternal stream must have >= 1 record"

    # Extract tool names from legacy records
    # logging.info(msg, extra={...}) puts extra dict keys as ATTRIBUTES on LogRecord
    legacy_tools: set[str] = set()
    for lr in legacy:
        # extra={...} becomes attributes directly on LogRecord
        tool = getattr(lr, "tool", None)
        if tool:
            legacy_tools.add(str(tool))

    # Extract tool names from cisternal records
    cisternal_tools: set[str] = {
        r.fields.get("tool", "")
        for r in cisternal_records
        if r.fields.get("tool")
    }

    # Verify overlap
    overlap = legacy_tools & cisternal_tools
    assert overlap, (
        f"No matching tool names: legacy={legacy_tools} vs cisternal={cisternal_tools}"
    )
