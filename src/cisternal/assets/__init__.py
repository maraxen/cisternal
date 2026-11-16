"""cisternal.assets — Agent-asset IR (data model) and registry source.

Public API:
    AssetSpec      — frozen dataclass: one tool's asset metadata.
    BundleMetadata — frozen dataclass: name/version/description for a bundle.
    CommandAsset   — frozen dataclass: one command asset.
    McpAsset       — frozen dataclass: one MCP server entry.
    TelemetryAsset — frozen dataclass: how a consumer's telemetry is controlled.
    ConfigOptionAsset — frozen dataclass: one user-configurable plugin option.
    SkillAsset     — frozen dataclass: one skill asset (M3.1a).
    AgentAsset     — frozen dataclass: one agent asset (M3.1a).
    HookSpecAsset  — frozen dataclass: one hook spec asset (M3.1a).
    LoadReport     — load result with bundle, warnings, conflicts (M3.1a).
    AssetBundle    — frozen dataclass: full bundle; sorted collections.
    registry_assets — Extract AssetSpec tuples from a named registry partition.
"""

from cisternal.assets.spec import AssetSpec
from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    ConfigOptionAsset,
    HookSpecAsset,
    LoadReport,
    McpAsset,
    SkillAsset,
    TelemetryAsset,
)
from cisternal.assets.capability import Capability, resolve_model_hint, resolve_tools
from cisternal.assets.composite import CompositeAssetSource
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.assets.protocol import AssetSource
from cisternal.assets.source import registry_assets, registry_bundle

__all__ = [
    "AssetSpec",
    "AgentAsset",
    "AssetBundle",
    "AssetSource",
    "BundleMetadata",
    "Capability",
    "CommandAsset",
    "CompositeAssetSource",
    "ConfigOptionAsset",
    "HookSpecAsset",
    "LoadReport",
    "ManifestAssetSource",
    "McpAsset",
    "SkillAsset",
    "TelemetryAsset",
    "registry_assets",
    "registry_bundle",
    "resolve_model_hint",
    "resolve_tools",
]
