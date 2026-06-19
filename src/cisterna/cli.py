"""Cisterna CLI — agent-asset export surface (spec §4, M3 Wave 3).

Provides:
    app — cyclopts App; entry point ``cisterna`` (pyproject [project.scripts]).

Subcommand tree:
    cisterna assets export [OPTIONS]

This module is FASTMCP-FREE by design (spec M4): importing ``cisterna.cli``
must succeed even when ``fastmcp`` is not installed.  All asset-export logic
routes through ``cisterna.assets.source`` (fastmcp-free path), never via
``cisterna.__init__`` (which lazily imports fastmcp via ``wire``/``WiredRegistry``).

Coexistence note:
    ``cisterna/adapters/cli.py`` provides the unrelated ``CliAdapter`` /
    ``timed_command`` telemetry surface.  Do NOT merge the two modules — they
    serve different concerns (telemetry instrumentation vs. asset export).

--import in-process limitation (spec B3):
    ``--import MODULE`` calls ``importlib.import_module(MODULE)`` to run the
    target module's ``@tool`` decorator side-effects.  Because Python caches
    imported modules in ``sys.modules``, re-importing an already-imported
    module in the same process is a no-op — no re-registration occurs.
    The contract is therefore:
        *The import target's @tool calls must execute in this process by
        export time.*
    If you need to re-register tools in the same process, call
    ``cisterna.clear_registry()`` first.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from pathlib import Path
from typing import Annotated

import cyclopts

_log = logging.getLogger("cisterna.cli")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = cyclopts.App(name="cisterna", help="Cisterna CLI.")
assets_app = cyclopts.App(name="assets", help="Agent-asset commands.")
app.command(assets_app)


# ---------------------------------------------------------------------------
# cisterna assets export
# ---------------------------------------------------------------------------


@assets_app.command(name="export")
def export(
    *,
    dry_run: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--dry-run"],
            help="Print file paths and sha256 hashes; write nothing.",
        ),
    ] = False,
    registry: Annotated[
        str,
        cyclopts.Parameter(
            name=["--registry"],
            help="Registry partition name to export (default: 'default').",
        ),
    ] = "default",
    out: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--out"],
            help="Output directory for emitted files (default: '.').",
        ),
    ] = Path("."),
    import_: Annotated[
        tuple[str, ...],
        cyclopts.Parameter(
            name=["--import"],
            help=(
                "Python module to import before export (repeatable). "
                "Triggers @tool registration side-effects. "
                "In-process only: sys.modules caching means already-imported "
                "modules are NOT re-imported."
            ),
        ),
    ] = (),
    name: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--name"],
            help="Bundle name (default: 'cisterna').",
        ),
    ] = None,
    version: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--version"],
            help="Bundle version (default: installed package version or '0.0.0').",
        ),
    ] = None,
) -> None:
    """Export registered tool assets to a Claude plugin bundle.

    Reads tools from the named registry partition, builds a Claude plugin
    manifest, and writes (or dry-runs) the output to --out.

    Always exits with code 0.  Warnings are emitted to stderr on empty
    registries or import errors.
    """
    # Import modules first so their @tool side-effects fire before snapshotting.
    for m in import_:
        try:
            importlib.import_module(m)
        except Exception:
            _log.warning("cisterna.cli: could not import %r; skipping", m, exc_info=True)

    # Import registry_assets via fastmcp-free path (spec M4).
    from cisterna.assets.source import registry_assets  # noqa: PLC0415

    snapshot = registry_assets(registry)

    if len(snapshot) == 0:
        _log.warning(
            "cisterna.cli: registry %r is empty; emitting empty bundle",
            registry,
        )

    # Resolve bundle metadata.
    resolved_name = name or "cisterna"
    if version is not None:
        resolved_version = version
    else:
        try:
            resolved_version = importlib.metadata.version("cisterna")
        except importlib.metadata.PackageNotFoundError:
            resolved_version = "0.0.0"

    # Build IR.
    from cisterna.assets.bundle import AssetBundle, BundleMetadata, CommandAsset  # noqa: PLC0415

    metadata = BundleMetadata(
        name=resolved_name,
        version=resolved_version,
        description="",
    )
    commands = tuple(
        CommandAsset(name=spec.name, description=spec.description)
        for spec in snapshot
    )
    bundle = AssetBundle(metadata=metadata, commands=commands)

    # Emit.
    from cisterna.export.claude import ClaudeEmitter  # noqa: PLC0415
    from cisterna.export.write import write_bundle  # noqa: PLC0415

    files = ClaudeEmitter().emit(bundle)
    result = write_bundle(files, out, dry_run=dry_run)

    if dry_run:
        for path, sha256 in result.files:
            print(f"{path}  {sha256}")
