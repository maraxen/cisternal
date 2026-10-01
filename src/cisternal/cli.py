"""Cisternal CLI — agent-asset export surface (spec §4, M3 Wave 3).

Provides:
    app — cyclopts App; entry point ``cisternal`` (pyproject [project.scripts]).

Subcommand tree:
    cisternal assets export [OPTIONS]
    cisternal assets inspect [OPTIONS]
    cisternal assets validate [OPTIONS]
    cisternal assets install [OPTIONS]
    cisternal assets publish-shared [OPTIONS]
    cisternal assets update-all [OPTIONS]
    cisternal assets snapshot [OPTIONS]
    cisternal plugin install|update|export|info   (cisternal.plugin sub-app,
                                                   mountable by any tool's CLI)
    cisternal telemetry doctor

This module is FASTMCP-FREE by design (spec M4): importing ``cisternal.cli``
must succeed even when ``fastmcp`` is not installed.  All asset-export logic
routes through ``cisternal.assets.source`` (fastmcp-free path), never via
``cisternal.__init__`` (which lazily imports fastmcp via ``wire``/``WiredRegistry``).

Coexistence note:
    ``cisternal/adapters/cli.py`` provides the unrelated ``CliAdapter`` /
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
    ``cisternal.clear_registry()`` first.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import cyclopts

_log = logging.getLogger("cisternal.cli")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = cyclopts.App(name="cisternal", help="Cisternal CLI.", version_flags=[])
assets_app = cyclopts.App(name="assets", help="Agent-asset commands.", version_flags=[])
telemetry_app = cyclopts.App(
    name="telemetry",
    help=(
        "Telemetry operator commands. "
        "Runbook: .praxia/docs/runbooks/cisternal-telemetry.md"
    ),
    version_flags=[],
)
app.command(assets_app)
app.command(telemetry_app)

# cisternal's own plugin, through the same sub-app every tool can mount
# (`cisternal plugin install claude`). Dogfoods cisternal.plugin.
from cisternal.plugin import PluginSpec, plugin_app  # noqa: E402

app.command(plugin_app(PluginSpec(name="cisternal", package="cisternal", cli="cisternal")))


@telemetry_app.command(name="doctor")
def telemetry_doctor(
    *,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON report to stdout.",
        ),
    ] = False,
    strict: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--strict"],
            help="Treat warnings as failures for exit code (see CISTERNAL_DOCTOR_STRICT).",
        ),
    ] = False,
    consumer: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--consumer"],
            help=(
                "Scope telemetry_gate to one consumer "
                "(bathos|contemplex|xperiri|myxcel; see CISTERNAL_DOCTOR_CONSUMER)."
            ),
        ),
    ] = None,
) -> None:
    """Print effective telemetry configuration (read-only).

    Operator runbook: .praxia/docs/runbooks/cisternal-telemetry.md

    CI/cutover scripts should use ``--json --strict`` (or set
    ``CISTERNAL_DOCTOR_STRICT=1``) so disabled telemetry fails the gate.
    Sibling-repo cutover may add ``--consumer <name>`` to scope the gate.
    """
    from cisternal.probe.telemetry_doctor import (  # noqa: PLC0415
        build_doctor_report,
        compute_doctor_exit_code,
        format_doctor_json,
        format_doctor_report,
        resolve_doctor_consumer,
        resolve_doctor_strict_mode,
    )

    try:
        consumer_filter = resolve_doctor_consumer(cli_consumer=consumer)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    report = build_doctor_report(consumer_filter=consumer_filter)
    strict_mode = resolve_doctor_strict_mode(cli_strict=strict)
    if json_output:
        print(format_doctor_json(report, strict=strict_mode))
    else:
        print(format_doctor_report(report))
    raise SystemExit(compute_doctor_exit_code(report, strict=strict_mode))


# ---------------------------------------------------------------------------
# cisternal assets export
# ---------------------------------------------------------------------------


def _load_export_bundle(
    *,
    manifest: Path | None,
    registry: str,
    name: str | None,
    version: str | None,
):
    # No return-type annotation: AssetBundle is imported lazily inside this
    # function (matches the existing fastmcp-free lazy-import style in this
    # module), so a module-level type reference isn't available to annotate with.
    from cisternal.assets.bundle import AssetBundle, BundleMetadata, CommandAsset  # noqa: PLC0415

    if manifest is not None:
        from cisternal.assets.load import load_asset_report  # noqa: PLC0415

        metadata_override: BundleMetadata | None = None
        if name is not None or version is not None:
            pre = load_asset_report(manifest=manifest, registry=registry)
            metadata_override = BundleMetadata(
                name=name or pre.bundle.metadata.name,
                version=version or pre.bundle.metadata.version,
                description=pre.bundle.metadata.description,
            )
        report = load_asset_report(
            manifest=manifest,
            registry=registry,
            metadata=metadata_override,
        )
        bundle = report.bundle
        for warning in report.warnings:
            _log.warning("cisternal.cli: %s", warning)
        for conflict in report.conflicts:
            _log.warning("cisternal.cli: conflict: %s", conflict)
        return bundle

    # Import registry_assets via fastmcp-free path (spec M4).
    from cisternal.assets.source import registry_assets  # noqa: PLC0415

    snapshot = registry_assets(registry)
    if len(snapshot) == 0:
        # (#28) No --manifest was given AND the in-process tool registry is
        # empty -- there is nothing to export. This used to warn and emit an
        # empty-but-valid bundle at exit 0 (AC-M3-8b), which looked like a
        # successful handoff downstream while actually producing nothing;
        # reversed per #28 in favor of a loud failure naming the likely cause
        # (forgetting --manifest, or exporting before any @cisternal.tool
        # registration / --import has happened).
        _log.error(
            "cisternal.cli: export failed — registry %r is empty and no "
            "--manifest was given; nothing to export. Pass --manifest, or "
            "register tools via @cisternal.tool (directly, or via --import) "
            "before calling export.",
            registry,
        )
        raise SystemExit(1)
    resolved_name = name or "cisternal"
    if version is not None:
        resolved_version = version
    else:
        try:
            resolved_version = importlib.metadata.version("cisternal")
        except importlib.metadata.PackageNotFoundError:
            resolved_version = "0.0.0"
    metadata = BundleMetadata(name=resolved_name, version=resolved_version, description="")
    commands = tuple(
        CommandAsset(name=spec.name, description=spec.description) for spec in snapshot
    )
    return AssetBundle(metadata=metadata, commands=commands)


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
            help="Bundle name (default: 'cisternal').",
        ),
    ] = None,
    version: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--version"],
            help="Bundle version (default: installed package version or '0.0.0').",
        ),
    ] = None,
    manifest: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml (CompositeAssetSource with --registry).",
        ),
    ] = None,
    emit_command_bodies: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--emit-command-bodies"],
            help="Emit commands/<name>.md for commands with non-empty bodies (claude only).",
        ),
    ] = False,
    surface: Annotated[
        str,
        cyclopts.Parameter(
            name=["--surface"],
            help=(
                "Emit surface: antigravity, claude, copilot, cursor, "
                "jcode, opencode, or pi (default: claude)."
            ),
        ),
    ] = "claude",

) -> None:
    """Export agent assets to a plugin bundle for the selected surface.

    Reads tools from the named registry partition (or manifest + registry),
    builds a Claude plugin manifest, and writes (or dry-runs) the output to --out.

    Always exits with code 0.  Warnings are emitted to stderr on empty
    registries or import errors.
    """
    # Import modules first so their @tool side-effects fire before snapshotting.
    for m in import_:
        try:
            importlib.import_module(m)
        except Exception:
            _log.warning("cisternal.cli: could not import %r; skipping", m, exc_info=True)

    bundle = _load_export_bundle(manifest=manifest, registry=registry, name=name, version=version)

    # Emit.
    from cisternal.export.registry import get_emitter, list_emitter_surfaces  # noqa: PLC0415
    from cisternal.export.write import write_bundle  # noqa: PLC0415

    if surface not in list_emitter_surfaces():
        _log.error("cisternal.cli: unsupported export surface %r", surface)
        raise SystemExit(2)

    bodies = emit_command_bodies
    if surface != "claude" and emit_command_bodies:
        _log.warning(
            "cisternal.cli: --emit-command-bodies ignored for surface %r",
            surface,
        )
        bodies = False

    emitter = get_emitter(surface, emit_command_bodies=bodies)
    if emitter is None:
        _log.error("cisternal.cli: could not load emitter for surface %r", surface)
        raise SystemExit(2)

    files = emitter.emit(bundle)
    result = write_bundle(files, out, dry_run=dry_run)

    if dry_run:
        for path, sha256 in result.files:
            print(f"{path}  {sha256}")


@assets_app.command(name="install")
def install(
    *,
    manifest: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml. Must define [plugin.marketplace].",
        ),
    ] = None,
    registry: Annotated[
        str,
        cyclopts.Parameter(
            name=["--registry"],
            help="Registry partition name (default: 'default').",
        ),
    ] = "default",
    out: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--out"],
            help="Directory to write the plugin bundle to (default: '.').",
        ),
    ] = Path("."),
    name: Annotated[
        str | None,
        cyclopts.Parameter(name=["--name"], help="Bundle name override."),
    ] = None,
    version: Annotated[
        str | None,
        cyclopts.Parameter(name=["--version"], help="Bundle version override."),
    ] = None,
    marketplace_name: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--marketplace-name"],
            help="Marketplace name override (default: manifest's [plugin.marketplace].name).",
        ),
    ] = None,
    scope: Annotated[
        str,
        cyclopts.Parameter(
            name=["--scope"],
            help="Install scope: user, project, or local (default: 'project').",
        ),
    ] = "project",
    claude_bin: Annotated[
        str,
        cyclopts.Parameter(
            name=["--claude-bin"],
            help="Path to the claude CLI binary (default: 'claude').",
        ),
    ] = "claude",
    dry_run: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--dry-run"],
            help="Print the files and commands that would run; do nothing.",
        ),
    ] = False,
) -> None:
    """Export a plugin bundle and register+install it as a real Claude Code plugin.

    Requires --manifest with a [plugin.marketplace] table. Writes the bundle
    to --out, then runs `claude plugin marketplace add <out>` and `claude
    plugin install <name>@<marketplace> --scope <scope>` as subprocesses.
    Both underlying commands are idempotent as of claude 2.1.227 — re-running
    install is safe.

    This makes the bundle its own standalone, single-plugin marketplace
    (`source: "./"`) — the right tool for "give me this one tool". To
    instead add this plugin to an existing marketplace that already lists
    other tools (a shared, multi-tool marketplace like the
    praxia/myxcel/cisternal family's), use `assets publish-shared` — it
    merges into that marketplace's entry list rather than replacing it.

    Unlike export/inspect/validate, install exits non-zero on real failure:
    it mutates live Claude Code state (marketplace registration, installed-
    plugin config), so a failure here must be visible, not swallowed.
    """
    if manifest is None:
        _log.error("cisternal.cli: assets install requires --manifest")
        raise SystemExit(2)

    bundle = _load_export_bundle(manifest=manifest, registry=registry, name=name, version=version)

    if bundle.marketplace is None:
        _log.error(
            "cisternal.cli: manifest %s has no [plugin.marketplace] table; "
            "assets install requires one",
            manifest,
        )
        raise SystemExit(2)

    resolved_marketplace_name = marketplace_name or bundle.marketplace.name
    if marketplace_name and marketplace_name != bundle.marketplace.name:
        bundle = replace(bundle, marketplace=replace(bundle.marketplace, name=marketplace_name))

    from cisternal.export.claude import ClaudeEmitter  # noqa: PLC0415
    from cisternal.export.write import write_bundle  # noqa: PLC0415

    files = ClaudeEmitter().emit(bundle)
    plugin_id = f"{bundle.metadata.name}@{resolved_marketplace_name}"
    # `claude plugin marketplace add` rejects bare relative paths like "." (though
    # it accepts "./"), so always pass an absolute path to avoid that footgun.
    out_abs = out.resolve()

    if dry_run:
        for path in sorted(files):
            print(path)
        print(f"would run: {claude_bin} plugin marketplace add {out_abs}")
        print(f"would run: {claude_bin} plugin install {plugin_id} --scope {scope}")
        return

    write_bundle(files, out, dry_run=False)

    if not (out / ".claude-plugin" / "plugin.json").is_file() or not (
        out / ".claude-plugin" / "marketplace.json"
    ).is_file():
        _log.error(
            "cisternal.cli: bundle write to %s appears incomplete "
            "(missing .claude-plugin/plugin.json or .claude-plugin/marketplace.json); "
            "refusing to run claude",
            out,
        )
        raise SystemExit(1)

    add_result = _run_claude(
        [claude_bin, "plugin", "marketplace", "add", str(out_abs)], claude_bin=claude_bin
    )
    if add_result.returncode != 0:
        _log.error(
            "cisternal.cli: `claude plugin marketplace add` failed (exit %d): %s",
            add_result.returncode,
            add_result.stderr.strip(),
        )
        raise SystemExit(1)

    install_result = _run_claude(
        [claude_bin, "plugin", "install", plugin_id, "--scope", scope], claude_bin=claude_bin
    )
    if install_result.returncode != 0:
        _log.error(
            "cisternal.cli: `claude plugin install` failed (exit %d): %s",
            install_result.returncode,
            install_result.stderr.strip(),
        )
        raise SystemExit(1)

    print(f"Installed {plugin_id} (scope={scope})")


def _run_claude(argv: list[str], *, claude_bin: str) -> subprocess.CompletedProcess[str]:
    """Run a `claude` subprocess, converting binary-not-found into SystemExit(1).

    Every other install() failure path logs via _log.error + raises
    SystemExit(1); without this, a missing/non-executable claude_bin would
    instead propagate as a raw, unhandled Python traceback.
    """
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        _log.error("cisternal.cli: could not run %r: %s", claude_bin, exc)
        raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# cisternal assets publish-shared
# ---------------------------------------------------------------------------


@assets_app.command(name="publish-shared")
def publish_shared(
    *,
    manifest: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml (default: .praxia/manifest.toml).",
        ),
    ] = Path(".praxia/manifest.toml"),
    registry: Annotated[
        str,
        cyclopts.Parameter(
            name=["--registry"],
            help="Registry partition name to export (default: 'default').",
        ),
    ] = "default",
    name: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--name"],
            help="Plugin name (default: manifest's plugin.name).",
        ),
    ] = None,
    description: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--description"],
            help="Marketplace entry description (default: manifest's plugin.description).",
        ),
    ] = None,
    marketplace: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--marketplace"],
            help="Marketplace root (default: resolved -- $CISTERNAL_PLUGIN_MARKETPLACE, "
            "[tool.cisternal] plugin_marketplace, ~/.config/cisternal/config.toml; "
            "see cisternal.plugin.config).",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--refresh"],
            help="After publishing, refresh Claude Code: update the marketplace listing and "
            "update the plugin if it is installed (default: on; --no-refresh to skip).",
        ),
    ] = True,
    prune_shadowed: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--prune-shadowed"],
            help="Move raw ~/.claude/skills/<skill>/ and ~/.claude/agents/<plugin>-<agent>.md "
            "copies that shadow this plugin's own skills/agents into a timestamped backup "
            "(~/.cisternal/shadowed/). Without it they are only reported.",
        ),
    ] = False,
    claude_bin: Annotated[
        str,
        cyclopts.Parameter(
            name=["--claude-bin"],
            help="Path to the claude CLI binary used by --refresh (default: 'claude').",
        ),
    ] = "claude",
) -> None:
    """Export this manifest's Claude plugin bundle into a SHARED, multi-tool marketplace.

    Not the same job as ``assets install``: that command makes a bundle its
    own standalone, single-plugin marketplace (``source: "./"``) and
    registers it via the real ``claude`` CLI — the right tool for installing
    one repo's plugin for yourself. This command instead publishes into an
    existing marketplace that already lists other tools (e.g.
    ``~/.cisternal/claude-plugin-marketplace``, shared across the
    praxia/myxcel/cisternal-family), merging its entry alongside theirs
    rather than replacing the marketplace file. Use ``assets install`` for
    "give me this one tool"; use this command for "add this tool to the
    shared family marketplace everyone already has registered."

    Publishes to ``<marketplace>/plugins/<name>/`` (scrubbing stale files first,
    since the asset writer does not prune) and merges a
    ``<marketplace>/.claude-plugin/marketplace.json`` entry under an flock'd,
    atomic read-modify-write — safe for concurrent publishes from other
    cisternal-family tools sharing the same marketplace.

    The published version is the manifest's version suffixed with a content
    digest of the emitted bundle, so Claude Code's version-keyed plugin cache
    is busted exactly when — and only when — the bundle actually changes.

    It also records where the bundle came from (``cisternal-source.json``), so
    ``assets update-all`` can later republish every plugin from its own repo.

    With ``--refresh`` (the default), a changed bundle is pushed into Claude
    Code: ``claude plugin marketplace update`` then ``claude plugin update``
    for an installed plugin; restart Claude Code to load it. The marketplace
    itself must be registered once per machine
    (``/plugin marketplace add <marketplace>``).
    """
    from cisternal.plugin.shared import handle_shadowed, refresh_claude  # noqa: PLC0415

    root = _resolve_marketplace(marketplace)
    result = _publish_shared_core(
        manifest=manifest,
        registry=registry,
        name=name,
        description=description,
        marketplace=root,
    )
    print(f"published {result.name}@{result.version} -> {result.out}")
    print(f"marketplace: {root}")
    handle_shadowed([result], prune=prune_shadowed)
    if refresh and refresh_claude(root, [result], claude_bin=claude_bin) != 0:
        raise SystemExit(1)


def _resolve_marketplace(marketplace: Path | None) -> Path:
    from cisternal.plugin.config import resolve_marketplace_root  # noqa: PLC0415

    try:
        return resolve_marketplace_root(marketplace)
    except ValueError as exc:
        _log.error("cisternal.cli: %s", exc)
        raise SystemExit(2) from exc


def _publish_shared_core(
    *,
    manifest: Path,
    registry: str,
    name: str | None,
    description: str | None,
    marketplace: Path,
):
    """Load a manifest strictly, then publish it into the shared marketplace."""
    from cisternal.assets.bundle import BundleMetadata  # noqa: PLC0415
    from cisternal.assets.load import load_asset_report  # noqa: PLC0415
    from cisternal.plugin.shared import publish_bundle  # noqa: PLC0415

    report = load_asset_report(manifest=manifest, registry=registry)
    if report.conflicts:
        _log.error("cisternal.cli: publish-shared failed — conflicts: %s", report.conflicts)
        raise SystemExit(1)
    if report.warnings:
        _log.error("cisternal.cli: publish-shared failed — warnings: %s", report.warnings)
        raise SystemExit(1)

    meta = report.bundle.metadata
    bundle = replace(
        report.bundle,
        metadata=BundleMetadata(
            name=name or meta.name,
            version=meta.version,
            description=description or meta.description,
        ),
    )
    source = {
        "manifest": str(manifest.expanduser().resolve()),
        "registry": registry,
        "name": name,
        "description": description,
    }
    try:
        return publish_bundle(bundle, marketplace=marketplace, source=source)
    except RuntimeError as exc:
        _log.error("cisternal.cli: publish-shared failed — %s", exc)
        raise SystemExit(2) from exc


@assets_app.command(name="update-all")
def update_all(
    *,
    marketplace: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--marketplace"],
            help="Marketplace root (default: resolved -- $CISTERNAL_PLUGIN_MARKETPLACE, "
            "[tool.cisternal] plugin_marketplace, ~/.config/cisternal/config.toml; "
            "see cisternal.plugin.config).",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--refresh"],
            help="Refresh Claude Code for changed, installed plugins (default: on).",
        ),
    ] = True,
    prune_shadowed: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--prune-shadowed"],
            help="Move raw ~/.claude/skills/<skill>/ and ~/.claude/agents/<plugin>-<agent>.md "
            "copies that shadow this plugin's own skills/agents into a timestamped backup "
            "(~/.cisternal/shadowed/). Without it they are only reported.",
        ),
    ] = False,
    claude_bin: Annotated[
        str,
        cyclopts.Parameter(name=["--claude-bin"], help="Path to the claude CLI (default: 'claude')."),
    ] = "claude",
    dry_run: Annotated[
        bool,
        cyclopts.Parameter(name=["--dry-run"], help="List what would be republished; change nothing."),
    ] = False,
) -> None:
    """Republish every plugin in the shared marketplace from its source repo.

    Each plugin published by ``publish-shared`` records its manifest in
    ``cisternal-source.json``; this re-runs that publish for all of them (from
    each repo's current checkout), then refreshes Claude Code once for the ones
    whose content changed. Plugins without the sidecar are listed as unmanaged:
    run ``cisternal assets publish-shared`` once from that tool's repo to enroll it.
    """
    from cisternal.plugin.shared import (  # noqa: PLC0415
        SOURCE_SIDECAR,
        PublishResult,
        handle_shadowed,
        refresh_claude,
    )

    marketplace = _resolve_marketplace(marketplace)
    plugins_dir = marketplace / "plugins"
    if not plugins_dir.is_dir():
        _log.error("cisternal.cli: no plugins directory at %s", plugins_dir)
        raise SystemExit(1)

    results: list[PublishResult] = []
    unmanaged: list[str] = []
    tool_managed: list[str] = []
    failed: list[str] = []
    for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
        sidecar = plugin_dir / ".claude-plugin" / SOURCE_SIDECAR
        if not sidecar.is_file():
            unmanaged.append(plugin_dir.name)
            continue
        try:
            source = json.loads(sidecar.read_text(encoding="utf-8"))
            if "update_command" in source:
                # Published by a tool's `plugin` sub-app: that tool owns the
                # recipe (version, snapshot vs checkout), so defer to it.
                tool_managed.append(f"{plugin_dir.name}: run `{source['update_command']}`")
                continue
            source_manifest = Path(source["manifest"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed.append(f"{plugin_dir.name}: unreadable {SOURCE_SIDECAR} ({exc})")
            continue
        if not source_manifest.is_file():
            failed.append(f"{plugin_dir.name}: manifest not found at {source_manifest}")
            continue
        if dry_run:
            print(f"would republish {plugin_dir.name} from {source_manifest}")
            continue
        try:
            results.append(
                _publish_shared_core(
                    manifest=source_manifest,
                    registry=source.get("registry") or "default",
                    name=source.get("name"),
                    description=source.get("description"),
                    marketplace=marketplace,
                )
            )
        except SystemExit as exc:
            failed.append(f"{plugin_dir.name}: publish failed (exit {exc.code})")

    for r in results:
        state = f"{r.previous_version} -> {r.version}" if r.changed else f"unchanged ({r.version})"
        print(f"{r.name}: {state}")
    for plugin_name in unmanaged:
        print(
            f"{plugin_name}: unmanaged (no {SOURCE_SIDECAR}) -- run "
            "`cisternal assets publish-shared` once from its repo to enroll it"
        )
    for line in tool_managed:
        print(f"managed by its tool -- {line}")
    for line in failed:
        print(f"FAILED {line}")

    if not dry_run:
        handle_shadowed(results, prune=prune_shadowed)

    rc = 0
    if refresh and not dry_run:
        rc = refresh_claude(marketplace, results, claude_bin=claude_bin)
    if failed or rc:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# cisternal assets snapshot
# ---------------------------------------------------------------------------


@assets_app.command(name="snapshot")
def snapshot(
    *,
    manifest: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml (default: .praxia/manifest.toml).",
        ),
    ] = Path(".praxia/manifest.toml"),
    out: Annotated[
        Path,
        cyclopts.Parameter(
            name=["--out"],
            help="Snapshot file to write, inside your package (e.g. src/<pkg>/agent_plugin.json).",
        ),
    ],
    check: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--check"],
            help="Write nothing; exit 1 if --out is missing or differs from the manifest (CI).",
        ),
    ] = False,
) -> None:
    """Freeze a manifest's resolved assets into one JSON file to ship as package data.

    A manifest points at files in the source checkout, so it cannot ship in a
    wheel. The snapshot inlines them; a tool that mounts
    ``cisternal.plugin.plugin_app`` falls back to it when installed from a
    wheel, so ``<tool> plugin install claude`` works without the repo.
    Registry commands are not frozen -- they are merged live at install time.
    """
    from cisternal.assets.manifest import ManifestAssetSource  # noqa: PLC0415
    from cisternal.assets.snapshot import dumps_snapshot  # noqa: PLC0415

    report = ManifestAssetSource(manifest).load()
    if report.warnings:
        _log.error("cisternal.cli: snapshot failed — warnings: %s", report.warnings)
        raise SystemExit(1)
    text = dumps_snapshot(report.bundle)

    if check:
        try:
            current = out.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != text:
            _log.error(
                "cisternal.cli: snapshot %s is %s; rerun `cisternal assets snapshot "
                "--manifest %s --out %s`",
                out, "missing" if current is None else "stale", manifest, out,
            )
            raise SystemExit(1)
        print(f"snapshot up to date: {out}")
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# cisternal assets inspect / validate (M3.1a W4)
# ---------------------------------------------------------------------------


@assets_app.command(name="inspect")
def inspect_assets(
    *,
    manifest: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml (uses CompositeAssetSource with --registry).",
        ),
    ] = None,
    registry: Annotated[
        str,
        cyclopts.Parameter(
            name=["--registry"],
            help="Registry partition when loading assets (default: 'default').",
        ),
    ] = "default",
    resolve_tools: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--resolve-tools"],
            help="Include resolved_tools for agents (requires --surface).",
        ),
    ] = False,
    surface: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--surface"],
            help="Vendor surface for tool resolution (e.g. claude_code).",
        ),
    ] = None,
) -> None:
    """Print a JSON LoadReport to stdout (no file writes)."""
    if resolve_tools and not surface:
        _log.error("cisternal.cli: --surface is required with --resolve-tools")
        raise SystemExit(2)

    from cisternal.assets.inspect_json import report_to_dict  # noqa: PLC0415
    from cisternal.assets.load import load_asset_report  # noqa: PLC0415

    report = load_asset_report(manifest=manifest, registry=registry)
    try:
        payload = report_to_dict(
            report,
            resolve_tools_flag=resolve_tools,
            surface=surface,
        )
    except ValueError as exc:
        _log.error("cisternal.cli: inspect failed — %s", exc)
        raise SystemExit(2) from exc
    print(json.dumps(payload, indent=2, sort_keys=True))



@assets_app.command(name="validate")
def validate_assets(
    *,
    manifest: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml (uses CompositeAssetSource with --registry).",
        ),
    ] = None,
    registry: Annotated[
        str,
        cyclopts.Parameter(
            name=["--registry"],
            help="Registry partition when loading assets (default: 'default').",
        ),
    ] = "default",
    surface: Annotated[
        str,
        cyclopts.Parameter(
            name=["--surface"],
            help="Emit surface for golden comparison (default: claude).",
        ),
    ] = "claude",
    emit_command_bodies: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--emit-command-bodies"],
            help="Include per-command body files in emission (golden mode switch).",
        ),
    ] = False,
    use_native_cli: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--use-native-cli"],
            help="Re-emit via subprocess export instead of in-process emitter.",
        ),
    ] = False,
    rust_parity: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--rust-parity"],
            help=(
                "Compare digest to praxia-agent-assets bundle-hash "
                "(requires CISTERNAL_PRAXIA_ASSETS_BIN)."
            ),
        ),
    ] = False,
) -> None:
    """Validate loaded assets: structural checks + golden digest (exit 0/1)."""
    from cisternal.assets.load import load_asset_report  # noqa: PLC0415
    from cisternal.assets.validate_golden import (  # noqa: PLC0415
        golden_digest_path,
        resolve_golden_slug,
        surface_digest,
    )
    from cisternal.export.registry import list_emitter_surfaces  # noqa: PLC0415

    if surface not in list_emitter_surfaces():
        _log.error("cisternal.cli: unsupported validate surface %r", surface)
        raise SystemExit(2)

    report = load_asset_report(manifest=manifest, registry=registry)

    if report.conflicts:
        _log.error("cisternal.cli: validate failed — conflicts: %s", report.conflicts)
        raise SystemExit(1)

    if report.warnings:
        _log.error("cisternal.cli: validate failed — warnings: %s", report.warnings)
        raise SystemExit(1)

    if rust_parity:
        from cisternal.assets.bridge import (  # noqa: PLC0415
            conformance_expected_path,
            conformance_manifest_path,
            resolve_bundle_hash_bin,
            rust_surface_digest,
        )

        if resolve_bundle_hash_bin() is None:
            _log.error(
                "cisternal.cli: validate failed — set CISTERNAL_PRAXIA_ASSETS_BIN "
                "to the praxia bundle-hash binary for --rust-parity"
            )
            raise SystemExit(1)
        try:
            actual = rust_surface_digest(report.bundle, surface)
            repeat = rust_surface_digest(report.bundle, surface)
        except RuntimeError as exc:
            _log.error("cisternal.cli: validate failed — %s", exc)
            raise SystemExit(1) from exc
        if actual != repeat:
            _log.error(
                "cisternal.cli: validate failed — rust parity digest unstable "
                "(got %s then %s)",
                actual,
                repeat,
            )
            raise SystemExit(1)
        if manifest is not None and manifest.resolve() == conformance_manifest_path().resolve():
            expected_file = conformance_expected_path(surface)
            if not expected_file.is_file():
                _log.error(
                    "cisternal.cli: validate failed — missing conformance digest: %s",
                    expected_file,
                )
                raise SystemExit(1)
            expected = expected_file.read_text(encoding="utf-8").strip()
            if actual != expected:
                _log.error(
                    "cisternal.cli: validate failed — rust parity mismatch "
                    "(expected %s, got %s)",
                    expected,
                    actual,
                )
                raise SystemExit(1)
        raise SystemExit(0)

    if surface != "claude" and emit_command_bodies:
        _log.warning(
            "cisternal.cli: --emit-command-bodies ignored for surface %r",
            surface,
        )
        emit_command_bodies = False

    mode = "with_command_bodies" if emit_command_bodies else "names_only"

    # (#28) A manifest resolving to zero skills/agents/commands/mcp_servers
    # is a real failure regardless of golden-slug status -- checked here,
    # before the golden-slug skip below, so it can't be masked by (and isn't
    # conflated with) "this is an external manifest cisternal has no golden
    # digest for." Note this is a bundle-content check, not an emitted-file
    # count: every surface's plugin manifest wrapper (e.g. claude's
    # plugin.json) gets emitted even for a genuinely empty bundle, so "zero
    # files" never actually happens and isn't a usable signal here.
    bundle = report.bundle
    if not (bundle.skills or bundle.agents or bundle.commands or bundle.mcp_servers):
        _log.error(
            "cisternal.cli: validate failed — manifest has no skills, "
            "agents, commands, or mcp_servers (empty bundle)"
        )
        raise SystemExit(1)

    golden_slug = resolve_golden_slug(manifest)
    if golden_slug is None:
        # (#28) An external manifest isn't one of cisternal's own known
        # fixtures/self-manifest -- there's no golden digest cisternal could
        # possibly have pre-computed for it, so this was never a real
        # failure. Structural checks (conflicts/warnings) already passed
        # above; skip the golden-digest comparison and report success rather
        # than exit-1, matching how --rust-parity already only compares
        # against a golden digest for cisternal's own conformance manifest
        # and skips the comparison (without failing) otherwise.
        _log.info(
            "cisternal.cli: validate skipping golden-digest comparison for "
            "external manifest %s (not one of cisternal's own known "
            "fixtures) — structural checks passed",
            manifest,
        )
        raise SystemExit(0)

    try:
        golden_path = golden_digest_path(surface, mode, manifest=manifest)
    except ValueError as exc:
        _log.error("cisternal.cli: validate failed — %s", exc)
        raise SystemExit(1) from exc

    if not golden_path.is_file():
        _log.error("cisternal.cli: validate failed — missing golden digest: %s", golden_path)
        raise SystemExit(1)

    expected = golden_path.read_text(encoding="utf-8").strip()

    if use_native_cli:
        try:
            actual = _native_cli_surface_digest(
                registry=registry,
                manifest=manifest,
                surface=surface,
                emit_command_bodies=emit_command_bodies,
            )
        except RuntimeError as exc:
            _log.error("cisternal.cli: validate failed — %s", exc)
            raise SystemExit(1) from exc
    else:
        actual = surface_digest(
            report.bundle,
            surface,
            emit_command_bodies=emit_command_bodies,
        )

    if actual != expected:
        _log.error(
            "cisternal.cli: validate failed — digest mismatch (expected %s, got %s)",
            expected,
            actual,
        )
        raise SystemExit(1)


def _native_cli_surface_digest(
    *,
    registry: str,
    manifest: Path | None,
    surface: str,
    emit_command_bodies: bool,
) -> str:
    """Run ``cisternal assets export`` in a subprocess and hash emitted files."""
    from cisternal.export._hash import bundle_sha256  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cmd = [
            sys.executable,
            "-c",
            "import sys; from cisternal.cli import app; app(sys.argv[1:])",
            "assets",
            "export",
            "--registry",
            registry,
            "--out",
            str(out),
        ]
        if manifest is not None:
            cmd.extend(["--manifest", str(manifest)])
        if emit_command_bodies:
            cmd.append("--emit-command-bodies")
        cmd.extend(["--surface", surface])
        subprocess.run(cmd, check=True, capture_output=True)
        files: dict[str, str] = {}
        for path in out.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(out).as_posix()
            if "cisternal-provenance.json" in rel:
                continue
            files[rel] = path.read_text(encoding="utf-8")
        if not files:
            msg = "native export did not emit any hashable files"
            raise RuntimeError(msg)
        return bundle_sha256(files)
