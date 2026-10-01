# cisternal

**Status: alpha.** APIs may change without notice before `1.0`.

Cisternal is a shared telemetry substrate and agent-asset export toolkit for the Praxia tool family. It has two parts:

- **Telemetry** — a lightweight, non-blocking event pipeline (JSONL export, OTLP export, MCP-tool registration wrapper) for instrumenting Python tools and MCP servers.
- **Agent-asset export** — a CLI that takes a registry of MCP tools/commands and emits native plugin/config bundles for downstream coding-agent surfaces: Claude Code, Cursor, GitHub Copilot, Antigravity, OpenCode, Pi, and JCode.


## Install

```bash
pip install cisternal
```

For OTLP export support:

```bash
pip install "cisternal[otlp]"
```

## Telemetry quickstart

```python
import cisternal

cisternal.init()  # log_dir defaults to ~/.cisternal/logs, or env-resolved

with cisternal.span("my.operation", request_id="abc123"):
    do_work()

cisternal.emit_event("my.custom_event", tool="foo")
print(cisternal.status())
```

Check your effective telemetry configuration from the shell:

```bash
cisternal telemetry doctor
cisternal telemetry doctor --json --strict
```

### Registering MCP tools

```python
import cisternal

@cisternal.tool
def my_tool(x: int) -> int:
    return x * 2

registry = cisternal.wire(server, app, adapter=my_adapter)
```

`cisternal.tool` is a pure-metadata decorator — it returns the original function unchanged. `cisternal.wire()` snapshots the registry at call time and registers each tool on a FastMCP server (and optionally a Cyclopts CLI app), returning a `WiredRegistry` for introspection.

## Agent-asset export

A tool's agent plugin (skills, agents, hooks, MCP servers, declared in its
`.praxia/manifest.toml`) reaches a coding agent by one of two paths:

| | **Path 1: install through the tool** | **Path 2: direct surface export** |
|---|---|---|
| Who runs it | anyone who has the tool installed | the tool's developer, in its repo |
| Command | `<tool> plugin install claude` (e.g. `bth plugin install claude`) | `cisternal assets export --manifest … --surface <s> --out DIR` |
| Needs the `cisternal` CLI | no — the tool mounts cisternal's sub-app | yes |
| Needs a source checkout | no — falls back to a snapshot in the wheel | yes |
| Installs into the agent | yes (Claude Code) | no — writes files only (`assets install` / `publish-shared` also register them with Claude) |
| Surfaces | install: `claude` · export: all seven | all seven |

### Path 1 — `<tool> plugin install|update`

**Users** of a tool that mounts the sub-app:

```bash
bth plugin install claude              # publish + register marketplace + install (user scope)
bth plugin install claude --scope project
bth plugin update claude               # republish + update the installed copy
bth plugin export cursor --out DIR     # files only, any surface
bth plugin info                        # where the bundle and the marketplace resolve from
bth plugin install claude --dry-run    # show what would happen, change nothing
```

`install` publishes into the shared marketplace, registers that marketplace
with Claude Code if it isn't already, then installs the plugin at `--scope`.
If the plugin is already installed at that scope, `install` updates it (or
does nothing when it is current). Installs at other scopes are left alone.
`update` refuses to run when the plugin isn't installed, and updates every
stale install at the scope it was installed at. Both commands report skill and
agent copies in `~/.claude/` that shadow the plugin; `--prune-shadowed` moves
them into a backup. Restart Claude Code to
load the change. cisternal dogfoods this itself: `cisternal plugin install claude`.

**Tool authors** add it in three steps:

1. Mount the sub-app in the tool's cyclopts CLI:

   ```python
   from cisternal.plugin import PluginSpec, plugin_app

   app.command(plugin_app(PluginSpec(name="bathos", package="bathos", cli="bth")))
   ```

   `PluginSpec` also takes `registry`/`imports` (merge `@cisternal.tool`
   commands, for surfaces that emit them), `version` (defaults to the
   installed distribution's version), `snapshot` and `manifest` paths.

2. Freeze the manifest into package data, so wheel installs work without the repo:

   ```bash
   cisternal assets snapshot --manifest .praxia/manifest.toml --out src/bathos/agent_plugin.json
   ```

   ```toml
   [tool.setuptools.package-data]      # or your build backend's equivalent
   bathos = ["agent_plugin.json"]
   ```

3. Keep it in sync in CI:
   `cisternal assets snapshot --manifest .praxia/manifest.toml --out src/bathos/agent_plugin.json --check`
   exits 1 if the snapshot is missing or stale.

The bundle is taken from the first of: `--manifest PATH`; the tool's own
`.praxia/manifest.toml` above the imported package, for an editable install
(it is never searched for from inside `site-packages`, and must name this
plugin); the packaged snapshot. `plugin info` shows which one won.

### Path 2 — direct surface export (`cisternal assets …`)

From the tool's source checkout, with the `cisternal` CLI:

```bash
cisternal assets export --manifest .praxia/manifest.toml --surface cursor --out ./dist/cursor
cisternal assets export --manifest .praxia/manifest.toml --dry-run      # paths + sha256, writes nothing
cisternal assets inspect  --manifest .praxia/manifest.toml              # JSON load report
cisternal assets validate --manifest .praxia/manifest.toml              # structural + golden checks
cisternal assets publish-shared --manifest .praxia/manifest.toml        # into the shared marketplace (+ refresh)
cisternal assets update-all                                             # republish every enrolled plugin
cisternal assets install --manifest .praxia/manifest.toml               # standalone single-plugin marketplace
```

`assets export` only writes files. Nothing loads them until something
registers them. `assets install` makes the bundle its own single-plugin
marketplace and registers it with Claude Code. It requires a
`[plugin.marketplace]` table in the manifest:

```toml
[plugin.marketplace]
name = "my-plugin-marketplace"

[plugin.marketplace.owner]
name = "Your Name"
```

`publish-shared` instead adds the plugin to the shared multi-tool
marketplace, the same one Path 1 uses. `update-all` republishes every plugin
there from the repo that last published it. A plugin installed through Path 1
is not rebuilt by `update-all`; instead it prints that tool's own
`<tool> plugin update claude`, because the tool owns the recipe (version,
snapshot vs. checkout).

### Where the shared marketplace lives

It is derived data, so its location is configuration, never a baked-in path.
The first match wins (`<tool> plugin info` shows which):

1. `--marketplace PATH`
2. `$CISTERNAL_PLUGIN_MARKETPLACE` (`none`/empty disables)
3. `[tool.cisternal] plugin_marketplace = "PATH"` in the nearest `pyproject.toml`
4. `plugin_marketplace = "PATH"` in `${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml`

If none of these is set, the first command that needs the marketplace
(`plugin install|update`, `assets publish-shared`, `assets update-all`)
**generates the per-machine config** and reports it on stderr:

```toml
# ~/.config/cisternal/config.toml
plugin_marketplace = "~/.cisternal/claude-plugin-marketplace"
```

That file then decides, and you can change it. An existing config file keeps
its contents: the key is added as its first line. A malformed config file is
an error and is never overwritten. `plugin info` and `--dry-run` only report
that the file would be written. Set `CISTERNAL_PLUGIN_MARKETPLACE=none` to opt
out; commands then fail instead of generating anything.

### Surfaces

Export targets: **Claude Code**, **Cursor**, **GitHub Copilot**, **Antigravity**, **OpenCode**, **Pi**, **JCode**.
Install (`plugin install|update`) is implemented for **Claude Code**. For the
other surfaces, `plugin install <surface>` points at `plugin export`.
**Codex** is not supported yet: there is no emitter, and Codex's documented
CLI can add a marketplace (`codex plugin marketplace add`) but installs only
through its `/plugins` UI. The installer table (`INSTALLABLE_SURFACES` in
`cisternal.plugin.app`) is where it would plug in.

The CLI is fastmcp-free by design — `cisternal.cli` imports and runs even in environments without `fastmcp` installed; asset-export logic never depends on the telemetry/registration surface.

## Design notes

- Telemetry emission never raises: if the pipeline isn't initialized, `emit_event`/`span` are no-ops.
- Registry state is process-scoped — call `cisternal.clear_registry()` between tests to avoid cross-test contamination.
- The M2 wire-time MCP callable is a pure passthrough: telemetry and shape adaptation are exclusively owned by the telemetry middleware, never by the registration wrapper itself.

## License

MIT — see [LICENSE](LICENSE).
