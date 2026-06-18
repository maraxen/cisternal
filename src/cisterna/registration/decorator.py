"""Public decorator re-export for the cisterna registration subsystem.

This module re-exports ``tool`` from :mod:`cisterna.registration.registry` so
that callers can write::

    from cisterna.registration import tool
    # or equivalently:
    from cisterna.registration.decorator import tool

The indirection exists so the registry module can be replaced by the
M2-REGISTRY track (item 2141) without touching the public import path.
"""

from __future__ import annotations

from cisterna.registration.registry import tool

__all__ = ["tool"]
