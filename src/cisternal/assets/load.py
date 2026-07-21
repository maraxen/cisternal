"""Load AssetBundle IR from manifest and/or registry (M3.1a)."""

from __future__ import annotations

from pathlib import Path

from cisternal.assets.bundle import BundleMetadata, LoadReport
from cisternal.assets.composite import CompositeAssetSource
from cisternal.assets.source import registry_bundle


def load_asset_report(
    *,
    manifest: Path | None = None,
    registry: str = "default",
    metadata: BundleMetadata | None = None,
) -> LoadReport:
    """Load a :class:`LoadReport` using manifest, registry, or both."""
    if manifest is not None:
        return CompositeAssetSource(manifest, registry, metadata=metadata).load()
    return LoadReport(bundle=registry_bundle(registry, metadata=metadata))
