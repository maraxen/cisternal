# Packaging a consumer as an agent-surface plugin

Registering tools via `@cisternal.tool` + `wire()` is only half of what cisternal offers a
consumer. The other half, `cisternal assets export`, turns a consumer's *whole* agent
footprint — its MCP tools, plus any skills/agents/hooks it ships — into a real,
installable plugin bundle (Claude Code, Cursor, Copilot, or Antigravity). Reach for this
whenever a consumer wants to be distributed as a plugin, not just consumed as a library.

Two sources combine into one bundle:

- **The wired MCP registry** (`--registry <name> --import <module that calls wire()>`)
  contributes *commands only* — one per tool, sourced from the registry snapshot. This is
  the same registry a consumer already populates via `@cisternal.tool(registry=...)`.
- **A `.praxia/manifest.toml`** (`--manifest path/to/manifest.toml`) declares everything a
  registry can't: `[plugin]` metadata, `[plugin.mcp]` (the MCP server launch command),
  `[[plugin.skills]]`, `[[plugin.agents]]`, `[[plugin.hook_specs]]`.

Passing both (`CompositeAssetSource`) merges them: manifest-declared commands win by name on
conflict, registry-derived commands fill in the rest. Passing only `--registry` (no
manifest) exports commands alone; passing only `--manifest` exports without any tool
commands. For a full bundle — the common case — pass both.

```bash
cisternal assets export \
  --manifest .praxia/manifest.toml --registry <consumer-registry-name> \
  --import <consumer_package.mcp_module> \
  --surface claude --out <output-dir>
```

## The manifest-path gotcha (a real bug this session hit)

`ManifestAssetSource` resolves every `path = "..."` in the manifest **relative to the
manifest file's own directory**, not the repo root. A manifest at `.praxia/manifest.toml`
declaring `path = "agent_assets/skills/foo/SKILL.md"` will look for
`.praxia/agent_assets/skills/foo/SKILL.md` — almost never what you meant. Paths need a
`../` prefix to climb back out of `.praxia/` to the repo root (e.g.
`../agent_assets/skills/foo/SKILL.md`). Verify with `--dry-run` before trusting any path in
a manifest you didn't just write yourself. A skill declared with a correct, same-directory
path (e.g. `skills/foo/SKILL.md` for a skill living right next to the manifest under
`.praxia/skills/foo/`) needs no `../` — the gotcha only bites when the target lives outside
the manifest's own directory tree.

## It fails open, not closed — read stderr, don't just check the exit code

`cisternal assets export` **always exits 0** (a deliberate never-raise convention) and
reports every problem as a stderr warning instead: an unreadable path, a missing skill body,
an unrecognized manifest table. The emitters (`ClaudeEmitter` et al.) are themselves
fail-closed on top of that — a skill or agent with an empty `body` (because its file failed
to load) is **silently dropped from the bundle**, not substituted with a placeholder or
flagged as an error in the output itself. The combined effect: a badly-pathed manifest
produces a bundle that *looks* successful (valid `plugin.json`, exit code 0) while quietly
missing half its assets. Treat any non-empty stderr from an export run as a real failure to
investigate, exactly like the "diagnose against real installed code, not assumptions"
principle in the main skill — don't infer correctness from the exit code or from the
presence of *some* output files.

## `[plugin.export_command]` is not a shell command

This table's values are lists of **markdown file paths** — each becomes a `CommandAsset`
named after the file's stem, meant for a consumer that has literal slash-command body files
to bundle. It is easy to mistake this for "the CLI invocation used to run export" (a shell
argv array) — that's a different, unrelated concept, and cisternal's loader will interpret
argv tokens as bogus file paths, producing a wall of "missing or unreadable" warnings for
`bth`, `export`, `--surface`, etc. If a consumer has no real command markdown files (e.g.
its "commands" are just its MCP tools, already covered by the registry side), leave this
table out entirely rather than repurposing it.

## Don't let the bundle's version drift from the package's

A manifest's own `version` field is easy to forget to bump and will happily ship a stale
version string in `plugin.json` forever if nothing overrides it. Pass `--name`/`--version`
explicitly at export time, sourced from the actual installed package
(`importlib.metadata.version(...)` or the package's own `__version__`), so the manifest's
hand-maintained field becomes a fallback rather than the source of truth.

## Only a single markdown file per skill is bundled — no `references/` of its own

`ManifestAssetSource._load_skills` (`src/cisternal/assets/manifest.py`) reads exactly one
file per `[[plugin.skills]]` entry — whatever `path` points at — into a single `SkillAsset`
body. There is no mechanism to carry a skill's own `references/`/`examples/`/`scripts/`
subdirectory into the exported bundle; only the one markdown file's contents make it into
`plugin.json`. A skill meant for export (declared in `.praxia/manifest.toml`, like
`export-trust` or `run-cisternal`) should therefore stay self-contained in its single
`SKILL.md` — this skill (`developing-cisternal-tools`) can use `references/` because it is
**not** declared in the manifest and is never exported; it's read directly out of
`.praxia/skills/` by whatever surfaces it to an agent working in this repo.

## Common commands

```bash
# Dry-run a consumer's plugin export before trusting any file paths in its manifest
cisternal assets export \
  --manifest .praxia/manifest.toml --registry <name> --import <module> \
  --surface claude --dry-run
```
