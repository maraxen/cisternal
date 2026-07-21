"""Composite manifest + registry asset source (M3.1a spec L2, L3)."""

from __future__ import annotations

from pathlib import Path

from cisternal.assets.bundle import (
    AssetBundle,
    BundleMetadata,
    CommandAsset,
    LoadReport,
)
from cisternal.assets.manifest import ManifestAssetSource
from cisternal.assets.source import registry_bundle


class CompositeAssetSource:
    """Merge manifest-loaded assets with registry-sourced commands."""

    def __init__(
        self,
        manifest_path: Path | str,
        registry: str = "default",
        *,
        metadata: BundleMetadata | None = None,
    ) -> None:
        self._manifest_path = Path(manifest_path)
        self._registry = registry
        self._metadata = metadata

    def load(self) -> LoadReport:
        manifest_report = ManifestAssetSource(self._manifest_path).load()
        registry_meta = self._metadata or manifest_report.bundle.metadata
        registry_b = registry_bundle(self._registry, metadata=registry_meta)

        warnings = list(manifest_report.warnings)
        conflicts: list[str] = []

        commands, cmd_conflicts = _merge_commands(
            manifest_report.bundle.commands,
            registry_b.commands,
        )
        conflicts.extend(cmd_conflicts)

        # Registry contributes commands only (L13); other kinds from manifest.
        bundle = AssetBundle(
            metadata=manifest_report.bundle.metadata,
            commands=commands,
            mcp_servers=manifest_report.bundle.mcp_servers,
            skills=manifest_report.bundle.skills,
            agents=manifest_report.bundle.agents,
            hook_specs=manifest_report.bundle.hook_specs,
        )
        return LoadReport(
            bundle=bundle,
            warnings=tuple(warnings),
            conflicts=tuple(conflicts),
        )


def _merge_commands(
    manifest_items: tuple[CommandAsset, ...],
    registry_items: tuple[CommandAsset, ...],
) -> tuple[tuple[CommandAsset, ...], list[str]]:
    merged: dict[str, CommandAsset] = {c.name: c for c in manifest_items}
    conflicts: list[str] = []
    for item in registry_items:
        if item.name not in merged:
            merged[item.name] = item
        elif _commands_incompatible(merged[item.name], item):
            conflicts.append(
                f"command {item.name!r}: manifest and registry payloads differ"
            )
    ordered = tuple(merged[name] for name in sorted(merged))
    return ordered, conflicts


def _commands_incompatible(a: CommandAsset, b: CommandAsset) -> bool:
    return a.description != b.description or a.body != b.body
