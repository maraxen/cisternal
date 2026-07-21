# cisternal

**Status: alpha.** APIs may change without notice before `1.0`.

Cisternal is a shared telemetry substrate and agent-asset export toolkit for the Praxia tool family. It has two parts:

- **Telemetry** — a lightweight, non-blocking event pipeline (JSONL export, OTLP export, MCP-tool registration wrapper) for instrumenting Python tools and MCP servers.
- **Agent-asset export** — a CLI that takes a registry of MCP tools/commands and emits native plugin/config bundles for downstream coding-agent surfaces: Claude Code, Cursor, GitHub Copilot, and Antigravity.

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

```bash
# Preview what would be written, without touching disk
cisternal assets export --dry-run

# Write bundles for specific surfaces
cisternal assets export --out ./dist/agent-assets

# Inspect or validate an existing bundle
cisternal assets inspect
cisternal assets validate
```

Supported export targets: **Claude Code**, **Cursor**, **GitHub Copilot**, **Antigravity**.

The CLI is fastmcp-free by design — `cisternal.cli` imports and runs even in environments without `fastmcp` installed; asset-export logic never depends on the telemetry/registration surface.

## Design notes

- Telemetry emission never raises: if the pipeline isn't initialized, `emit_event`/`span` are no-ops.
- Registry state is process-scoped — call `cisternal.clear_registry()` between tests to avoid cross-test contamination.
- The M2 wire-time MCP callable is a pure passthrough: telemetry and shape adaptation are exclusively owned by the telemetry middleware, never by the registration wrapper itself.

## License

MIT — see [LICENSE](LICENSE).
