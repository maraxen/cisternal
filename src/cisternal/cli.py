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
from typing import Annotated, Any

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

hook_app = cyclopts.App(
    name="hook",
    help="Claude Code client hook handlers.",
    version_flags=[],
)
app.command(hook_app)
app.command(hook_app, name="hooks")


@hook_app.command(name="pre-tool-use")
def hook_pre_tool_use() -> None:
    """PreToolUse hook entrypoint for Claude Code."""
    from cisternal.usage.cli_hook import main

    main(["pre-tool-use"])


@hook_app.command(name="post-tool-use")
def hook_post_tool_use() -> None:
    """PostToolUse hook entrypoint for Claude Code."""
    from cisternal.usage.cli_hook import main

    main(["post-tool-use"])


@hook_app.command(name="post-tool-failure")
def hook_post_tool_failure() -> None:
    """PostToolUseFailure hook entrypoint (RISK-01)."""
    from cisternal.usage.cli_hook import main

    main(["post-tool-failure"])


from cisternal.shadow.cli import shadow_app  # noqa: E402
app.command(shadow_app)

# cisternal's own plugin, through the same sub-app every tool can mount
# (`cisternal plugin install claude`). Dogfoods cisternal.plugin.
from cisternal.plugin import PluginSpec, plugin_app  # noqa: E402

app.command(
    plugin_app(PluginSpec(name="cisternal", package="cisternal", cli="cisternal"))
)


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
    metadata = BundleMetadata(
        name=resolved_name, version=resolved_version, description=""
    )
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
            _log.warning(
                "cisternal.cli: could not import %r; skipping", m, exc_info=True
            )

    bundle = _load_export_bundle(
        manifest=manifest, registry=registry, name=name, version=version
    )

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

    bundle = _load_export_bundle(
        manifest=manifest, registry=registry, name=name, version=version
    )

    if bundle.marketplace is None:
        _log.error(
            "cisternal.cli: manifest %s has no [plugin.marketplace] table; "
            "assets install requires one",
            manifest,
        )
        raise SystemExit(2)

    resolved_marketplace_name = marketplace_name or bundle.marketplace.name
    if marketplace_name and marketplace_name != bundle.marketplace.name:
        bundle = replace(
            bundle, marketplace=replace(bundle.marketplace, name=marketplace_name)
        )

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

    if (
        not (out / ".claude-plugin" / "plugin.json").is_file()
        or not (out / ".claude-plugin" / "marketplace.json").is_file()
    ):
        _log.error(
            "cisternal.cli: bundle write to %s appears incomplete "
            "(missing .claude-plugin/plugin.json or .claude-plugin/marketplace.json); "
            "refusing to run claude",
            out,
        )
        raise SystemExit(1)

    add_result = _run_claude(
        [claude_bin, "plugin", "marketplace", "add", str(out_abs)],
        claude_bin=claude_bin,
    )
    if add_result.returncode != 0:
        _log.error(
            "cisternal.cli: `claude plugin marketplace add` failed (exit %d): %s",
            add_result.returncode,
            add_result.stderr.strip(),
        )
        raise SystemExit(1)

    install_result = _run_claude(
        [claude_bin, "plugin", "install", plugin_id, "--scope", scope],
        claude_bin=claude_bin,
    )
    if install_result.returncode != 0:
        _log.error(
            "cisternal.cli: `claude plugin install` failed (exit %d): %s",
            install_result.returncode,
            install_result.stderr.strip(),
        )
        raise SystemExit(1)

    print(f"Installed {plugin_id} (scope={scope})")


def _run_claude(
    argv: list[str], *, claude_bin: str
) -> subprocess.CompletedProcess[str]:
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
        _log.error(
            "cisternal.cli: publish-shared failed — conflicts: %s", report.conflicts
        )
        raise SystemExit(1)
    if report.warnings:
        _log.error(
            "cisternal.cli: publish-shared failed — warnings: %s", report.warnings
        )
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
        cyclopts.Parameter(
            name=["--claude-bin"], help="Path to the claude CLI (default: 'claude')."
        ),
    ] = "claude",
    dry_run: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--dry-run"], help="List what would be republished; change nothing."
        ),
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
                tool_managed.append(
                    f"{plugin_dir.name}: run `{source['update_command']}`"
                )
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
        state = (
            f"{r.previous_version} -> {r.version}"
            if r.changed
            else f"unchanged ({r.version})"
        )
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
                out,
                "missing" if current is None else "stale",
                manifest,
                out,
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


@assets_app.command(name="skillmod")
def skillmod_assets(
    *,
    manifest: Annotated[
        list[Path],
        cyclopts.Parameter(
            name=["--manifest"],
            help="Plugin manifest.toml to migrate; repeat for several projects.",
            negative="",
        ),
    ],
    apply: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--apply"],
            help="Write the changes (default: dry run, print the plan only).",
        ),
    ] = False,
) -> None:
    """Fold each skill's legacy `triggers` into `when_to_use` (valid SKILL.md schema).

    Exit 0 when nothing failed verification, 1 otherwise. Review the result
    with `git diff` in each project before committing.
    """
    from cisternal.assets.skillmod import migrate_manifest  # noqa: PLC0415

    failed = False
    report: dict[str, list[dict[str, object]]] = {}
    for path in manifest:
        changes = migrate_manifest(path, apply=apply)
        failed |= any(c.status == "failed" for c in changes)
        report[str(path)] = [
            {
                "skill": c.skill,
                "status": c.status,
                "triggers": list(c.triggers),
                "listing_chars": c.listing_chars,
                "notes": c.notes,
            }
            for c in changes
        ]
    print(json.dumps({"applied": apply, "manifests": report}, indent=2))
    if failed:
        raise SystemExit(1)


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
    baseline_ref: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--baseline-ref"],
            help="Git ref to check for capability erosion in distinctive strings.",
        ),
    ] = None,
    report_only: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--report-only"],
            help="Route honesty lint violations to advisories (non-fatal, exit 0).",
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

    from cisternal.assets.validate import (  # noqa: PLC0415
        validate_bundle_guidance,
        validate_bundle_honesty,
    )

    guidance_warnings, guidance_advisories = validate_bundle_guidance(report.bundle)
    # The baseline ref is resolved in the manifest's repository (the plugin
    # root), not the process cwd, so the ref check lives in the validator.
    try:
        honesty_warnings, honesty_advisories = validate_bundle_honesty(
            report.bundle,
            manifest_path=manifest,
            baseline_ref=baseline_ref,
            report_only=report_only,
        )
    except ValueError as exc:
        _log.error("cisternal.cli: %s (%r)", exc, baseline_ref)
        raise SystemExit(2) from exc

    all_conflicts = list(report.conflicts)
    all_warnings = (
        list(report.warnings) + list(guidance_warnings) + list(honesty_warnings)
    )
    all_advisories = (
        list(report.advisories) + list(guidance_advisories) + list(honesty_advisories)
    )

    if all_conflicts:
        _log.error("cisternal.cli: validate failed — conflicts: %s", all_conflicts)
        raise SystemExit(1)

    if all_warnings:
        _log.error("cisternal.cli: validate failed — warnings: %s", all_warnings)
        raise SystemExit(1)

    # Soft listing-target advisories never change the exit code; they live
    # outside report.warnings, which publish/snapshot/plugin install also fail on.
    from cisternal.assets.skill_schema import listing_advisory  # noqa: PLC0415

    for skill in report.bundle.skills:
        advisory = listing_advisory(skill)
        if advisory is not None:
            _log.warning("cisternal.cli: advisory — %s", advisory)

    for advisory in all_advisories:
        _log.warning("cisternal.cli: advisory — %s", advisory)

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
        if (
            manifest is not None
            and manifest.resolve() == conformance_manifest_path().resolve()
        ):
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
        _log.error(
            "cisternal.cli: validate failed — missing golden digest: %s", golden_path
        )
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


# ---------------------------------------------------------------------------
# Usage & Pruning CLI Commands (Spec §C0, §C1)
# ---------------------------------------------------------------------------


@app.command(name="usage")
def usage(
    *,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON telemetry usage report to stdout.",
        ),
    ] = False,
    summary: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--summary"],
            help="Emit human-readable summary tables (default: enabled when not --json).",
        ),
    ] = True,
    sessions_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--sessions-dir", "--data-dir"],
            help="Explicit sessions directory override (layer 1 of derived-data resolver).",
        ),
    ] = None,
    projects_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--projects-dir", "--transcripts-dir"],
            help="Root directory for Claude Code projects transcripts (default: ~/.claude/projects).",
        ),
    ] = None,
    log_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--log-dir"],
            help="Directory containing cisternal server JSONL logs for duration enrichment.",
        ),
    ] = None,
    show_paths: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--show-paths"],
            help="Print resolved sessions/projects paths and winning resolution layer.",
        ),
    ] = False,
    project_root: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--project-root"],
            help="Anchor directory for pyproject.toml lookup (default: current working directory).",
        ),
    ] = None,
) -> None:
    """Analyze MCP, CLI, skill, and ToolSearch usage across session transcripts (Spec §C0)."""
    from cisternal.plugin.shared import claude_home
    from cisternal.usage.paths import resolve_sessions_dir
    from cisternal.usage.usage import ToolCallStats, compute_usage_summary

    resolved_sessions, sessions_layer = resolve_sessions_dir(
        data_dir=sessions_dir, project_dir=project_root
    )

    resolved_projects = projects_dir or (claude_home() / "projects")

    if show_paths:
        sess_str = str(resolved_sessions) if resolved_sessions else "off"
        print(f"Sessions directory: {sess_str} (layer: {sessions_layer})")
        print(f"Transcripts root:   {resolved_projects}")
        if log_dir:
            print(f"Server log directory: {log_dir}")
        if not json_output and not summary:
            return

    if sessions_layer == "off":
        if json_output:
            print(json.dumps({"status": "disabled", "sessions_layer": "off"}, indent=2))
        else:
            print("Sessions telemetry disabled (layer: off).")
        return

    # Always pass the resolved root: a missing --projects-dir yields an empty
    # report instead of silently analysing the default ~/.claude/projects.
    usage_summary = compute_usage_summary(
        projects_root=resolved_projects,
        log_dir=log_dir,
    )

    if json_output:
        combined_durations = {
            k: ToolCallStats(
                durations_ms=v.main_interactive.durations_ms
                + v.subagent_headless.durations_ms
            )
            for k, v in usage_summary.tools.items()
            if v.main_interactive.durations_ms or v.subagent_headless.durations_ms
        }
        doc: dict[str, Any] = {
            "version": "1.0",
            "metadata": {
                "sessions_total": usage_summary.total_sessions,
                "sessions_main_interactive": usage_summary.main_sessions_count,
                "sessions_subagent_headless": usage_summary.subagent_sessions_count,
                "calendar_days_span": round(usage_summary.calendar_days, 1),
                "paths": {
                    "sessions_dir": str(resolved_sessions)
                    if resolved_sessions
                    else None,
                    "sessions_layer": sessions_layer,
                    "projects_dir": str(resolved_projects),
                    "log_dir": str(log_dir) if log_dir else None,
                },
            },
            "stratified": {
                "main_interactive": {
                    "mcp_calls": {
                        k: v.main_interactive.total_calls
                        for k, v in usage_summary.tools.items()
                        if v.main_interactive.total_calls > 0
                    },
                    "cli_calls": {
                        k: v.main_interactive
                        for k, v in usage_summary.cli_verbs.items()
                        if v.main_interactive > 0
                    },
                    "skill_invocations": {
                        k: v.main_interactive
                        for k, v in usage_summary.skills.items()
                        if v.main_interactive > 0
                    },
                    "tool_search": {
                        "select_exact": usage_summary.toolsearch.select_exact.main_interactive,
                        "keyword": usage_summary.toolsearch.keyword_queries.main_interactive,
                    },
                },
                "subagent_headless": {
                    "mcp_calls": {
                        k: v.subagent_headless.total_calls
                        for k, v in usage_summary.tools.items()
                        if v.subagent_headless.total_calls > 0
                    },
                    "cli_calls": {
                        k: v.subagent_headless
                        for k, v in usage_summary.cli_verbs.items()
                        if v.subagent_headless > 0
                    },
                    "skill_invocations": {
                        k: v.subagent_headless
                        for k, v in usage_summary.skills.items()
                        if v.subagent_headless > 0
                    },
                    "tool_search": {
                        "select_exact": usage_summary.toolsearch.select_exact.subagent_headless,
                        "keyword": usage_summary.toolsearch.keyword_queries.subagent_headless,
                    },
                },
                "combined": {
                    "mcp_calls": {
                        k: v.total_calls for k, v in usage_summary.tools.items()
                    },
                    "cli_calls": {
                        k: v.total for k, v in usage_summary.cli_verbs.items()
                    },
                    "skill_invocations": {
                        k: v.total for k, v in usage_summary.skills.items()
                    },
                    "tool_search": {
                        "select_exact": usage_summary.toolsearch.select_exact.total,
                        "keyword": usage_summary.toolsearch.keyword_queries.total,
                    },
                    "e4_transitions": {
                        "error_trials": usage_summary.e4_transitions[
                            "error_to_cli"
                        ].trials,
                        "error_fallbacks": usage_summary.e4_transitions[
                            "error_to_cli"
                        ].successes,
                        "error_fallback_rate": round(
                            usage_summary.e4_transitions["error_to_cli"].rate, 4
                        ),
                        "error_wilson_ci": [
                            round(
                                usage_summary.e4_transitions[
                                    "error_to_cli"
                                ].ci_95.lower,
                                3,
                            ),
                            round(
                                usage_summary.e4_transitions[
                                    "error_to_cli"
                                ].ci_95.upper,
                                3,
                            ),
                        ],
                        "success_trials": usage_summary.e4_transitions[
                            "success_to_cli"
                        ].trials,
                        "success_fallbacks": usage_summary.e4_transitions[
                            "success_to_cli"
                        ].successes,
                        "success_fallback_rate": round(
                            usage_summary.e4_transitions["success_to_cli"].rate, 4
                        ),
                        "success_wilson_ci": [
                            round(
                                usage_summary.e4_transitions[
                                    "success_to_cli"
                                ].ci_95.lower,
                                3,
                            ),
                            round(
                                usage_summary.e4_transitions[
                                    "success_to_cli"
                                ].ci_95.upper,
                                3,
                            ),
                        ],
                    },
                },
            },
            # count, p50, p95 and mean all describe the same combined sample.
            "durations_ms": {
                k: {
                    "count": len(c.durations_ms),
                    "p50": c.p50,
                    "p95": c.p95,
                    "mean": c.mean_duration,
                }
                for k, c in combined_durations.items()
            },
        }
        print(json.dumps(doc, indent=2))
        return

    # Text summary output
    print("=== Cisternal Usage Telemetry Summary ===")
    print(
        f"Analyzed {usage_summary.total_sessions} sessions "
        f"({usage_summary.main_sessions_count} main interactive, "
        f"{usage_summary.subagent_sessions_count} subagent headless) "
        f"across {usage_summary.calendar_days:.1f} days.\n"
    )

    print("[MCP Tools]")
    if not usage_summary.tools:
        print("  (no MCP tool calls found)")
    else:
        print(f"{'Tool':<35} {'Main':>8} {'Subagent':>10} {'Total':>8}")
        print("-" * 65)
        for t_name, t_stat in sorted(usage_summary.tools.items()):
            print(
                f"{t_name:<35} {t_stat.main_interactive.total_calls:>8} "
                f"{t_stat.subagent_headless.total_calls:>10} {t_stat.total_calls:>8}"
            )
    print()

    print("[CLI Verbs]")
    if not usage_summary.cli_verbs:
        print("  (no matching CLI commands found)")
    else:
        print(f"{'Command':<35} {'Main':>8} {'Subagent':>10} {'Total':>8}")
        print("-" * 65)
        for c_name, c_stat in sorted(usage_summary.cli_verbs.items()):
            print(
                f"{c_name:<35} {c_stat.main_interactive:>8} "
                f"{c_stat.subagent_headless:>10} {c_stat.total:>8}"
            )
    print()

    print("[Skill Invocations]")
    if not usage_summary.skills:
        print("  (no skill invocations found)")
    else:
        print(f"{'Skill':<35} {'Main':>8} {'Subagent':>10} {'Total':>8}")
        print("-" * 65)
        for s_name, s_stat in sorted(usage_summary.skills.items()):
            print(
                f"{s_name:<35} {s_stat.main_interactive:>8} "
                f"{s_stat.subagent_headless:>10} {s_stat.total:>8}"
            )
    print()

    print("[ToolSearch Queries]")
    print(
        f"  select:<exact>: {usage_summary.toolsearch.select_exact.total} "
        f"(deferred only: {usage_summary.toolsearch.provenance.deferred_listing_only.total}, "
        f"prior mention: {usage_summary.toolsearch.provenance.prior_mention.total})"
    )
    print(f"  keyword:        {usage_summary.toolsearch.keyword_queries.total}\n")

    print("[E4 Transition Rates]")
    e4_err = usage_summary.e4_transitions["error_to_cli"]
    e4_succ = usage_summary.e4_transitions["success_to_cli"]
    print(
        f"  Fallback after ERROR:   {e4_err.successes}/{e4_err.trials} = "
        f"{e4_err.rate * 100:.1f}% (Wilson 95% {e4_err.ci_95.format_pct()})"
    )
    print(
        f"  Fallback after SUCCESS: {e4_succ.successes}/{e4_succ.trials} = "
        f"{e4_succ.rate * 100:.1f}% (Wilson 95% {e4_succ.ci_95.format_pct()})"
    )


@app.command(name="prune-list")
def prune_list(
    *,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON prune recommendations to stdout.",
        ),
    ] = False,
    sessions_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--sessions-dir", "--data-dir"],
            help="Explicit sessions directory override.",
        ),
    ] = None,
    projects_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--projects-dir"],
            help="Transcripts directory (default: ~/.claude/projects).",
        ),
    ] = None,
    days: Annotated[
        int,
        cyclopts.Parameter(
            name=["--days"],
            help="Calendar lookback floor in days (default: 14).",
        ),
    ] = 14,
    min_sessions: Annotated[
        int,
        cyclopts.Parameter(
            name=["--min-sessions"],
            help="Minimum session count floor (default: 20).",
        ),
    ] = 20,
    repo: Annotated[
        str | None,
        cyclopts.Parameter(
            name=["--repo"],
            help="Scope analysis to a single normalized repository key.",
        ),
    ] = None,
    project_root: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--project-root"],
            help="Anchor directory for pyproject.toml lookup.",
        ),
    ] = None,
) -> None:
    """Recommend server pruning (keep, drop, enable-per-project) based on active registrations and usage (Spec §C1)."""
    if days < 1 or min_sessions < 1:
        _log.error("cisternal.cli: --days and --min-sessions must be >= 1")
        raise SystemExit(2)

    from cisternal.plugin.shared import claude_home
    from cisternal.usage.paths import resolve_sessions_dir
    from cisternal.usage.prune import compute_prune_recommendations
    from cisternal.usage.registrations import scan_active_registrations
    from cisternal.usage.usage import compute_usage_summary

    resolved_sessions, _ = resolve_sessions_dir(
        data_dir=sessions_dir, project_dir=project_root
    )
    resolved_projects = projects_dir or (claude_home() / "projects")

    # Pass "off" through explicitly: sessions_dir=None would make the scanner
    # re-resolve (and write active_servers.json to the XDG default).
    registrations = scan_active_registrations(
        sessions_dir=resolved_sessions if resolved_sessions is not None else "off"
    )
    # Canonicalize transcript tool names against the same registered servers the
    # report buckets by; without them `mcp__plugin_<p>_<s>__<t>` keys as
    # `<p>_<s>/<t>` and a heavily used server `<s>` shows 0 calls.
    usage_summary = compute_usage_summary(
        projects_root=resolved_projects,
        declared_servers=registrations.servers,
    )

    report = compute_prune_recommendations(
        usage=usage_summary,
        registrations=registrations,
        min_sessions=min_sessions,
        min_days=days,
    )

    # Filter by repo if requested
    enable_per_project = report.enable_per_project
    if repo:
        enable_per_project = tuple(p for p in enable_per_project if p.top_repo == repo)

    if json_output:
        doc: dict[str, Any] = {
            "version": "1.0",
            "floor_cleared": report.floor_cleared,
            "suppression_reason": report.suppression_reason,
            "total_sessions": report.total_sessions,
            "calendar_days": round(report.calendar_days, 1),
            "keep": list(report.keep),
            "drop": [
                {
                    "server": d.server,
                    "plugin": d.plugin,
                    "rule_of_three_bound": round(d.rule_of_three_bound, 4),
                    "reason": d.reason,
                }
                for d in report.drop
            ],
            "enable_per_project": [
                {
                    "server": p.server,
                    "top_repo": p.top_repo,
                    "concentration_share": round(p.concentration_share, 4),
                    "repo_sessions": p.repo_sessions,
                    "reason": p.reason,
                }
                for p in enable_per_project
            ],
        }
        print(json.dumps(doc, indent=2))
        return

    print("=== Cisternal Server Prune Recommendations ===")
    if not report.floor_cleared:
        print(f"\n[Floor Not Met]\n{report.suppression_reason}\n")
        print("Active Registered Servers (all retained):")
        for srv in sorted(registrations.servers):
            print(f"  • {srv}")
        return

    print(
        f"\nAnalyzed {report.total_sessions} sessions over {report.calendar_days:.1f} days "
        f"(floor cleared: >= {min_sessions} sessions, >= {days} days).\n"
    )

    print("[Keep]")
    if not report.keep:
        print("  (none)")
    else:
        for srv in sorted(report.keep):
            print(f"  • {srv}")
    print()

    print("[Drop]")
    if not report.drop:
        print("  (none)")
    else:
        for d in report.drop:
            print(
                f"  • {d.server} (bound <= {d.rule_of_three_bound * 100:.1f}%) — {d.reason}"
            )
    print()

    print("[Enable Per Project]")
    if not enable_per_project:
        print("  (none)")
    else:
        for p in enable_per_project:
            print(
                f"  • {p.server} -> {p.top_repo} ({p.concentration_share * 100:.1f}% concentration)"
            )


@app.command(name="skill-coverage")
def skill_coverage(
    *,
    manifest: Annotated[
        tuple[Path, ...],
        cyclopts.Parameter(
            name=["--manifest"],
            help="Path to manifest.toml (repeatable, default: .praxia/manifest.toml).",
        ),
    ] = (Path(".praxia/manifest.toml"),),
    marketplace: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--marketplace"],
            help="Path to marketplace plugins directory (resolved read-only).",
        ),
    ] = None,
    situations: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--situations", "--situations-in"],
            help="Path to situations JSONL fixture to evaluate precision and recall against.",
        ),
    ] = None,
    situations_out: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--situations-out"],
            help="Path to write evaluated or mined opportunity situations (JSONL).",
        ),
    ] = None,
    threshold: Annotated[
        float,
        cyclopts.Parameter(
            name=["--threshold"],
            help="Certified precision point-estimate threshold (default: 0.80).",
        ),
    ] = 0.80,
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--json"],
            help="Emit machine-readable JSON coverage report.",
        ),
    ] = False,
    summary: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--summary"],
            help="Emit human-readable summary tables (default: enabled when not --json).",
        ),
    ] = True,
    projects_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--projects-dir", "--transcripts-dir"],
            help="Transcripts directory (default: ~/.claude/projects).",
        ),
    ] = None,
    sessions_dir: Annotated[
        Path | None,
        cyclopts.Parameter(
            name=["--sessions-dir"],
            help="Explicit sessions directory override.",
        ),
    ] = None,
) -> None:
    """Evaluate skill invocation coverage, opportunities, and precision/recall."""
    from cisternal.usage.coverage import (  # noqa: PLC0415
        evaluate_situation_set,
        load_monitored_skills,
        mine_skill_opportunities,
    )

    monitored_skills, unmonitored_skills = load_monitored_skills(
        manifest_paths=manifest,
        marketplace_dir=marketplace,
    )

    if situations is not None:
        report, records = evaluate_situation_set(
            situations_path=situations,
            skills=monitored_skills,
            threshold=threshold,
        )

        if situations_out:
            situations_out.parent.mkdir(parents=True, exist_ok=True)
            with open(situations_out, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec.to_dict()) + "\n")

        if json_output:
            doc = report.to_dict()
            doc["unmonitored_skills"] = [
                {"name": u.name, "path": u.path, "reason": u.reason}
                for u in unmonitored_skills
            ]
            print(json.dumps(doc, indent=2))
        elif summary:
            print("=== Cisternal Skill Coverage Evaluation ===")
            print(f"Monitored skills: {len(monitored_skills)}")
            print(f"Total situations: {report.total_situations}")
            print(f"Matched turns (n): {report.matched_turns}")
            print(f"True Positives (TP): {report.true_positives}")
            print(f"False Positives (FP): {report.false_positives}")
            print(f"False Negatives (FN): {report.false_negatives}")
            print(
                f"Precision (p_hat): {report.precision:.4f} {report.precision_ci.format_pct()}"
            )
            print(f"Recall: {report.recall:.4f} {report.recall_ci.format_pct()}")
            print(f"Threshold: {report.threshold:.2f}")
            print(f"Gate Status: {report.status}")
            print()
            print("Per-Skill Breakdown:")
            for s_name, stats in sorted(report.per_skill_stats.items()):
                print(
                    f"  • {s_name}: TP={stats['tp']}, FP={stats['fp']}, FN={stats['fn']}, "
                    f"Precision={stats['precision']:.2f} {stats['precision_ci']}"
                )
            if unmonitored_skills:
                print("\nUnmonitored Skills:")
                for u in unmonitored_skills:
                    print(f"  • {u.name} ({u.path}): {u.reason}")

        if report.status == "FAIL":
            raise SystemExit(1)
        return

    # Transcript opportunity mining
    from cisternal.plugin.shared import claude_home  # noqa: PLC0415

    p_dir = projects_dir or (claude_home() / "projects")
    opp_report = mine_skill_opportunities(
        projects_dir=p_dir if p_dir.is_dir() else None,
        skills=monitored_skills,
        sessions_dir=sessions_dir,
    )

    if situations_out and opp_report.mined_situations:
        situations_out.parent.mkdir(parents=True, exist_ok=True)
        with open(situations_out, "w", encoding="utf-8") as f:
            for sit in opp_report.mined_situations:
                f.write(json.dumps(sit) + "\n")

    if json_output:
        doc = opp_report.to_dict()
        doc["unmonitored_skills"] = [
            {"name": u.name, "path": u.path, "reason": u.reason}
            for u in unmonitored_skills
        ]
        print(json.dumps(doc, indent=2))
    elif summary:
        print("=== Cisternal Skill Opportunity Telemetry ===")
        print(f"Monitored skills: {len(monitored_skills)}")
        for s_name, stat in sorted(opp_report.skills.items()):
            lba_rate = (
                (stat.loaded_before_action / stat.invoked * 100)
                if stat.invoked > 0
                else 0.0
            )
            print(
                f"  • {s_name}: opportunities={stat.opportunities}, invoked={stat.invoked}, "
                f"loaded_before_action={stat.loaded_before_action} ({lba_rate:.1f}%), "
                f"missed={stat.missed_opportunities}, post_load_tool_calls={stat.post_load_tool_calls}"
            )
        if unmonitored_skills:
            print("\nUnmonitored Skills:")
            for u in unmonitored_skills:
                print(f"  • {u.name} ({u.path}): {u.reason}")


if __name__ == "__main__":
    app()
