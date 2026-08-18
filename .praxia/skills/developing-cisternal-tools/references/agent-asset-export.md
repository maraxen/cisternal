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

## Manifest paths are plugin-root-relative (praxia parent-of-parent)

`ManifestAssetSource` resolves every `path = "..."` against the **plugin root** — the
directory that *contains* `.praxia/`, not the directory that contains `manifest.toml`.
That matches praxia (`<repo>/.praxia/manifest.toml` → `<repo>`). A skill at
`agent_assets/skills/foo/SKILL.md` is declared as `path = "agent_assets/skills/foo/SKILL.md"`.
A skill that lives *inside* `.praxia/` must include that prefix:
`path = ".praxia/skills/foo/SKILL.md"`. Do **not** use a `../` climb out of `.praxia/` —
that would resolve *above* the plugin root. Verify with `cisternal assets inspect` /
`validate` (and stderr) before trusting any path in a manifest you didn't just write.

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

## `[plugin.export_command]` is praxia argv, not slash-command files

This table is `Option<Vec<String>>` in praxia's schema and is executed as a subprocess
argv after export (`session.rs`). Cisternal must **not** treat those strings as markdown
paths: argv and a path list are the same TOML type, so a misread produces no parse error
— only missing-file warnings and empty `CommandAsset` bodies. Commands in a cisternal
bundle come from the Python registry, not from this table. If a plugin has no post-export
command for praxia to run, omit the table entirely. Do not put `.md` paths here (praxia
would try to exec them). A vendor path-list for slash-command files would be a new praxia
schema key, not a reinterpretation of `export_command`.

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
