---
name: developing-cisternal-tools
description: Guides safe, release-ready development of cisternal — the shared telemetry + registration substrate consumed by multiple sibling projects (bathos, contemplex, xperiri, myxcel). Use this whenever fixing a bug in cisternal itself, extending its registration/wire()/telemetry/export API, or cutting and publishing a new cisternal release (version bump, GitHub Release, PyPI publish via trusted OIDC). Also trigger whenever a consumer integration (e.g. bathos migrating onto cisternal.wire()) surfaces what looks like a bug in cisternal's public API — even if the user only asks you to fix or work around it in the consumer repo. Also trigger whenever a consumer wants to be packaged/exported as an agent-surface plugin (Claude Code, Cursor, Copilot, Antigravity) via `cisternal assets export` and a `.praxia/manifest.toml` — including debugging why an export silently dropped an agent/skill, or why a manifest's declared paths aren't resolving. This skill covers deciding whether to patch upstream in cisternal vs. work around it downstream, proving the fix with a regression test that actually fails without it, verifying end-to-end against the real consumer before publishing, closing the loop by updating every dependent project afterward, and the manifest/registry asset-export workflow's specific gotchas (path resolution, fail-open exit codes, export_command semantics). Use proactively — don't wait for the user to say "cisternal" by name if the symptom (silently wrong behavior in a decorator/registry/wire() call, a consumer-side workaround for what looks like a library defect, an agent/skill missing from an exported plugin bundle) points there.
---

# Developing cisternal tools

cisternal is a shared substrate, not a single-project library — it exists so bathos, contemplex, xperiri, and myxcel (see the adapter classes in `src/cisternal/adapters/base.py`) don't each reinvent telemetry and MCP-tool registration. That single fact should drive most of the decisions below: **a bug found through one consumer will eventually bite every other consumer**, so the default is to fix it in cisternal itself, not to route around it in whichever project happened to find it first. A consumer-side workaround is sometimes the right call (see "When NOT to patch upstream" below), but it should be a deliberate choice, not a reflex.

## The loop, end to end

This is the shape the work takes, whether you're extending cisternal's API or fixing a bug a consumer surfaced:

1. **Isolate.** Branch off `main` in the cisternal repo before touching anything — never edit `main` directly, even for a one-line fix.
2. **Diagnose against the real installed code, not assumptions.** Read the actual source of the function you suspect (`site-packages/cisternal/...` in the consumer's venv, or the cisternal repo directly), and confirm the failure empirically — call the function, introspect the real return value or object state — before writing a fix. A docstring or comment describing intended behavior is a hypothesis, not evidence.
3. **Fix at the root.** Prefer the cisternal-side fix over a consumer-side workaround (see below for when this isn't the right call).
4. **Prove the fix with a test that fails first.** Write the regression test, confirm it fails against the pre-fix code (`git stash` the fix, run the test, `git stash pop`), then confirm it passes with the fix restored. A test you never watched fail isn't verified to test anything.
5. **Run the full suite, not just the new test.** A narrow fix can still have collateral effects elsewhere in the registration/telemetry pipeline.
6. **Triage CI failures before merging — don't blindly override, but don't blindly block either.** If a check fails, read the actual failure log. Check whether it was already failing on `main` before your change (`gh run list --branch main --workflow <name>`, then read 1-2 pre-existing failure logs and confirm the exact same signature). A pre-existing, unrelated, disclosed failure is not a reason to hold up a real fix; a failure you haven't actually read is not something to wave through either.
7. **Respect (or knowingly bypass) branch protection.** Check `gh api repos/<owner>/<repo>/rules/branches/main` before merging — a required-review rule with no available reviewer (common on a solo-maintainer repo) will reject a plain `gh pr merge`. Bypassing it with `--admin` is a real decision with a real owner: ask before doing it, don't default to it silently.
8. **Release as two commits, not one.** The fix/feature PR merges first; the version bump (`chore(release): X.Y.Za`) is its own separate PR/commit afterward, keyed to what's actually shipping in it (`fix wire() name= drop (#6)`, not a generic "bump version"). Don't fold a version bump into a feature commit.
9. **Cut the release, then verify it actually landed.** `gh release create vX.Y.Za --target main` (published, not draft) is what fires `publish.yml`'s `on: release: types: [published]` trigger → `uv build && uv publish` (PyPI trusted OIDC publishing — no token to manage). A green Actions run is necessary but not sufficient: PyPI's index can lag 10-20 seconds behind a successful upload, so re-check `https://pypi.org/pypi/<name>/json` directly rather than trusting the workflow's green checkmark alone.
10. **Close the loop in every dependent project.** For each consumer: bump its dependency floor to the new version, `uv sync` so it resolves the *real published package* (not a leftover local editable/path override used during development), rerun its full test suite, and delete the temporary override before committing. "It works with my local checkout of cisternal" is not the same claim as "it works with what's on PyPI."
11. **If a second bug surfaces in the same area, repeat the loop — don't patch around it downstream a second time.** An adversarial second look after a first fix ships is normal, not a sign the first fix was sloppy; treat a fresh finding the same way as the first (root-cause fix, failing-then-passing test, full suite, proper release).

## When NOT to patch upstream

There are two different questions here, and they get different answers.

**If the user has told you how to scope this — that instruction wins, full stop.** "We don't have time for the library today, just patch the consumer" is not one factor to weigh against "fix at the root" — it's the answer. The "bug found through one consumer will eventually bite every consumer" reasoning is true, but it's an argument for *why upstream is usually better when the choice is yours to make*, not a license to override someone who has already made the call for a stated reason (time pressure, a freeze, wanting to batch several fixes into one release later). Talking yourself into the full upstream cycle anyway — "the time-pressure argument didn't really hold up" — is answering a question nobody asked. When you honor a deferred/scoped request, your job shifts from "decide whether to patch upstream" to "make sure the workaround doesn't silently erase the fact that a shared-library bug exists": leave a code comment, a commit message note, or a stated follow-up that says what the real defect is and where it lives, so it doesn't quietly become permanent or blindside the next consumer who hits it.

**If the user hasn't specified — then you're the one deciding, and the default is to prefer cisternal.** Fix it in the consumer instead when: the behavior is genuinely project-specific (not something a second consumer would ever want), the "fix" would require cisternal to know about a consumer's internals (breaks the substrate/consumer boundary), or you have good reason to believe a release cycle isn't warranted yet and the workaround is trivially removable later. Same rule applies here too: leave a trace of the real defect rather than letting the workaround read as a coincidental rename.

## Asking before bypassing friction

Sandbox or permission denials during this work (writing into a sibling repo's worktree, running git operations outside the current session's default allowlist) are common — cisternal deliberately sits alongside consumer repos rather than inside them. Hitting one is a normal, expected part of the loop, not a sign something's broken. Retry the specific operation with elevated/unsandboxed access rather than disabling the sandbox wholesale, and say what you're doing and why before you do it — a quick "this needs write access to the cisternal repo, which is outside the default sandbox for this session" costs one line and lets the user object if the access is broader than they intended. Silently flipping a permission or sandbox setting to make an error go away removes their chance to say no.

## The kind of bug that hides from unit tests

The `wire()` name-override bug (`maraxen/cisternal#6`) is the canonical example of why this loop matters: the registry snapshot and `WiredRegistry.mcp_tools` both *correctly* recorded the intended tool name — only the actual FastMCP registration (`server.add_tool(...)`) silently fell back to the raw Python function's `__name__`. Every existing test asserted against the registry-level view, which was right all along, so nothing caught it. The lesson: **when a fix touches a boundary between two systems (a registry and a transport, a decorator and a real server), assert against the far side of that boundary** (`await app.list_tools()`, not just `WiredRegistry.mcp_tools`), not just the near side that's convenient to construct a test double for.

## Packaging a consumer as an agent-surface plugin

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

### The manifest-path gotcha (a real bug this session hit)

`ManifestAssetSource` resolves every `path = "..."` in the manifest **relative to the
manifest file's own directory**, not the repo root. A manifest at `.praxia/manifest.toml`
declaring `path = "agent_assets/skills/foo/SKILL.md"` will look for
`.praxia/agent_assets/skills/foo/SKILL.md` — almost never what you meant. Paths need a
`../` prefix to climb back out of `.praxia/` to the repo root (e.g.
`../agent_assets/skills/foo/SKILL.md`). Verify with `--dry-run` before trusting any path in
a manifest you didn't just write yourself.

### It fails open, not closed — read stderr, don't just check the exit code

`cisternal assets export` **always exits 0** (a deliberate never-raise convention) and
reports every problem as a stderr warning instead: an unreadable path, a missing skill body,
an unrecognized manifest table. The emitters (`ClaudeEmitter` et al.) are themselves
fail-closed on top of that — a skill or agent with an empty `body` (because its file failed
to load) is **silently dropped from the bundle**, not substituted with a placeholder or
flagged as an error in the output itself. The combined effect: a badly-pathed manifest
produces a bundle that *looks* successful (valid `plugin.json`, exit code 0) while quietly
missing half its assets. Treat any non-empty stderr from an export run as a real failure to
investigate, exactly like the "diagnose against real installed code, not assumptions"
principle above — don't infer correctness from the exit code or from the presence of
*some* output files.

### `[plugin.export_command]` is not a shell command

This table's values are lists of **markdown file paths** — each becomes a `CommandAsset`
named after the file's stem, meant for a consumer that has literal slash-command body files
to bundle. It is easy to mistake this for "the CLI invocation used to run export" (a shell
argv array) — that's a different, unrelated concept, and cisternal's loader will interpret
argv tokens as bogus file paths, producing a wall of "missing or unreadable" warnings for
`bth`, `export`, `--surface`, etc. If a consumer has no real command markdown files (e.g.
its "commands" are just its MCP tools, already covered by the registry side), leave this
table out entirely rather than repurposing it.

### Don't let the bundle's version drift from the package's

A manifest's own `version` field is easy to forget to bump and will happily ship a stale
version string in `plugin.json` forever if nothing overrides it. Pass `--name`/`--version`
explicitly at export time, sourced from the actual installed package
(`importlib.metadata.version(...)` or the package's own `__version__`), so the manifest's
hand-maintained field becomes a fallback rather than the source of truth.

## Common commands

```bash
# CI history check before triaging a failure as "pre-existing"
gh run list --repo <owner>/<repo> --branch main --workflow <name> --limit 5

# Branch protection / required reviews
gh api repos/<owner>/<repo>/rules/branches/main

# Confirm a release actually reached PyPI (allow for index lag)
curl -sf https://pypi.org/pypi/<package>/json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d['info']['version'])"

# Point a consumer at an unreleased local fix for end-to-end verification
# (pyproject.toml, DEV-ONLY — revert before committing):
#   [tool.uv.sources]
#   cisternal = { path = "../relative/path/to/cisterna", editable = true }

# Dry-run a consumer's plugin export before trusting any file paths in its manifest
cisternal assets export \
  --manifest .praxia/manifest.toml --registry <name> --import <module> \
  --surface claude --dry-run
```
