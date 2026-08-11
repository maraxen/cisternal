# Task Report: fix-mcp-command-string

## Bug mechanism

`ClaudeEmitter.emit()` in `src/cisternal/export/claude.py` built `.mcp.json` like:

```python
"command": list(srv.command),   # full argv, e.g. ["uv", "run", "--project", "/path", "pull-books", "mcp"]
```

Claude Code's real `.mcp.json` schema requires `command` to be a single
executable string, with a separate `args` array for the rest of the argv.
Confirmed live in production: running `claude` against a real `.mcp.json`
produced by this emitter yielded:

```
[Warning] [pull-books] mcpServers.pull-books: Skipped — invalid MCP server config for "pull-books": command: expected string, received array
```

This is a hard schema-validation rejection, not cosmetic — the MCP server
never registers.

## Fix design

`src/cisternal/export/claude.py`:
- Added `_mcp_server_obj(srv: McpAsset) -> dict[str, object]` helper.
  `command` = `srv.command[0]` (or `""` if the tuple is empty — defensive,
  never-raise; this shouldn't happen in practice since `McpAsset.command` is
  populated from a non-empty list in `assets/manifest.py::_load_mcp`).
  `args` = `list(srv.command[1:])`, added to the dict **only when
  non-empty** — mirrors this file's existing sparse-field conventions (e.g.
  optional `owner.email`/`owner.url` in the marketplace block).
  `env` is always present (unchanged).
- Updated the `.mcp.json` shape described in the module docstring to match.

Ground-truthed the "omit `args` when empty" design decision against the
actual Rust source this Python code aims for parity with:
`/Users/mar/Projects/praxia/crates/praxia-agent-assets/src/bundle_claude.rs`
(lines 25-44, 88-108) does exactly this:
```rust
let command_str = mcp.command.first().cloned().unwrap_or_default();
let args: Vec<String> = mcp.command.get(1..).unwrap_or(&[]).to_vec();
let mut server_obj = json!({ "command": command_str, "env": mcp.env });
if !args.is_empty() {
    server_obj["args"] = Value::Array(args.into_iter().map(Value::String).collect());
}
```
This confirms the split/omit-if-empty/`""`-default design is correct, not
just a plausible guess.

## claude_rust.py — same bug, fixed

`src/cisternal/export/claude_rust.py`'s `.mcp.json` (and its embedded
`plugin.json["mcpServers"]`, both rust-parity output) delegate to
`_rust_emit.py::mcp_servers_json()`, which had the identical
whole-argv-in-`command` bug. Fixed it to match, following the exact
`bundle_claude.rs` logic above (command/args split, `args` omitted when
empty, `env` always present). Also built the dict in alphabetical key
insertion order (`args`, `command`, `env`) to match serde_json's
default `BTreeMap`-backed `Map` serialization order, since
`bundle_sha256_rust`/rust-parity golden-digest tests hash raw JSON string
bytes (key order is significant for byte-parity there, unlike the
legacy/`claude.py` path which always serializes with `sort_keys=True`).

This was a small, mechanically analogous fix (same shape, same file,
already-shared helper) — not deep/ambiguous, so no NEEDS_CONTEXT escalation
was warranted. Verified against the real Rust source directly rather than
guessing.

## Other surfaces checked (out of scope, confirmed correct)

- `src/cisternal/export/cursor.py`, `copilot.py`, `antigravity.py` (+ their
  `*_rust.py` counterparts) each keep `"command": list(srv.command)` — these
  are different tools (Cursor IDE, Copilot CLI, Antigravity) with their own
  `.mcp.json`/config schemas, out of this task's scope (which is Claude
  Code's emitter specifically). Not touched.
- `src/cisternal/assets/bridge.py::_mcp_to_json` also keeps
  `"command": list(mcp.command)` — but this is the **input** JSON fed to the
  `PraxiaBundle` Rust struct for cross-validation subprocess calls (matches
  the Rust struct's `command: Vec<String>` field, which is the pre-split
  argv). `bundle_claude.rs` itself does the split when producing *output*.
  Confirmed correct, not a bug.

## TDD evidence

- `tests/test_export_claude.py::test_mcp_json_present_when_non_empty` (was
  locking in the wrong shape): before the fix this test asserted
  `srv["command"] == ["python", "-m", "server"]`. Updated to assert the
  correct split: `srv["command"] == "python"` and
  `srv["args"] == ["-m", "server"]`.
- Added `tests/test_export_claude.py::test_mcp_json_single_element_command_omits_args`:
  covers a single-element argv `("python",)` — confirms `command` is a
  string, `"args"` key is absent entirely (not an empty list), and `env`
  is `{}`.
- Manually verified the real pull-books-shaped multi-element argv produces
  exactly the shape a real Claude Code install would accept:
  ```json
  {"mcpServers": {"pull-books": {"args": ["run", "--project", "/path", "pull-books", "mcp"], "command": "uv", "env": {}}}}
  ```

## Full suite results

`uv run pytest -q` → **531 passed, 16 skipped** (skips are the
`CISTERNAL_PRAXIA_ASSETS_BIN`-gated subprocess-parity tests, unrelated to
this change — env var unset in this environment). No failures.

Verified no golden-digest regression risk directly: grepped all fixtures for
`[plugin.mcp]` — zero matches. The rust-parity conformance fixture
(`tests/fixtures/manifest_minimal/manifest.toml`) has no `[[plugin.mcp]]`
table, so the `mcpServers`/`.mcp.json` branches in `_rust_emit.py` /
`claude_rust.py` were never exercised by the pinned golden digests before or
after this change.

## Lint results

`uv run ruff check src/cisternal/export/claude.py src/cisternal/export/claude_rust.py src/cisternal/export/_rust_emit.py tests/test_export_claude.py`
→ **All checks passed!**

## Files changed

- `src/cisternal/export/claude.py` — `.mcp.json` command/args split
  (`_mcp_server_obj` helper), docstring update.
- `src/cisternal/export/_rust_emit.py` — `mcp_servers_json()` command/args
  split (shared by `claude_rust.py`'s `.mcp.json` and rust-parity
  `plugin.json["mcpServers"]`).
- `tests/test_export_claude.py` — fixed the previously-wrong assertion in
  `test_mcp_json_present_when_non_empty`; added
  `test_mcp_json_single_element_command_omits_args`.

## Self-review

- Real multi-element argv (`["uv", "run", "--project", "/path", "pull-books", "mcp"]`)
  produces `{"command": "uv", "args": ["run", "--project", "/path", "pull-books", "mcp"]}` — confirmed by direct execution above. YES.
- Previously-wrong test updated (not deleted), now asserts the correct split
  shape. YES.
- `claude_rust.py` checked for the same bug — found it (via shared
  `_rust_emit.py::mcp_servers_json`) and fixed it, ground-truthed against
  the actual Rust source. YES.
- `Emitter.emit()`'s PURE/DETERMINISTIC/NEVER-RAISE contract preserved: no
  I/O added; empty-tuple and single-element `command` handled without
  raising (`command[0] if command else ""`, `args` only added when
  `len(command) > 1`); existing purity/determinism tests
  (`test_claude_emitter_emit_does_no_filesystem_io*`,
  `test_emit_twice_byte_identical_dict`, etc.) still pass. YES.

## Concerns

None. The fix is isolated, ground-truthed against the actual upstream Rust
implementation (not guessed), and the full suite + lint are clean.

---

## Round 2: field-order bug in the rust-parity path (reviewer finding)

The coordinator's review confirmed the legacy `ClaudeEmitter` path (the
actual production bug) correct, but caught a real ordering bug in my
round-1 rust-parity fix.

### What was wrong

My round-1 `mcp_servers_json()` inserted fields as `args, command, env`
(alphabetical), reasoning that serde_json's default `BTreeMap`-backed `Map`
alphabetizes keys on serialization. That premise was wrong for the actual
`praxia-agent-assets` build: `praxia-core`'s `Cargo.toml` requests
`serde_json = { features = ["preserve_order"] }`
(`/Users/mar/Projects/praxia/crates/praxia-core/Cargo.toml:18`), and Cargo
feature unification means that feature is active for `serde_json` across
the whole dependency graph that includes `praxia-agent-assets`
(`praxia-agent-assets` depends on `praxia-core` — confirmed via
`praxia-agent-assets/Cargo.toml:12`, `praxia-core = { path = "../praxia-core" }`).
With `preserve_order` active, `serde_json::Map` is `IndexMap`-backed
(insertion-ordered), not alphabetical. Since `_rust_emit.py::compact_json`
does not `sort_keys`, the round-1 fix's literal output byte order diverged
from the real Rust binary for any MCP server with more than one command
element — undetected only because no fixture exercises `[[plugin.mcp]]`
through the golden/parity test matrix.

### Fix

Re-verified `bundle_claude.rs`'s literal field-insertion order (both the
`plugin.json["mcpServers"]` block, lines 25-44, and the `.mcp.json` block,
lines 88-108): `json!({"command": command_str, "env": mcp.env})` builds the
object with `command` then `env`, and `args` is appended afterward,
conditionally, only when non-empty:
```rust
let mut server_obj = json!({ "command": command_str, "env": mcp.env });
if !args.is_empty() {
    server_obj["args"] = Value::Array(...);
}
```
Reordered `mcp_servers_json()` in `src/cisternal/export/_rust_emit.py` to
build the dict as `{"command": ..., "env": ...}` first, then conditionally
add `obj["args"] = ...` last — matching this literal insertion order exactly.
Rewrote the function's docstring to state the real reason (literal
insertion order matching `bundle_claude.rs`, `preserve_order` active via
`praxia-core`), not the incorrect alphabetical/`BTreeMap` claim from round 1.

### New tests (catch field-order regressions specifically)

Dict equality (used by round-1's `test_mcp_json_single_element_command_omits_args`)
can't catch an insertion-order regression since Python dict equality ignores
key order. Added two new tests in `tests/test_claude_rust_parity.py` that
assert on the literal serialized string instead:

- `test_mcp_servers_json_field_order_matches_bundle_claude_rs`: calls
  `compact_json(mcp_servers_json(...))` directly for a multi-element
  command and asserts the exact literal substring
  `'"command":"uv","env":{},"args":["run","--project","/path","pull-books","mcp"]'`
  is present, in that order.
- `test_claude_rust_parity_mcp_json_field_order_end_to_end`: calls
  `emit_claude_rust_parity()` end-to-end and asserts
  `'"command":"python","env":{},"args":["-m","server"]'` appears in the
  emitted `.mcp.json` file content.

Manually re-verified the real pull-books-shaped output:
```
{"mcpServers":{"pull-books":{"command":"uv","env":{},"args":["run","--project","/path","pull-books","mcp"]}}}
```

### Full suite + lint (round 2)

`uv run pytest -q` → **533 passed, 16 skipped** (2 new tests added since
round 1; same 16 env-gated subprocess skips, unrelated).

`uv run ruff check src/cisternal/export/claude.py src/cisternal/export/claude_rust.py src/cisternal/export/_rust_emit.py tests/test_export_claude.py tests/test_claude_rust_parity.py`
→ **All checks passed!**

### Files changed (round 2, in addition to round 1)

- `src/cisternal/export/_rust_emit.py` — reordered `mcp_servers_json()`
  field insertion to `command`, `env`, `args` (matching `bundle_claude.rs`'s
  literal insertion order); rewrote the docstring to cite the real
  `preserve_order`/insertion-order rationale instead of the incorrect
  alphabetical/`BTreeMap` claim.
- `tests/test_claude_rust_parity.py` — added `McpAsset`/`AssetBundle`/
  `BundleMetadata`, `compact_json`/`mcp_servers_json`, and
  `emit_claude_rust_parity` imports; added the two literal-string
  field-order regression tests described above.

### Self-review (round 2)

- Verified the corrected insertion order against the actual Rust source a
  second time, specifically for literal field-insertion order (not just
  which fields exist) — confirmed `command`, `env`, `args`.
- Confirmed via `Cargo.toml` inspection (not just trusting the reviewer's
  claim) that `praxia-core` requests `preserve_order` and
  `praxia-agent-assets` depends on `praxia-core`, so feature unification
  applies.
- Confirmed `claude.py` (legacy path) is unaffected by this class of bug —
  it always serializes with `json.dumps(..., sort_keys=True)`, so field
  insertion order there is a non-issue regardless of dict construction
  order.
- New tests assert on the literal `compact_json()` string output
  specifically so a future insertion-order regression would be caught
  (dict-equality-based tests cannot catch this class of bug).

No remaining concerns.
