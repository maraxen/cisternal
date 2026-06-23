"""AC-M5-0b: import cisterna must not start telemetry pipeline."""

from __future__ import annotations

import importlib
import sys


def test_import_cisterna_does_not_start_pipeline() -> None:
    """Fresh import leaves get_pipeline() as None until cisterna.init()."""
    # Remove cached module to approximate fresh interpreter behavior.
    for name in list(sys.modules):
        if name == "cisterna" or name.startswith("cisterna."):
            del sys.modules[name]

    importlib.import_module("cisterna")
    from cisterna.telemetry.pipeline import get_pipeline

    assert get_pipeline() is None
