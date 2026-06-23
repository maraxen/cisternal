"""Telemetry consumer enablement via environment (M5.1b)."""

from __future__ import annotations

import os

_ENABLED_VALUES = frozenset({"1", "true", "yes", "all"})


def consumer_telemetry_enabled(consumer: str) -> bool:
    """Return whether cisterna telemetry is enabled for *consumer*.

    Reads ``CISTERNA_TELEMETRY``:
    - unset / empty → disabled for all consumers
    - ``all`` / ``1`` / ``true`` / ``yes`` → enabled for all known consumers
    - otherwise → enabled only when value equals *consumer* (case-insensitive)
    """
    raw = os.environ.get("CISTERNA_TELEMETRY", "").strip().lower()
    if not raw:
        return False
    if raw in _ENABLED_VALUES:
        return True
    return raw == consumer.strip().lower()
