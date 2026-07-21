"""AssetSource protocol (M3.1a spec L1)."""

from __future__ import annotations

from typing import Protocol

from cisternal.assets.bundle import LoadReport


class AssetSource(Protocol):
    """Load an :class:`AssetBundle` without raising (never-raise convention)."""

    def load(self) -> LoadReport:
        """Return a load report; errors degrade to warnings on the report."""
        ...
