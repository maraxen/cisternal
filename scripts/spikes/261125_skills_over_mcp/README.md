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

## Not yet checked: Claude Code (needs an interactive session)

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
