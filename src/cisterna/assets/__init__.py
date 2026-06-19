"""cisterna.assets — Agent-asset IR (data model) and registry source.

Public API:
    AssetSpec      — frozen dataclass: one tool's asset metadata.
    BundleMetadata — frozen dataclass: name/version/description for a bundle.
    CommandAsset   — frozen dataclass: one command asset.
    McpAsset       — frozen dataclass: one MCP server entry (reserved M3.1).
    AssetBundle    — frozen dataclass: full bundle; commands sorted by name.
    registry_assets — Extract AssetSpec tuples from a named registry partition.
"""

from cisterna.assets.spec import AssetSpec
from cisterna.assets.bundle import (
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    McpAsset,
)
from cisterna.assets.source import registry_assets

__all__ = [
    "AssetSpec",
    "AssetBundle",
    "BundleMetadata",
    "CommandAsset",
    "McpAsset",
    "registry_assets",
]
