# Marketplace/Install Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `cisternal assets export` output become a real, installed Claude Code plugin with one command, instead of files that sit inert on disk until someone manually registers them.

**Architecture:** Add an optional `MarketplaceAsset` to the existing `AssetBundle` IR, loaded from a new `[plugin.marketplace]` manifest table. `ClaudeEmitter` renders it as `.claude-plugin/marketplace.json` (a local marketplace listing the plugin itself via `source: "./"`) alongside the existing plugin bundle — no change to the Emitter's pure/deterministic/never-raise contract. A new `cisternal assets install` CLI command writes the bundle, then shells out to the real `claude` CLI (`plugin marketplace add`, `plugin install --scope`) to actually register and install it. Unlike `export`, `install` propagates real failures (non-zero exit) since it mutates live Claude Code state, not just files.

**Tech Stack:** Python 3.13, cyclopts (CLI), pytest, uv.

## Global Constraints

- Python `>=3.13`; use `uv run pytest` / `uv run python`, never bare `python`/`pytest` (matches this repo's existing `uv.lock`-managed environment).
- `Emitter.emit()` must remain PURE (zero I/O), DETERMINISTIC (identical bundle → identical dict), and NEVER-RAISE — this applies to the new marketplace.json emission exactly as it applies to every other file `ClaudeEmitter` writes. All I/O and subprocess calls belong only in the CLI layer (`cli.py`), never in `export/claude.py`.
- **Confirmed live** (spiked directly against `claude` CLI 2.1.227 on this machine, not assumed):
  - `claude plugin marketplace add <path>` exits `0` on first add and on idempotent re-add (message differs — "Successfully added" vs "already on disk" — but exit code is `0` both times). No stderr-string matching is needed to detect "already registered"; a bare `returncode != 0` check is sufficient and correct.
  - `claude plugin install <name>@<marketplace> [--scope user|project|local]` (`--scope` default is `user`, per `claude plugin install --help`) exits `0` on first install and on idempotent re-install, same as above.
  - `--scope project`, run with cwd inside a project, writes `{"enabledPlugins": {"<name>@<marketplace>": true}}` into that project's `.claude/settings.json` — confirmed by direct inspection of the resulting file.
  - `claude plugin uninstall <name>@<marketplace>` and `claude plugin marketplace remove <marketplace-name>` exist for manual rollback (not built by this plan — mention in docs only).
- Existing `export`/`inspect`/`validate` commands always exit `0` (warnings, not failures) — `install` is a deliberate, documented exception to that convention because it mutates real external state.

---

### Task 1: `MarketplaceAsset` dataclass on `AssetBundle`

**Files:**
- Modify: `src/cisternal/assets/bundle.py`
- Test: `tests/test_assets_bundle_marketplace.py` (new)

**Interfaces:**
- Produces: `cisternal.assets.bundle.MarketplaceAsset(name: str, owner_name: str = "", owner_email: str = "", owner_url: str = "")` — frozen, slotted dataclass. `AssetBundle.marketplace: MarketplaceAsset | None = None` new field, default `None`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for MarketplaceAsset — local Claude Code marketplace metadata on AssetBundle."""

from __future__ import annotations

import pytest

from cisternal.assets.bundle import AssetBundle, BundleMetadata, MarketplaceAsset


def _meta() -> BundleMetadata:
    return BundleMetadata(name="test", version="1.0.0")


def test_marketplace_asset_is_frozen() -> None:
    marketplace = MarketplaceAsset(name="test-marketplace", owner_name="Someone")
    with pytest.raises(AttributeError):
        marketplace.name = "other"  # type: ignore[misc]


def test_marketplace_asset_defaults() -> None:
    marketplace = MarketplaceAsset(name="test-marketplace")
    assert marketplace.owner_name == ""
    assert marketplace.owner_email == ""
    assert marketplace.owner_url == ""


def test_bundle_marketplace_defaults_to_none() -> None:
    bundle = AssetBundle(metadata=_meta())
    assert bundle.marketplace is None


def test_bundle_marketplace_roundtrips() -> None:
    marketplace = MarketplaceAsset(name="test-marketplace", owner_name="Someone")
    bundle = AssetBundle(metadata=_meta(), marketplace=marketplace)
    assert bundle.marketplace is marketplace


def test_bundle_with_marketplace_is_hashable() -> None:
    bundle = AssetBundle(
        metadata=_meta(),
        marketplace=MarketplaceAsset(name="test-marketplace"),
    )
    hash(bundle)  # must not raise
```

Write this to `tests/test_assets_bundle_marketplace.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_assets_bundle_marketplace.py -v`
Expected: FAIL with `ImportError: cannot import name 'MarketplaceAsset'`

- [ ] **Step 3: Add `MarketplaceAsset` and wire the `marketplace` field**

In `src/cisternal/assets/bundle.py`, add (near `McpAsset`, before `AssetBundle`):

```python
@dataclass(frozen=True, slots=True)
class MarketplaceAsset:
    """Local Claude Code marketplace metadata for self-installing a plugin.

    When present on a bundle, ``ClaudeEmitter`` renders a
    ``.claude-plugin/marketplace.json`` alongside the plugin bundle, listing
    the plugin itself via ``source: "./"`` — a single-repo, self-contained
    marketplace+plugin pair, installable via ``cisternal assets install``.
    """

    name: str
    owner_name: str = ""
    owner_email: str = ""
    owner_url: str = ""
```

In `AssetBundle`, add the field (after `hook_specs`):

```python
    hook_specs: tuple[HookSpecAsset, ...] = ()
    marketplace: MarketplaceAsset | None = None
```

No `__post_init__` change needed — a single optional object has no sort invariant.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_assets_bundle_marketplace.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/cisternal/assets/bundle.py tests/test_assets_bundle_marketplace.py
git commit -m "feat(assets): add MarketplaceAsset to AssetBundle IR"
```

---

### Task 2: Load `[plugin.marketplace]` from the manifest

**Files:**
- Modify: `src/cisternal/assets/manifest.py`
- Test: `tests/test_assets_manifest.py` (add cases)

**Interfaces:**
- Consumes: `MarketplaceAsset` from Task 1 (`cisternal.assets.bundle.MarketplaceAsset`).
- Produces: `_load_marketplace(plugin: dict[str, object], plugin_name: str) -> MarketplaceAsset | None`, wired into `ManifestAssetSource.load()`'s `AssetBundle(...)` construction as `marketplace=...`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_assets_manifest.py`:

```python
def test_manifest_loads_marketplace_table(tmp_path: Path) -> None:
    """[plugin.marketplace] loads into AssetBundle.marketplace."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"

[plugin.marketplace]
name = "demo-marketplace"

[plugin.marketplace.owner]
name = "Demo Owner"
email = "demo@example.com"
""",
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    marketplace = report.bundle.marketplace
    assert marketplace is not None
    assert marketplace.name == "demo-marketplace"
    assert marketplace.owner_name == "Demo Owner"
    assert marketplace.owner_email == "demo@example.com"
    assert marketplace.owner_url == ""


def test_manifest_marketplace_name_defaults_to_plugin_name(tmp_path: Path) -> None:
    """[plugin.marketplace] with no `name` falls back to [plugin].name."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"

[plugin.marketplace]
""",
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert report.bundle.marketplace is not None
    assert report.bundle.marketplace.name == "demo-plugin"


def test_manifest_without_marketplace_table_leaves_it_none() -> None:
    """No [plugin.marketplace] table → bundle.marketplace stays None."""
    report = ManifestAssetSource(MANIFEST).load()
    assert report.bundle.marketplace is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_assets_manifest.py -k marketplace -v`
Expected: FAIL — `AttributeError: 'AssetBundle' object has no attribute 'marketplace'` is already gone after Task 1, so this should instead FAIL on an assertion (`marketplace is None` when a table was provided), since `_load_marketplace` doesn't exist/isn't wired yet.

- [ ] **Step 3: Implement `_load_marketplace` and wire it in**

In `src/cisternal/assets/manifest.py`, add the import:

```python
from cisternal.assets.bundle import (
    AgentAsset,
    AssetBundle,
    BundleMetadata,
    HookSpecAsset,
    LoadReport,
    McpAsset,
    MarketplaceAsset,
    SkillAsset,
)
```

Add a loader function (near `_load_mcp`):

```python
def _load_marketplace(plugin: dict[str, object], plugin_name: str) -> MarketplaceAsset | None:
    marketplace = plugin.get("marketplace")
    if not isinstance(marketplace, dict):
        return None
    name = str(marketplace.get("name") or plugin_name or "")
    if not name:
        return None
    owner = marketplace.get("owner")
    owner_name = owner_email = owner_url = ""
    if isinstance(owner, dict):
        owner_name = str(owner.get("name") or "")
        owner_email = str(owner.get("email") or "")
        owner_url = str(owner.get("url") or "")
    return MarketplaceAsset(
        name=name,
        owner_name=owner_name,
        owner_email=owner_email,
        owner_url=owner_url,
    )
```

In `ManifestAssetSource.load()`, after the existing `mcp_servers = _load_mcp(plugin, name)` line, add:

```python
        marketplace = _load_marketplace(plugin, name)
```

And add `marketplace=marketplace` to the `AssetBundle(...)` construction a few lines below.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_assets_manifest.py -v`
Expected: PASS (all tests in the file, including the 3 new ones — confirms no regression on the other manifest-loading tests)

- [ ] **Step 5: Commit**

```bash
git add src/cisternal/assets/manifest.py tests/test_assets_manifest.py
git commit -m "feat(assets): load [plugin.marketplace] table from manifest.toml"
```

---

### Task 3: `ClaudeEmitter` renders `.claude-plugin/marketplace.json`

**Files:**
- Modify: `src/cisternal/export/claude.py`
- Test: `tests/test_export_claude.py` (add cases)

**Interfaces:**
- Consumes: `bundle.marketplace: MarketplaceAsset | None` (Task 1), `bundle.metadata.name` (existing).
- Produces: `.claude-plugin/marketplace.json` key in the `ClaudeEmitter.emit()` output dict when `bundle.marketplace is not None`; absent otherwise.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_export_claude.py` (add `MarketplaceAsset` to the existing `from cisternal.assets.bundle import (...)` block):

```python
def test_emit_includes_marketplace_json_when_set() -> None:
    bundle = AssetBundle(
        metadata=_meta(name="pull-books"),
        marketplace=MarketplaceAsset(name="pull-books-marketplace", owner_name="Marielle Russo"),
    )
    files = ClaudeEmitter().emit(bundle)
    assert ".claude-plugin/marketplace.json" in files
    marketplace = json.loads(files[".claude-plugin/marketplace.json"])
    assert marketplace["name"] == "pull-books-marketplace"
    assert marketplace["owner"]["name"] == "Marielle Russo"
    assert marketplace["plugins"] == [{"name": "pull-books", "source": "./"}]


def test_emit_omits_marketplace_json_when_unset() -> None:
    files = ClaudeEmitter().emit(_bundle())
    assert ".claude-plugin/marketplace.json" not in files


def test_marketplace_json_covered_by_provenance_digest() -> None:
    bundle = AssetBundle(
        metadata=_meta(name="pull-books"),
        marketplace=MarketplaceAsset(name="pull-books-marketplace"),
    )
    files_a = ClaudeEmitter().emit(bundle)
    files_b = ClaudeEmitter().emit(bundle)
    assert files_a == files_b
    assert files_a[_PROVENANCE_PATH] == files_b[_PROVENANCE_PATH]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_export_claude.py -k marketplace -v`
Expected: FAIL — `test_emit_includes_marketplace_json_when_set` fails with a `KeyError`/assertion (`.claude-plugin/marketplace.json` not in files).

- [ ] **Step 3: Implement marketplace.json emission**

In `src/cisternal/export/claude.py`, add the path constant near the others:

```python
_MARKETPLACE_JSON_PATH = ".claude-plugin/marketplace.json"
```

In `ClaudeEmitter.emit()`, after the `if bundle.mcp_servers:` block and before the `if self._emit_command_bodies:` block, add:

```python
        if bundle.marketplace is not None:
            owner: dict[str, str] = {
                "name": bundle.marketplace.owner_name or bundle.metadata.name,
            }
            if bundle.marketplace.owner_email:
                owner["email"] = bundle.marketplace.owner_email
            if bundle.marketplace.owner_url:
                owner["url"] = bundle.marketplace.owner_url
            marketplace_obj = {
                "name": bundle.marketplace.name,
                "owner": owner,
                "plugins": [{"name": bundle.metadata.name, "source": "./"}],
            }
            files[_MARKETPLACE_JSON_PATH] = json.dumps(
                marketplace_obj, sort_keys=True, indent=2
            )
```

This sits before the provenance digest computation, so `.claude-plugin/marketplace.json` is correctly included in the hashed non-provenance file set (it's real bundle content, not a build artifact). Only touches the legacy (non-`rust_parity`) branch — `emit_claude_rust_parity` is untouched, matching this feature's scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_export_claude.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/cisternal/export/claude.py tests/test_export_claude.py
git commit -m "feat(export): render .claude-plugin/marketplace.json when bundle.marketplace is set"
```

---

### Task 4: `cisternal assets install` CLI command

**Files:**
- Modify: `src/cisternal/cli.py`
- Test: `tests/test_cli_assets_install.py` (new)

**Interfaces:**
- Consumes: `ClaudeEmitter` (Task 3), `write_bundle` (`cisternal.export.write`), `load_asset_report` (`cisternal.assets.load`).
- Produces: `_load_export_bundle(*, manifest: Path | None, registry: str, name: str | None, version: str | None) -> AssetBundle` (extracted, reused by both `export` and the new `install`); `cisternal assets install` cyclopts command.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_assets_install.py`:

```python
"""Tests for `cisternal assets install` — export + real claude CLI registration."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

_FAKE_CLAUDE_SCRIPT = """#!/bin/sh
echo "$@" >> "$FAKE_CLAUDE_LOG"
if [ "$1" = "plugin" ] && [ "$2" = "$FAKE_CLAUDE_FAIL_STEP" ]; then
  echo "simulated failure at $2" >&2
  exit 1
fi
exit 0
"""


def _write_fake_claude(tmp_path: Path) -> Path:
    script = tmp_path / "fake-claude"
    script.write_text(_FAKE_CLAUDE_SCRIPT, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _write_manifest_with_marketplace(tmp_path: Path) -> Path:
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"

[plugin.marketplace]
name = "demo-marketplace"
""",
        encoding="utf-8",
    )
    return manifest_dir / "manifest.toml"


def _write_manifest_without_marketplace(tmp_path: Path) -> Path:
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "demo-plugin"
version = "1.0.0"
""",
        encoding="utf-8",
    )
    return manifest_dir / "manifest.toml"


def _invoke_app(args: list[str], *, exit_code: int) -> None:
    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(args)
    assert exc_info.value.code == exit_code, (
        f"Expected exit {exit_code}; got: {exc_info.value.code}"
    )


def test_install_requires_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _invoke_app(["assets", "install", "--out", str(out_dir)], exit_code=2)


def test_install_requires_marketplace_table(tmp_path: Path) -> None:
    manifest = _write_manifest_without_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _invoke_app(
        ["assets", "install", "--manifest", str(manifest), "--out", str(out_dir)],
        exit_code=2,
    )


def test_install_dry_run_writes_nothing_and_prints_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--dry-run",
        ],
        exit_code=0,
    )

    assert list(out_dir.rglob("*")) == []
    captured = capsys.readouterr()
    assert "would run: claude plugin marketplace add" in captured.out
    assert "would run: claude plugin install demo-plugin@demo-marketplace --scope project" in captured.out


def test_install_runs_marketplace_add_and_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    log_path = tmp_path / "fake-claude.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    monkeypatch.delenv("FAKE_CLAUDE_FAIL_STEP", raising=False)

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
        ],
        exit_code=0,
    )

    assert (out_dir / ".claude-plugin" / "plugin.json").exists()
    assert (out_dir / ".claude-plugin" / "marketplace.json").exists()

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert log_lines[0] == f"plugin marketplace add {out_dir}"
    assert log_lines[1] == "plugin install demo-plugin@demo-marketplace --scope project"

    captured = capsys.readouterr()
    assert "Installed demo-plugin@demo-marketplace" in captured.out


def test_install_propagates_marketplace_add_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake-claude.log"))
    monkeypatch.setenv("FAKE_CLAUDE_FAIL_STEP", "marketplace")

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
        ],
        exit_code=1,
    )


def test_install_propagates_plugin_install_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "fake-claude.log"))
    monkeypatch.setenv("FAKE_CLAUDE_FAIL_STEP", "install")

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
        ],
        exit_code=1,
    )


def test_install_marketplace_name_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_manifest_with_marketplace(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fake_claude = _write_fake_claude(tmp_path)
    log_path = tmp_path / "fake-claude.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    monkeypatch.delenv("FAKE_CLAUDE_FAIL_STEP", raising=False)

    _invoke_app(
        [
            "assets",
            "install",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
            "--claude-bin",
            str(fake_claude),
            "--marketplace-name",
            "override-marketplace",
            "--scope",
            "user",
        ],
        exit_code=0,
    )

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert log_lines[1] == "plugin install demo-plugin@override-marketplace --scope user"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_assets_install.py -v`
Expected: FAIL — `assert exc_info.value.code == 2` fails because `cisternal assets install` doesn't exist yet (cyclopts will error with an unknown-subcommand exit, or `AttributeError`/import error depending on how cyclopts reports it — either way, not the expected passing behavior).

- [ ] **Step 3: Extract `_load_export_bundle` and implement `install`**

In `src/cisternal/cli.py`, replace the bundle-resolution block inside `export()` (from `from cisternal.assets.bundle import AssetBundle, BundleMetadata, CommandAsset` through the `bundle = AssetBundle(metadata=metadata, commands=commands)` line) with a call to a new extracted helper, and add that helper plus the new `install` command.

Extracted helper (place above `export()`):

```python
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
```

In `export()`, replace the whole `if manifest is not None: ... else: ...` bundle-building block with:

```python
    bundle = _load_export_bundle(manifest=manifest, registry=registry, name=name, version=version)
```

(Keep everything else in `export()` — the emitter/`write_bundle` section below — unchanged.)

Add the new command (after `export()`, before `inspect_assets()`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_assets_install.py -v`
Expected: PASS (8 tests)

Then run the full existing CLI/export test suite to confirm the `export()` refactor caused no regression:

Run: `uv run pytest tests/test_cli_assets.py tests/test_cli_assets_export_surface.py tests/test_cli_assets_inspect.py tests/test_cli_assets_validate.py tests/test_cli_assets_validate_conflict.py -v`
Expected: PASS (all existing tests, unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/cisternal/cli.py tests/test_cli_assets_install.py
git commit -m "feat(cli): add \`cisternal assets install\` -- export + real claude plugin registration"
```

---

### Task 5: README docs for `assets install` and `[plugin.marketplace]`

**Files:**
- Modify: `README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Add an "Install as a real plugin" subsection**

In `README.md`, under the existing `## Agent-asset export` section, after the `cisternal assets inspect` / `cisternal assets validate` example block, add:

```markdown
### Install as a real Claude Code plugin

`cisternal assets export` only writes files — nothing picks them up until
something registers them. `cisternal assets install` does both steps: it
writes the bundle, then drives the real `claude` CLI to register it as a
local marketplace and install it, so its skills/agents/MCP config actually
load in a Claude Code session.

Requires a `[plugin.marketplace]` table in your manifest:

\```toml
[plugin]
name = "my-plugin"
version = "1.0.0"

[plugin.marketplace]
name = "my-plugin-marketplace"

[plugin.marketplace.owner]
name = "Your Name"
\```

\```bash
cisternal assets install --manifest .praxia/manifest.toml
# writes the bundle to ./ , then runs:
#   claude plugin marketplace add .
#   claude plugin install my-plugin@my-plugin-marketplace --scope project
\```

Both underlying `claude` commands are idempotent — re-running `install` is
safe. `--scope project` (the default) registers the plugin in this
project's `.claude/settings.json`, so anyone who clones the repo needs only
one manual `claude plugin install my-plugin@my-plugin-marketplace` (Claude
Code's own trust-on-first-use step — not something this command tries to
bypass). To remove it later: `claude plugin uninstall
my-plugin@my-plugin-marketplace` and `claude plugin marketplace remove
my-plugin-marketplace`.
```

- [ ] **Step 2: Verify the doc renders sensibly**

Run: `uv run python -c "import pathlib; print(pathlib.Path('README.md').read_text()[:6000])"` and read it — confirm no broken code fences, the new section sits logically after the existing export examples.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document \`cisternal assets install\` and [plugin.marketplace]"
```

---

### Task 6: Open the PR

**Files:** none (git/gh only).

- [ ] **Step 1: Run the full test suite and lint**

Run: `uv run pytest -v`
Expected: PASS (all tests, including the 3 tasks above plus the full pre-existing suite)

Run: `uv run ruff check src/cisternal/assets/bundle.py src/cisternal/assets/manifest.py src/cisternal/export/claude.py src/cisternal/cli.py tests/test_assets_bundle_marketplace.py tests/test_cli_assets_install.py`
Expected: no findings (fix any that appear before proceeding)

- [ ] **Step 2: Create a feature branch**

```bash
git checkout -b feat/marketplace-install
```

(Run this first — Tasks 1-5's commits above should actually happen on this branch. If they were made on `main` by mistake, `git branch feat/marketplace-install && git checkout feat/marketplace-install` still captures them; just don't push `main` directly.)

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/marketplace-install
gh pr create --title "Add marketplace.json emission + \`cisternal assets install\`" --body "$(cat <<'EOF'
## Summary
- New `MarketplaceAsset` on `AssetBundle`, loaded from an optional `[plugin.marketplace]` manifest table
- `ClaudeEmitter` renders `.claude-plugin/marketplace.json` (a local, self-contained marketplace listing the plugin via `source: "./"`) when `bundle.marketplace` is set
- New `cisternal assets install` command: writes the bundle, then drives the real `claude` CLI (`plugin marketplace add`, `plugin install --scope`) to actually register+install it — confirmed live against claude 2.1.227 that both underlying commands are idempotent, so no fragile stderr string-matching is needed
- Unlike `export`/`inspect`/`validate`, `install` exits non-zero on real failure, since it mutates live Claude Code state

## Test plan
- [x] `uv run pytest -v` — full suite passes
- [x] `uv run ruff check` — clean
- [x] Manually spiked `claude plugin marketplace add` / `claude plugin install` / idempotent re-runs / `--scope project` settings.json shape / uninstall+marketplace remove cleanup against a throwaway plugin, live, before writing the CLI command's error handling

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Report the PR URL**

Print the URL `gh pr create` returns so it can be handed back to the user.
