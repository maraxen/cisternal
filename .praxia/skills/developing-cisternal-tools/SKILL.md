---
name: developing-cisternal-tools
description: Guides safe, release-ready development of cisternal — the shared telemetry + registration substrate consumed by multiple sibling projects (bathos, contemplex, xperiri, myxcel). Use this whenever fixing a bug in cisternal itself, extending its registration/wire()/telemetry/export API, or cutting and publishing a new cisternal release (version bump, GitHub Release, PyPI publish via trusted OIDC). Also trigger whenever a consumer integration (e.g. bathos migrating onto cisternal.wire()) surfaces what looks like a bug in cisternal's public API — even if the user only asks you to fix or work around it in the consumer repo. This skill covers deciding whether to patch upstream in cisternal vs. work around it downstream, proving the fix with a regression test that actually fails without it, verifying end-to-end against the real consumer before publishing, and closing the loop by updating every dependent project afterward. Use proactively — don't wait for the user to say "cisternal" by name if the symptom (silently wrong behavior in a decorator/registry/wire() call, a consumer-side workaround for what looks like a library defect) points there.
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

Fix it in the consumer instead when: the behavior is genuinely project-specific (not something a second consumer would ever want), the "fix" would require cisternal to know about a consumer's internals (breaks the substrate/consumer boundary), or the turnaround time genuinely doesn't allow a release cycle and the workaround is trivially removable later. Even then, leave a comment or issue noting the workaround exists *because* of a cisternal gap, so it doesn't quietly become permanent.

## The kind of bug that hides from unit tests

The `wire()` name-override bug (`maraxen/cisternal#6`) is the canonical example of why this loop matters: the registry snapshot and `WiredRegistry.mcp_tools` both *correctly* recorded the intended tool name — only the actual FastMCP registration (`server.add_tool(...)`) silently fell back to the raw Python function's `__name__`. Every existing test asserted against the registry-level view, which was right all along, so nothing caught it. The lesson: **when a fix touches a boundary between two systems (a registry and a transport, a decorator and a real server), assert against the far side of that boundary** (`await app.list_tools()`, not just `WiredRegistry.mcp_tools`), not just the near side that's convenient to construct a test double for.

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
```
