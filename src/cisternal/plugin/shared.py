"""Shared Claude Code marketplace: publish one bundle, refresh installs, find shadows.

Used by both ``cisternal assets publish-shared`` / ``update-all`` (manifest
in hand) and the mountable ``<tool> plugin`` sub-app (bundle loaded from a
manifest *or* a packaged snapshot). Everything here takes an already-loaded
:class:`AssetBundle`; where the bundle came from is recorded in the
``cisternal-source.json`` sidecar so ``update-all`` knows how to rebuild it.

Fastmcp-free, like ``cisternal.cli``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from cisternal.assets.bundle import AssetBundle

_log = logging.getLogger("cisternal.plugin")

# Written next to plugin.json by every shared publish; read by update-all.
# Claude Code ignores unknown files in .claude-plugin/.
SOURCE_SIDECAR = "cisternal-source.json"


@dataclass(frozen=True)
class PublishResult:
    name: str
    previous_version: str | None
    version: str
    out: Path
    skill_names: tuple[str, ...] = ()
    agent_names: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.previous_version != self.version


def read_plugin_version(plugin_dir: Path) -> str | None:
    try:
        doc = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = doc.get("version") if isinstance(doc, dict) else None
    return version if isinstance(version, str) else None


def marketplace_name(marketplace: Path) -> str:
    """The ``name`` in ``<marketplace>/.claude-plugin/marketplace.json``. Raises ``ValueError``."""
    path = marketplace / ".claude-plugin" / "marketplace.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["name"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"cannot read marketplace name from {path}: {exc}"
        raise ValueError(msg) from exc


def publish_bundle(
    bundle: AssetBundle,
    *,
    marketplace: Path,
    source: dict[str, Any],
) -> PublishResult:
    """Emit *bundle* for Claude into ``<marketplace>/plugins/<name>/`` and list it.

    Scrubs the destination first (the asset writer does not prune), versions
    the bundle as ``<version>+<content digest>`` so Claude Code's
    version-keyed cache is busted exactly when content changes, writes
    *source* as the ``cisternal-source.json`` sidecar, and merges the
    marketplace entry under the flock'd atomic read-modify-write.
    """
    from cisternal.export.marketplace import (  # noqa: PLC0415
        content_version,
        default_seed,
        merge_marketplace_entry,
        plugin_output_dir,
    )
    from cisternal.export.registry import get_emitter  # noqa: PLC0415
    from cisternal.export.write import write_bundle  # noqa: PLC0415

    emitter = get_emitter("claude")
    if emitter is None:
        msg = "claude emitter is not registered"
        raise RuntimeError(msg)

    # The standalone [plugin.marketplace] table is for single-plugin
    # self-install; a shared marketplace owns its own marketplace.json.
    base = replace(bundle, marketplace=None)
    # Two passes: the first (base version) derives a content digest; the
    # second bakes the final, cache-busting version into plugin.json.
    version = content_version(base.metadata.version, emitter.emit(base))
    versioned = replace(base, metadata=replace(base.metadata, version=version))
    files = emitter.emit(versioned)

    name = base.metadata.name
    out = plugin_output_dir(marketplace, name)
    previous_version = read_plugin_version(out)

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    write_bundle(files, out)
    (out / ".claude-plugin" / SOURCE_SIDECAR).write_text(
        json.dumps(source, indent=2) + "\n", encoding="utf-8"
    )

    merge_marketplace_entry(
        marketplace,
        {
            "name": name,
            "source": f"./plugins/{name}",
            "description": base.metadata.description,
        },
        seed=default_seed(),
        readme_template=MARKETPLACE_README_TEMPLATE,
    )
    return PublishResult(
        name=name,
        previous_version=previous_version,
        version=version,
        out=out,
        skill_names=tuple(s.name for s in versioned.skills),
        agent_names=tuple(a.name for a in versioned.agents),
    )


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def find_shadowed(result: PublishResult, home: Path) -> list[Path]:
    """User-level copies that duplicate what this plugin already ships.

    Claude Code lists a plugin's skills as ``<plugin>:<skill>``; a same-named
    ``<home>/skills/<skill>/`` is a second, unnamespaced listing of the
    same skill (and wins over the plugin's copy when they drift). Agents are
    matched by the ``<plugin>-<agent>.md`` name that legacy per-tool exporters
    wrote, so a user's own same-named agent is never touched.
    """
    found = [
        home / "skills" / skill
        for skill in result.skill_names
        if (home / "skills" / skill).exists()
    ]
    found += [
        home / "agents" / f"{result.name}-{agent}.md"
        for agent in result.agent_names
        if (home / "agents" / f"{result.name}-{agent}.md").is_file()
    ]
    return found


def handle_shadowed(results: list[PublishResult], *, prune: bool) -> None:
    """Report (or with *prune*, move into a backup) copies shadowing published plugins."""
    home = claude_home()
    shadowed = [(r, p) for r in results for p in find_shadowed(r, home)]
    if not shadowed:
        return
    if not prune:
        for r, path in shadowed:
            print(f"shadowed: {path} duplicates plugin {r.name}")
        print("rerun with --prune-shadowed to move these into a backup")
        return
    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup_root = Path(
        os.environ.get("CISTERNAL_SHADOW_BACKUP_DIR") or "~/.cisternal/shadowed"
    ).expanduser() / stamp
    for r, path in shadowed:
        dest = backup_root / path.relative_to(home)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        print(f"pruned: {path} (duplicate of plugin {r.name}) -> {dest}")


@dataclass(frozen=True)
class InstalledPlugin:
    id: str
    version: str | None
    scope: str | None


def installed_entries(claude_bin: str) -> list[InstalledPlugin] | None:
    """One entry per install from ``claude plugin list --json``, or None if unavailable.

    A plugin installed at several scopes yields several entries. None (with a
    printed reason) means the listing could not be obtained -- a missing binary
    or unparseable output -- which callers treat as "unknown", never as
    "nothing installed".
    """
    try:
        listing = subprocess.run(
            [claude_bin, "plugin", "list", "--json"], capture_output=True, text=True
        )
    except OSError as exc:
        print(f"claude: could not run {claude_bin!r} ({exc})")
        return None
    if listing.returncode != 0:
        print(f"claude: `plugin list` failed: {listing.stderr.strip()}")
        return None
    try:
        return [
            InstalledPlugin(id=p["id"], version=p.get("version"), scope=p.get("scope"))
            for p in json.loads(listing.stdout)
        ]
    except (ValueError, KeyError, TypeError):
        print("claude: could not parse `plugin list --json` output")
        return None


def installed_plugins(claude_bin: str) -> dict[str, str | None] | None:
    """``{plugin_id: version}`` view of :func:`installed_entries` (last scope wins)."""
    entries = installed_entries(claude_bin)
    return None if entries is None else {e.id: e.version for e in entries}


def refresh_claude(
    marketplace: Path, results: list[PublishResult], *, claude_bin: str
) -> int:
    """Bring installed plugins up to the just-published versions. Returns an exit code.

    Compares each INSTALLED version against the published one, not merely
    "did this publish change the marketplace copy": the marketplace can already
    be ahead of the install (e.g. published by another tool or an earlier run
    with --no-refresh). A published-but-not-installed plugin gets an install
    hint rather than being installed unasked. A missing ``claude`` binary is
    not an error (the publish itself succeeded) -- it prints the equivalent
    slash commands instead.
    """
    if not results:
        return 0
    try:
        mkt_name = marketplace_name(marketplace)
    except ValueError as exc:
        _log.error("cisternal: cannot read marketplace name for refresh: %s", exc)
        return 1

    def manual_hint(targets: list[PublishResult]) -> None:
        print(f"refresh manually in Claude Code: /plugin marketplace update {mkt_name}")
        for r in targets:
            print(f"  /plugin update {r.name}@{mkt_name}")

    installed = installed_plugins(claude_bin)
    if installed is None:
        manual_hint([r for r in results if r.changed])
        return 0

    stale = [
        r for r in results
        if f"{r.name}@{mkt_name}" in installed and installed[f"{r.name}@{mkt_name}"] != r.version
    ]
    for r in results:
        if r.changed and f"{r.name}@{mkt_name}" not in installed:
            print(f"{r.name}@{mkt_name}: published, not installed -- "
                  f"claude plugin install {r.name}@{mkt_name} --scope user")
    if not stale:
        print("claude: installed plugins already match the published versions")
        return 0

    update = subprocess.run(
        [claude_bin, "plugin", "marketplace", "update", mkt_name], capture_output=True, text=True
    )
    if update.returncode != 0:
        _log.error(
            "cisternal: `claude plugin marketplace update %s` failed (exit %d): %s",
            mkt_name, update.returncode, update.stderr.strip(),
        )
        return 1

    failures = 0
    for r in stale:
        plugin_id = f"{r.name}@{mkt_name}"
        upd = subprocess.run(
            [claude_bin, "plugin", "update", plugin_id], capture_output=True, text=True
        )
        if upd.returncode != 0:
            _log.error(
                "cisternal: `claude plugin update %s` failed (exit %d): %s",
                plugin_id, upd.returncode, upd.stderr.strip(),
            )
            failures += 1
        else:
            print(f"{plugin_id}: {installed[plugin_id]} -> {r.version}")
    if failures == 0:
        print("restart Claude Code to load the updated plugin(s)")
    return 1 if failures else 0


MARKETPLACE_README_TEMPLATE = """\
<!-- cisternal:managed -->
# Cisternal Local Plugin Marketplace

This is a shared Claude Code marketplace for locally built plugins from the
cisternal tool family (praxia, myxcel, bathos, and related tools).

## Installing a Tool's Plugin

From any tool that mounts cisternal's plugin sub-app (no repo checkout needed):

```
<tool> plugin install claude      # e.g. bth plugin install claude
<tool> plugin update claude
```

This publishes the tool's bundle here, registers this marketplace with Claude
Code, and installs (or updates) the plugin.

## Registering the Marketplace by Hand (One Time)

```
/plugin marketplace add <this directory>
/plugin install <tool>@cisternal-local
```

## Publishing from a Source Checkout

From the tool's own repo:

```
cisternal assets publish-shared --manifest .praxia/manifest.toml
```

This scrubs the destination plugin directory, exports a fresh bundle at a
content-derived version, and merges the marketplace entry under an flock'd
atomic read-modify-write — safe to run concurrently with other tools
publishing to the same marketplace. If the content changed and the plugin is
installed, it then runs `claude plugin marketplace update` + `claude plugin
update` for you (`--no-refresh` to skip); restart Claude Code to load it.

## Updating Everything

```
cisternal assets update-all
```

Republishes every plugin here from the repo that last published it (recorded
in `plugins/<tool>/.claude-plugin/cisternal-source.json`) and refreshes the
changed, installed ones in Claude Code. Plugins installed from a tool's
packaged snapshot are listed with the `<tool> plugin update claude` command to
run instead. `--dry-run` lists what it would do.

## One Source Per Skill

Plugins own their skills and agents. `publish-shared` and `update-all` report
any `~/.claude/skills/<skill>/` or `~/.claude/agents/<plugin>-<agent>.md` copy
that duplicates a published plugin; add `--prune-shadowed` to move them into
`~/.cisternal/shadowed/<timestamp>/`.

## Known Gaps

- **No cross-machine sync.** This marketplace is local to one machine.
- **Restart required.** Claude Code loads an updated plugin on restart.
- **MCP server name collisions.** Before installing a plugin, check whether
  its `.mcp.json` declares a server name already registered globally
  (`claude mcp list`) — installing would otherwise create a confusing
  plugin-namespaced duplicate.
"""
