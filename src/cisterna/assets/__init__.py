"""cisterna.assets — Agent-asset IR (data model) and registry source.

Public API:
    AssetSpec      — frozen dataclass: one tool's asset metadata.
    BundleMetadata — frozen dataclass: name/version/description for a bundle.
    CommandAsset   — frozen dataclass: one command asset.
    McpAsset       — frozen dataclass: one MCP server entry.
    SkillAsset     — frozen dataclass: one skill asset (M3.1a).
    AgentAsset     — frozen dataclass: one agent asset (M3.1a).
    HookSpecAsset  — frozen dataclass: one hook spec asset (M3.1a).
    LoadReport     — load result with bundle, warnings, conflicts (M3.1a).
    AssetBundle    — frozen dataclass: full bundle; sorted collections.
    registry_assets — Extract AssetSpec tuples from a named registry partition.
"""

from cisterna.assets.spec import AssetSpec
from cisterna.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    HookSpecAsset,
    LoadReport,
    McpAsset,
    SkillAsset,
)
from cisterna.assets.source import registry_assets

__all__ = [
    "AssetSpec",
    "AgentAsset",
    "AssetBundle",
    "BundleMetadata",
    "CommandAsset",
    "HookSpecAsset",
    "LoadReport",
    "McpAsset",
    "SkillAsset",
    "registry_assets",
]
