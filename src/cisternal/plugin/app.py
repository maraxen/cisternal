"""Mountable ``plugin`` sub-app: ``<tool> plugin install|update|export|info``.

A tool that depends on cisternal mounts this into its own CLI, so its users
install the tool's agent plugin through the tool itself::

    # bathos/cli.py
    from cisternal.plugin import PluginSpec, plugin_app

    app.command(plugin_app(PluginSpec(name="bathos", package="bathos")))

    $ bth plugin install claude      # publish + register + install in Claude Code
    $ bth plugin update claude       # republish + update the installed plugin
    $ bth plugin export cursor --out ./dist/cursor   # direct surface export
    $ bth plugin info                # where the bundle and marketplace resolve from

Nothing here needs the ``cisternal`` CLI on PATH or the tool's source
checkout: the bundle comes from the first of

1. ``--manifest PATH`` (explicit);
2. the tool's source checkout -- a ``.praxia/manifest.toml`` at or above the
   imported package whose ``[plugin].name`` matches (editable installs);
3. the packaged snapshot ``<package>/<spec.snapshot>`` (wheel installs),
   written by ``cisternal assets snapshot`` and shipped as package data.

Fastmcp-free, like ``cisternal.cli``: importing this module never imports
fastmcp. ``PluginSpec.imports`` (if any) are imported only when a command runs.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.resources
import importlib.util
import json
import logging
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, NoReturn

import cyclopts

from cisternal.assets.bundle import AssetBundle, BundleMetadata, LoadReport

_log = logging.getLogger("cisternal.plugin")

# Surfaces `plugin install`/`update` can drive end to end. Every emitter
# surface can still be exported with `plugin export`.
INSTALLABLE_SURFACES = ("claude",)


@dataclass(frozen=True)
class PluginSpec:
    """How a tool's plugin bundle is found, named and versioned.

    name:         plugin name (Claude plugin id is ``<name>@<marketplace>``).
    package:      importable package that owns the plugin; anchors the
                  source-checkout search and the packaged snapshot.
    registry:     cisternal tool-registry partition whose commands merge in.
    imports:      modules imported before loading, for ``@cisternal.tool``
                  registration side effects (only matters for surfaces that
                  emit commands; claude does not).
    snapshot:     package-relative path of the packaged bundle snapshot.
    manifest:     checkout-root-relative manifest path.
    distribution: dist name for the version (default: ``package``).
    version:      fixed version (default: installed dist version, else manifest's).
    description:  override the manifest's description.
    cli:          the command users type for this tool (e.g. ``"bth"``), used in
                  ``update-all``'s pointer back to the tool (default: ``argv[0]``).
    """

    name: str
    package: str
    registry: str = "default"
    imports: tuple[str, ...] = ()
    snapshot: str = "agent_plugin.json"
    manifest: str = ".praxia/manifest.toml"
    distribution: str | None = None
    version: str | None = None
    description: str | None = None
    cli: str | None = None

    def update_command(self, subapp: str = "plugin") -> str:
        prog = self.cli
        if not prog:
            argv0 = Path(sys.argv[0]).name
            # `python -m pkg` gives __main__.py; a script path ends in .py.
            prog = argv0 if argv0 and not argv0.endswith(".py") else f"python -m {self.package}"
        return f"{prog} {subapp} update claude"


@dataclass(frozen=True)
class BundleSource:
    kind: str  # "manifest" (explicit), "checkout", or "snapshot"
    path: Path
    record: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        return f"{self.kind}: {self.path}"


class PluginError(Exception):
    """A user-facing failure; the CLI prints it and exits 1."""


# ---------------------------------------------------------------------------
# Locating and loading the bundle
# ---------------------------------------------------------------------------


def _package_dir(package: str) -> Path | None:
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))).resolve()


def _manifest_plugin_name(path: Path) -> str | None:
    try:
        plugin = tomllib.loads(path.read_text(encoding="utf-8")).get("plugin")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return str(plugin.get("name") or "") if isinstance(plugin, dict) else None


def _is_editable_install(spec: PluginSpec) -> bool | None:
    """PEP 610: True/False from the dist's ``direct_url.json``; None without metadata."""
    try:
        dist = importlib.metadata.distribution(spec.distribution or spec.package)
    except importlib.metadata.PackageNotFoundError:
        return None
    raw = dist.read_text("direct_url.json")
    if raw is None:
        return False  # installed from an index: a regular, non-editable install
    try:
        return bool(json.loads(raw).get("dir_info", {}).get("editable", False))
    except (ValueError, AttributeError):
        return False


def find_checkout_manifest(spec: PluginSpec) -> Path | None:
    """The tool's own manifest when the package is imported from a source checkout.

    Searches only for an editable install (PEP 610 ``direct_url.json``); a
    package with no dist metadata at all (bare ``PYTHONPATH``/``src`` on the
    path) is treated as a checkout unless it sits under ``site-packages`` or
    ``dist-packages``. Only a manifest whose ``[plugin].name`` is this plugin's
    is accepted, so a tree nested in some *other* project never picks up that
    project's manifest.
    """
    pkg_dir = _package_dir(spec.package)
    if pkg_dir is None:
        return None
    editable = _is_editable_install(spec)
    if editable is False:
        return None
    if editable is None and {"site-packages", "dist-packages"} & set(pkg_dir.parts):
        return None
    for directory in pkg_dir.parents:
        candidate = directory / spec.manifest
        if candidate.is_file() and _manifest_plugin_name(candidate) == spec.name:
            return candidate
    return None


def locate_bundle(spec: PluginSpec, *, manifest: Path | None = None) -> BundleSource:
    """Which bundle source wins (see module docstring). Raises :class:`PluginError`."""
    if manifest is not None:
        path = manifest.expanduser().resolve()
        if not path.is_file():
            raise PluginError(f"manifest not found: {path}")
        return BundleSource("manifest", path, {"manifest": str(path), "registry": spec.registry})

    checkout = find_checkout_manifest(spec)
    if checkout is not None:
        return BundleSource(
            "checkout", checkout, {"manifest": str(checkout), "registry": spec.registry}
        )

    try:
        resource = importlib.resources.files(spec.package).joinpath(spec.snapshot)
        found = resource.is_file()
    except (ModuleNotFoundError, TypeError):
        found = False
    if found:
        return BundleSource(
            "snapshot",
            Path(str(resource)),
            {"package": spec.package, "snapshot": spec.snapshot, "registry": spec.registry},
        )

    raise PluginError(
        f"no plugin bundle for {spec.name!r}: no --manifest, no {spec.manifest} in a "
        f"source checkout of {spec.package!r}, and no packaged snapshot "
        f"{spec.package}/{spec.snapshot} (build it with `cisternal assets snapshot`)"
    )


def _resolve_version(spec: PluginSpec, fallback: str) -> str:
    if spec.version:
        return spec.version
    try:
        return importlib.metadata.version(spec.distribution or spec.package)
    except importlib.metadata.PackageNotFoundError:
        return fallback


def load_bundle(
    spec: PluginSpec, *, manifest: Path | None = None
) -> tuple[AssetBundle, BundleSource]:
    """Load the plugin bundle, merged with the registry. Raises :class:`PluginError`.

    Unlike ``load_asset_report`` (never-raise), any warning or conflict is a
    failure here: a warning almost always means an asset silently dropped out
    of the bundle about to be installed.
    """
    from cisternal.assets.composite import merge_registry  # noqa: PLC0415
    from cisternal.assets.manifest import ManifestAssetSource  # noqa: PLC0415
    from cisternal.assets.snapshot import loads_snapshot  # noqa: PLC0415

    for module in spec.imports:
        try:
            importlib.import_module(module)
        except Exception as exc:
            raise PluginError(f"could not import {module!r}: {exc}") from exc

    source = locate_bundle(spec, manifest=manifest)
    if source.kind == "snapshot":
        try:
            base = LoadReport(bundle=loads_snapshot(source.path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise PluginError(f"{source.path}: {exc}") from exc
    else:
        base = ManifestAssetSource(source.path).load()

    meta = base.bundle.metadata
    metadata = BundleMetadata(
        name=spec.name,
        version=_resolve_version(spec, meta.version),
        description=spec.description if spec.description is not None else meta.description,
    )
    report = merge_registry(base, spec.registry, metadata=metadata)
    if report.warnings or report.conflicts:
        raise PluginError(
            f"bundle from {source.describe()} has problems -- "
            f"warnings: {list(report.warnings)}; conflicts: {list(report.conflicts)}"
        )
    return report.bundle, source


# ---------------------------------------------------------------------------
# Claude Code installer
# ---------------------------------------------------------------------------


def _claude(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except OSError as exc:
        raise PluginError(f"could not run {argv[0]!r}: {exc}") from exc


def _check(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise PluginError(f"`{what}` failed (exit {result.returncode}): {detail}")


def _registered_marketplaces(claude_bin: str) -> dict[str, dict[str, Any]]:
    """``{name: entry}`` from ``claude plugin marketplace list --json``."""
    result = _claude([claude_bin, "plugin", "marketplace", "list", "--json"])
    _check(result, "claude plugin marketplace list --json")
    try:
        return {m["name"]: m for m in json.loads(result.stdout)}
    except (ValueError, KeyError, TypeError) as exc:
        raise PluginError(f"could not parse `claude plugin marketplace list --json`: {exc}") from exc


def _marketplace_is_registered(root: Path, name: str, *, claude_bin: str) -> bool:
    """Whether *name* is already registered as *root*. Raises on any other registration.

    Only a ``directory`` marketplace at *root* counts: a same-named one from a
    remote repo (no local ``path``) or another directory would make
    ``plugin install <tool>@<name>`` install from there, silently ignoring the
    bundle just published into *root*.
    """
    entry = _registered_marketplaces(claude_bin).get(name)
    if entry is None:
        return False
    local = entry.get("path") if entry.get("source") == "directory" else None
    if local is None or Path(local).expanduser().resolve() != root:
        where = local or entry.get("repo") or entry.get("url") or entry.get("source") or "elsewhere"
        raise PluginError(
            f"Claude Code already has a marketplace named {name!r} ({where}), not {root}; "
            f"remove it (`{claude_bin} plugin marketplace remove {name}`) or point "
            "--marketplace at the directory it uses"
        )
    return True


def _target_marketplace_name(root: Path) -> str:
    """The name *root* has (or will get on first publish)."""
    from cisternal.export.marketplace import DEFAULT_MARKETPLACE_NAME  # noqa: PLC0415
    from cisternal.plugin.shared import marketplace_name  # noqa: PLC0415

    if (root / ".claude-plugin" / "marketplace.json").is_file():
        return marketplace_name(root)
    return DEFAULT_MARKETPLACE_NAME


def claude_install(
    bundle: AssetBundle,
    record: dict[str, Any],
    *,
    marketplace: Path,
    scope: str,
    claude_bin: str,
    require_installed: bool,
) -> None:
    """Install or update in Claude Code via the shared marketplace.

    Every refusal (a conflicting marketplace registration, ``update`` with
    nothing installed, an unreadable listing) is checked before anything is
    written, so a failing command leaves the marketplace untouched.
    """
    from cisternal.plugin.shared import (  # noqa: PLC0415
        handle_shadowed,
        installed_entries,
        publish_bundle,
    )

    mkt_name = _target_marketplace_name(marketplace)
    plugin_id = f"{bundle.metadata.name}@{mkt_name}"
    registered = _marketplace_is_registered(marketplace, mkt_name, claude_bin=claude_bin)
    entries = installed_entries(claude_bin)
    if entries is None:
        raise PluginError("could not list installed Claude Code plugins (see above)")
    installs = [e for e in entries if e.id == plugin_id]
    if require_installed and not installs:
        raise PluginError(f"{plugin_id} is not installed; run `plugin install claude` first")

    result = publish_bundle(bundle, marketplace=marketplace, source=record)
    print(f"published {result.name}@{result.version} -> {result.out}")
    handle_shadowed([result], prune=False)
    if not registered:
        _check(
            _claude([claude_bin, "plugin", "marketplace", "add", str(marketplace)]),
            f"claude plugin marketplace add {marketplace}",
        )
        print(f"claude: registered marketplace {mkt_name} -> {marketplace}")

    if not installs:
        _check(
            _claude([claude_bin, "plugin", "install", plugin_id, "--scope", scope]),
            f"claude plugin install {plugin_id} --scope {scope}",
        )
        print(f"installed {plugin_id} (scope={scope}); restart Claude Code to load it")
        return

    stale = [e for e in installs if e.version != result.version]
    if not stale:
        print(f"{plugin_id} is already up to date ({result.version})")
        return
    _check(
        _claude([claude_bin, "plugin", "marketplace", "update", mkt_name]),
        f"claude plugin marketplace update {mkt_name}",
    )
    # Update each stale install at the scope it was installed at. A
    # project/local install belonging to another project can fail from this
    # cwd; report it rather than abort the others.
    failures: list[str] = []
    for e in stale:
        argv = [claude_bin, "plugin", "update", plugin_id]
        if e.scope:
            argv += ["--scope", e.scope]
        upd = _claude(argv)
        if upd.returncode != 0:
            failures.append(f"scope={e.scope}: {(upd.stderr or upd.stdout).strip()}")
        else:
            print(f"{plugin_id} (scope={e.scope}): {e.version} -> {result.version}")
    if failures:
        raise PluginError(f"`claude plugin update {plugin_id}` failed for " + "; ".join(failures))
    print("restart Claude Code to load it")


# ---------------------------------------------------------------------------
# The sub-app
# ---------------------------------------------------------------------------

_SurfaceArg = Annotated[
    str,
    cyclopts.Parameter(help="Agent surface (install/update: claude; export: any emitter surface)."),
]
_ManifestOpt = Annotated[
    Path | None,
    cyclopts.Parameter(
        name=["--manifest"],
        help="Use this manifest.toml instead of the checkout manifest / packaged snapshot.",
    ),
]
_MarketplaceOpt = Annotated[
    Path | None,
    cyclopts.Parameter(
        name=["--marketplace"],
        help="Shared marketplace root (default: resolved; see `plugin info`).",
    ),
]
_ClaudeBinOpt = Annotated[
    str, cyclopts.Parameter(name=["--claude-bin"], help="claude CLI binary (default: 'claude').")
]
_DryRunOpt = Annotated[
    bool, cyclopts.Parameter(name=["--dry-run"], help="Show what would happen; change nothing.")
]


def _fail(exc: Exception) -> NoReturn:
    _log.error("cisternal.plugin: %s", exc)
    raise SystemExit(1) from exc


def _require_installable(surface: str) -> None:
    from cisternal.export.registry import list_emitter_surfaces  # noqa: PLC0415

    if surface in INSTALLABLE_SURFACES:
        return
    exportable = ", ".join(sorted(list_emitter_surfaces()))
    raise PluginError(
        f"no installer for surface {surface!r} (installable: {', '.join(INSTALLABLE_SURFACES)}). "
        f"Use `plugin export <surface> --out DIR` for: {exportable}"
    )


def plugin_app(spec: PluginSpec, *, name: str = "plugin") -> cyclopts.App:
    """Build the ``plugin`` sub-app for *spec*; mount it with ``app.command(...)``."""
    app = cyclopts.App(
        name=name,
        help=f"Install, update, or export the {spec.name} agent plugin.",
        version_flags=[],
    )

    def _install_or_update(
        surface: str,
        *,
        manifest: Path | None,
        marketplace: Path | None,
        scope: str,
        claude_bin: str,
        dry_run: bool,
        require_installed: bool,
    ) -> None:
        from cisternal.plugin.config import resolve_marketplace_root  # noqa: PLC0415

        try:
            _require_installable(surface)
            bundle, source = load_bundle(spec, manifest=manifest)
            if dry_run:
                from cisternal.plugin.config import (  # noqa: PLC0415
                    CONFIG_KEY,
                    GENERATED_DEFAULT,
                    marketplace_root_source,
                    user_config_path,
                )

                root, layer = marketplace_root_source(marketplace)
                if root is None and layer != "unconfigured":
                    raise PluginError(f"plugin marketplace is {layer}")
                if root is None:  # resolve would generate the config; dry-run only says so
                    root = Path(GENERATED_DEFAULT).expanduser()
                    print(f'would write {CONFIG_KEY} = "{GENERATED_DEFAULT}" to {user_config_path()}')
                print(f"bundle: {source.describe()}")
                print(f"would publish {bundle.metadata.name} into {root}/plugins/{spec.name}")
                verb = "update" if require_installed else "install (or update)"
                print(f"would {verb} {spec.name}@<marketplace> in Claude Code (scope={scope})")
                return
            root = resolve_marketplace_root(marketplace)
            # update-all defers to this command rather than rebuilding with
            # a different recipe (it would version from the manifest).
            record = {
                **source.record,
                "plugin": spec.name,
                "update_command": spec.update_command(name),
            }
            claude_install(
                bundle,
                record,
                marketplace=root,
                scope=scope,
                claude_bin=claude_bin,
                require_installed=require_installed,
            )
        except (PluginError, ValueError, RuntimeError, OSError) as exc:
            _fail(exc)

    @app.command(name="install")
    def install(
        surface: _SurfaceArg = "claude",
        /,
        *,
        scope: Annotated[
            str,
            cyclopts.Parameter(
                name=["--scope"], help="Claude install scope: user, project, local (default: user)."
            ),
        ] = "user",
        manifest: _ManifestOpt = None,
        marketplace: _MarketplaceOpt = None,
        claude_bin: _ClaudeBinOpt = "claude",
        dry_run: _DryRunOpt = False,
    ) -> None:
        """Publish this plugin and install it into the surface (updates if already installed)."""
        _install_or_update(
            surface, manifest=manifest, marketplace=marketplace, scope=scope,
            claude_bin=claude_bin, dry_run=dry_run, require_installed=False,
        )

    @app.command(name="update")
    def update(
        surface: _SurfaceArg = "claude",
        /,
        *,
        manifest: _ManifestOpt = None,
        marketplace: _MarketplaceOpt = None,
        claude_bin: _ClaudeBinOpt = "claude",
        dry_run: _DryRunOpt = False,
    ) -> None:
        """Republish this plugin and update the installed copy (fails if not installed)."""
        _install_or_update(
            surface, manifest=manifest, marketplace=marketplace, scope="user",
            claude_bin=claude_bin, dry_run=dry_run, require_installed=True,
        )

    @app.command(name="export")
    def export(
        surface: _SurfaceArg,
        /,
        *,
        out: Annotated[
            Path, cyclopts.Parameter(name=["--out"], help="Directory to write the bundle into.")
        ],
        manifest: _ManifestOpt = None,
        emit_command_bodies: Annotated[
            bool,
            cyclopts.Parameter(
                name=["--emit-command-bodies"], help="Emit commands/<name>.md (claude only)."
            ),
        ] = False,
        dry_run: _DryRunOpt = False,
    ) -> None:
        """Write this plugin's bundle for one surface into --out (files only; no install)."""
        from cisternal.export.registry import get_emitter, list_emitter_surfaces  # noqa: PLC0415
        from cisternal.export.write import write_bundle  # noqa: PLC0415

        try:
            if surface not in list_emitter_surfaces():
                raise PluginError(
                    f"unknown surface {surface!r}; choose from: "
                    f"{', '.join(sorted(list_emitter_surfaces()))}"
                )
            bundle, source = load_bundle(spec, manifest=manifest)
            emitter = get_emitter(
                surface, emit_command_bodies=emit_command_bodies and surface == "claude"
            )
            if emitter is None:
                raise PluginError(f"could not load emitter for surface {surface!r}")
            result = write_bundle(emitter.emit(bundle), out, dry_run=dry_run)
        except (PluginError, ValueError, OSError) as exc:
            _fail(exc)
        for path, sha256 in result.files:
            print(f"{path}  {sha256}" if dry_run else path)
        if not dry_run:
            print(f"exported {spec.name} ({surface}) from {source.describe()} -> {out}")

    @app.command(name="info")
    def info() -> None:
        """Show where the bundle and the marketplace resolve from (read-only)."""
        from cisternal.plugin.config import marketplace_root_source  # noqa: PLC0415

        try:
            source = locate_bundle(spec).describe()
        except PluginError as exc:
            source = f"none ({exc})"
        try:
            root, layer = marketplace_root_source()
        except ValueError as exc:
            root, layer = None, f"error: {exc}"
        print(f"plugin:      {spec.name} (package {spec.package})")
        print(f"bundle:      {source}")
        if root is None and layer == "unconfigured":
            from cisternal.plugin.config import (  # noqa: PLC0415
                CONFIG_KEY,
                GENERATED_DEFAULT,
                user_config_path,
            )

            layer = (
                f"unconfigured; the first install writes {CONFIG_KEY} = "
                f'"{GENERATED_DEFAULT}" to {user_config_path()}'
            )
        print(f"marketplace: {root if root else '-'} [{layer}]")
        print(f"installable: {', '.join(INSTALLABLE_SURFACES)}")

    return app
