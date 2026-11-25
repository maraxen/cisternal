# Spike: skills over MCP (SEP-2640) from a FastMCP server

Throwaway, task `261125_skills-over-mcp-spike`. Not wired into cisternal.

- `skills_ext_server.py`: a FastMCP `ServerExtension` advertising
  `io.modelcontextprotocol/skills`, with `skills/list`, `skills/get` and one
  `skill://<name>/<path>` resource per file.
- `probe_raw.py`: raw 2026-07-28 JSON-RPC over stdio; checks the capability,
  both methods, per-file sha256 and size, and the -32602 error.
- `skills/spike-demo/`: a skill with one supporting file.

## Result so far (2026-11-25, fastmcp 4.0.10, mcp 2.2.0)

`probe_raw.py` passes against `export-trust` and `spike-demo`: PROBE PASS.

## Claude Code result (2026-11-25, v2.1.332, Claude Team login)

Observed in `wire.log` from an interactive session (`claude -n <name>`; a bare
`claude` opens the agent view, which connects to no MCP server):

- Claude Code sends `server/discover` at 2026-07-28 and receives the
  `io.modelcontextprotocol/skills` capability.
- Its client capabilities list only `io.modelcontextprotocol/tasks`.
- It calls `prompts/list`, `resources/list` and `tools/list`, and never
  `skills/list`. So no MCP skill appears in `/skills`.

Most likely cause: the account is on a Team plan, where the docs say MCP skills
are off until the organization enables them (and, for servers that are not
connectors, sets `disableDirectMcpSkills` to `false` in managed settings). Not
ruled out: the session was a sandboxed child session.

The server side needs no change to retest once the feature is on.

## Manual check, for when MCP skills are enabled

`claude -p` does not load MCP skills, so run this by hand (Claude Code
>= 2.1.331, on a plan where MCP skills are on):

```
PY=/home/marielle/projects/cisternal/.venv/bin/python
D=<this directory, absolute>
claude mcp add skillspike -- $PY $D/skills_ext_server.py \
  $D/skills/spike-demo <repo>/.praxia/skills/export-trust
claude
```

In the session:

1. `/mcp` then skillspike: Protocol row shows 2026-07-28 or later.
2. `/skills`: `skillspike:spike-demo` and `skillspike:export-trust` are listed.
3. Is `skillspike:export-trust` listed next to the plugin's
   `cisternal:export-trust` (two copies), or is one hidden?
4. Type `skill spike check`: the reply contains `MCP-SKILL-LOADED` and the
   token from `references/token.md` (supporting file read as a resource).
5. Note whether a load prompt appeared, and in which permission mode.

Clean up: `claude mcp remove skillspike`.
