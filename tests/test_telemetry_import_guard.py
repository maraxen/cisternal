"""AC-M5-0b: import cisternal must not start telemetry pipeline."""

from __future__ import annotations

import importlib
import sys


def test_import_cisternal_does_not_start_pipeline() -> None:
    """Fresh import leaves get_pipeline() as None until cisternal.init()."""
    # Remove cached module to approximate fresh interpreter behavior.
    for name in list(sys.modules):
        if name == "cisternal" or name.startswith("cisternal."):
            del sys.modules[name]

    importlib.import_module("cisternal")
    from cisternal.telemetry.pipeline import get_pipeline

    assert get_pipeline() is None
