"""Cisternal CLI — agent-asset export surface (spec §4, M3 Wave 3).

Provides:
    app — cyclopts App; entry point ``cisternal`` (pyproject [project.scripts]).

Subcommand tree:
    cisternal assets export [OPTIONS]
    cisternal assets inspect [OPTIONS]
    cisternal assets validate [OPTIONS]
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

    from cisternal.assets.source import registry_assets  # noqa: PLC0415

    snapshot = registry_assets(registry)
    if len(snapshot) == 0:
        _log.warning(
            "cisternal.cli: registry %r is empty; emitting empty bundle",
            registry,
        )
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
            help="Emit surface: claude, cursor, copilot, or antigravity (default: claude).",
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
    Both underlying commands are idempotent (confirmed live against claude
    2.1.227) — re-running install is safe.

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

    from cisternal.export.claude import ClaudeEmitter  # noqa: PLC0415
    from cisternal.export.write import write_bundle  # noqa: PLC0415

    files = ClaudeEmitter().emit(bundle)
    plugin_id = f"{bundle.metadata.name}@{resolved_marketplace_name}"

    if dry_run:
        for path in sorted(files):
            print(path)
        print(f"would run: {claude_bin} plugin marketplace add {out}")
        print(f"would run: {claude_bin} plugin install {plugin_id} --scope {scope}")
        return

    write_bundle(files, out, dry_run=False)

    add_result = subprocess.run(
        [claude_bin, "plugin", "marketplace", "add", str(out)],
        capture_output=True,
        text=True,
    )
    if add_result.returncode != 0:
        _log.error(
            "cisternal.cli: `claude plugin marketplace add` failed (exit %d): %s",
            add_result.returncode,
            add_result.stderr.strip(),
        )
        raise SystemExit(1)

    install_result = subprocess.run(
        [claude_bin, "plugin", "install", plugin_id, "--scope", scope],
        capture_output=True,
        text=True,
    )
    if install_result.returncode != 0:
        _log.error(
            "cisternal.cli: `claude plugin install` failed (exit %d): %s",
            install_result.returncode,
            install_result.stderr.strip(),
        )
        raise SystemExit(1)

    print(f"Installed {plugin_id} (scope={scope})")


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
    payload = report_to_dict(
        report,
        resolve_tools_flag=resolve_tools,
        surface=surface,
    )
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
            expected = conformance_expected_path(surface).read_text(encoding="utf-8").strip()
            if actual != expected:
                _log.error(
                    "cisternal.cli: validate failed — rust parity mismatch "
                    "(expected %s, got %s)",
                    expected,
                    actual,
                )
                raise SystemExit(1)
        raise SystemExit(0)

    mode = "with_command_bodies" if emit_command_bodies else "names_only"

    if resolve_golden_slug(manifest) is None:
        _log.error(
            "cisternal.cli: validate failed — unknown manifest for golden: %s",
            manifest,
        )
        raise SystemExit(1)

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
