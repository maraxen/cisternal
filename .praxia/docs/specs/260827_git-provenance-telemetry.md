---
title: Git provenance in telemetry — buildable spec
description: Adds git SHA/branch/dirty-state capture as a first-class cisternal telemetry field, consumed consistently by bathos and myxcel
status: draft
task_id: 260827_git-provenance-telemetry
date: '260827'
backlog_ids: ''
adversarial_review: ''
---
# Git provenance in telemetry — buildable spec

## Motivation

Scoping pass (260827) found cisternal's telemetry substrate carries **zero** git
provenance: `Record` (telemetry/record.py) has `run_uuid`, `mcp_request_id`, `task_id`,
`request_id`, `session_id`, `phase` — no git SHA, branch, dirty flag, or anything
resembling one. `grep -rn "git_sha\|git_hash\|subprocess.*git" src/` returns nothing.
`init()`/`init_pipeline()` have no process-start capture step to hang it on either.

This isn't hypothetical: praxia's own harness-level telemetry (`.praxia/telemetry.jsonl`,
a separate stream from cisternal's own pipeline) already carries placeholder `"commit": ""`
and `"branch": "unknown"` fields that are simply never populated — direct evidence the gap
bites in practice, not just an abstract completeness concern.

Three Praxia-family tools currently handle this independently, with real drift risk:

- **myxcel** (`src/myxcel/provenance.py`) owns the most complete implementation: async
  `git rev-parse`/`git status --porcelain` for hash/branch/dirty, PLUS a genuinely hard
  piece — `dirty_content_id`, a content-addressable id for the *uncommitted* state, computed
  via `git write-tree` (real git plumbing, hashes the current index+worktree into a tree
  OID) with a `sha256(git diff)` fallback if `write-tree` fails. This exists because a dirty
  commit SHA alone can't distinguish two different uncommitted states — critical when a job
  is dispatched to a cluster node with no git access to the origin repo. myxcel serializes
  this across the local→remote boundary via env vars (`MYXCEL_GIT_SHA`, etc.) and a
  versioned JSON sidecar (`.myxcel_provenance.json`).
- **bathos** (`src/bathos/git.py`) does NOT reimplement the tree-OID algorithm; it consumes
  myxcel's env/sidecar channel when present (with a same-root check to avoid trusting stale
  or foreign provenance), falling back to its own plain `git rev-parse`/`git status
  --porcelain` shellout when no channel exists. Its `GitState` dataclass: `hash`, `branch`,
  `dirty`, `dirty_content_id` (nullable — `None` when only the local shellout ran, no tree
  OID), `provenance_source` (`"git" | "myxcel-env" | "myxcel-sidecar" | "none"` — so a
  record can explain *where* its git fields came from). Never raises; `_UNKNOWN` sentinel
  (`hash="unknown", branch="unknown", dirty=False`) as universal fallback.
- **contemplex** has nothing.

cisternal is already a real dependency of both (`bathos: cisternal>=0.1.1a3`,
`myxcel: cisternal>=0.1.1a5`), and both wrap `cisternal.emit_event`/`cisternal.tool` for
their own telemetry (`bathos.telemetry.event()` → `bathos.telemetry_bridge.emit_via_cisternal`
→ `cisternal.emit_event`). Given cisternal's stated purpose — "shared telemetry substrate
... for the Praxia tool family" — the local git-state-capture primitive belongs there once,
not duplicated in one place (myxcel), partially reimplemented in another (bathos), and
absent everywhere else (contemplex, cisternal itself).

## Goals

1. cisternal.telemetry gets a canonical, never-raising `capture_git_state()` + `GitState`
   dataclass: hash/branch/dirty/dirty_content_id/provenance_source for the *local* repo.
   No cross-boundary channel logic (env vars, sidecar files) — that stays myxcel-specific.
2. cisternal captures this **once per process**, at `init()` time — not per-event, which
   would violate the pipeline's existing off-hot-path design (`emit()` must stay
   non-blocking; shelling out to git on every `emit_event` call is not acceptable). Every
   `Record` built after `init()` carries it via a new contextvar, mirroring the existing
   `session_id_var`/`task_id_var` pattern in `context.py`.
3. bathos's `git.py` delegates its local-shellout tier to cisternal's `capture_git_state()`,
   keeping its own env/sidecar channel-precedence logic untouched.
4. myxcel's `provenance.py` delegates its local git-state capture AND its
   `dirty_content_id` computation (tree-OID / diff-sha256 fallback) to cisternal's
   `capture_git_state()`, keeping its own env-var serialization, JSON sidecar, and
   cluster-dispatch comparison logic (`resolve_submit_provenance`) untouched.
5. No behavior change to bathos's Run/Arrow schema or myxcel's sidecar JSON schema/wire
   format — this is an internal implementation consolidation for both consumers, not a
   schema migration.

## Non-goals

- Moving bathos's env/sidecar channel-reading logic into cisternal (stays consumer-specific
  — not every cisternal user needs cluster-dispatch provenance propagation).
- Changing bathos's Run/Arrow schema or myxcel's sidecar JSON `schema_version`.
- contemplex integration (flagged as a follow-up, not bundled here).
- Retroactively backfilling git fields into historical JSONL/Parquet records.
- Other gaps noted during scoping but deliberately deferred: a `schema_version` field on
  `Record` itself, embedding hostname/pid inside the Record (currently only in the JSONL
  filename), a cisternal-package-version field, and bathos's `dependency_lock_sha256`
  pattern. Worth a future pass; not part of this change.

## Design

### `cisternal.telemetry.git_state` (new module)

```python
@dataclass(frozen=True, slots=True)
class GitState:
    hash: str                             # "unknown" | "nogit" | actual sha
    branch: str                           # "unknown" | "nogit" | actual branch name
    dirty: bool
    dirty_content_id: str | None = None   # git write-tree OID, or sha256(diff) fallback
    provenance_source: str = "git"        # "git" | "nogit" | "unavailable"
    toplevel: str | None = None           # `git rev-parse --show-toplevel`, see Risks

def capture_git_state(
    cwd: Path | None = None,
    *,
    compute_dirty_content_id: bool = True,
) -> GitState:
    """Never raises. cwd defaults to Path.cwd()."""
```

Behavior:
- Not a git repo → `GitState(hash="nogit", branch="nogit", dirty=False, provenance_source="nogit")`
- git binary missing / any subprocess error → `GitState(hash="unknown", branch="unknown", dirty=False, provenance_source="unavailable")`
- Success → real hash/branch/dirty/toplevel; if dirty and `compute_dirty_content_id`, try
  `git write-tree` for a real tree OID, falling back to `sha256(git diff bytes)` if
  `write-tree` fails (e.g. dirty state includes untracked files write-tree won't see without
  a temp index — match myxcel's existing fallback semantics exactly); `provenance_source="git"`.

### Record / context wiring

- Add `git_state_var: ContextVar[GitState | None]` (default `None`) to `context.py`.
- `init()`/`init_pipeline()` calls `capture_git_state()` once and sets the contextvar.
  (Defense in depth only — `capture_git_state()` itself never raises — but `init()` must
  not be able to fail because of this call regardless.)
- Add 5 new fields to `Record`: `git_hash`, `git_branch`, `git_dirty`,
  `git_dirty_content_id`, `git_provenance_source` — populated from `git_state_var.get()` in
  `_build_record()`. Unlike bathos's non-nullable-with-sentinel convention, these are
  `str | None` / `bool | None` on cisternal's `Record`, since a `Record` can legitimately be
  built before `init()` ran (or with git capture never having happened) — `None` means "not
  captured," not "captured, and it's unknown."
- Verify `JsonlExporter`/OTLP exporter serialize the full `Record` already (likely no
  exporter-side change needed, but confirm during implementation).

### bathos changes (`src/bathos/git.py`)

- Replace `_legacy_git_shellout` and the local-tier branch of
  `_git_shellout_with_toplevel` with a call to
  `cisternal.telemetry.git_state.capture_git_state()` — field names already match closely
  enough that this should be closer to a passthrough than a remapping.
- Keep `_env_channel`, `_sidecar_channel`, `_same_root`, and the precedence orchestration in
  bathos's own `capture_git_state()` (same name, different module) exactly as-is.
- Bump bathos's `cisternal` dependency floor to the release that ships this.

### myxcel changes (`src/myxcel/provenance.py`)

- Replace `_git_rev_parse`, `_is_git_dirty`, `_compute_tree_oid`, `_compute_diff_sha256`
  internals with a call to cisternal's `capture_git_state()`. myxcel's functions are
  `async def`; cisternal's `capture_git_state()` is sync (subprocess-based) — wrap via
  `asyncio.to_thread()` so the async call signature and non-blocking behavior are preserved.
- Keep `to_json_bytes`, `to_env`, `state_record_path`, `write_state_record`,
  `read_state_record`, `resolve_submit_provenance` as-is (myxcel-specific cross-boundary
  propagation — out of scope for consolidation).
- Bump myxcel's `cisternal` dependency floor similarly.

## AC matrix

| AC | Then |
|----|------|
| AC-1 | `capture_git_state()` returns correct hash/branch/dirty for: a clean repo, a dirty repo, a non-repo dir, and (mocked) missing git binary — never raises in any case |
| AC-2 | `dirty_content_id` differs between two different dirty working-tree states at the same commit (proves content-addressability, not just a dirty bool) |
| AC-3 | `cisternal.init()` populates `git_state_var`; a `Record` built after `init()` carries non-None `git_hash`/`git_branch`/`git_dirty` |
| AC-4 | A `Record` built *before* `init()` (or with git capture skipped) has `None` git fields — never raises either way |
| AC-5 | bathos's own `capture_git_state()` (post-refactor) produces field-identical `GitState` output to pre-refactor, for the local (no-channel) case, against a fixture repo — behavior-parity test, not new coverage |
| AC-6 | myxcel's `build_provenance_record` produces identical `ProvenanceRecord` output pre/post refactor for a fixture repo (clean and dirty cases), confirming the `asyncio.to_thread` wrapping changes nothing observable |
| AC-7 | No change to bathos's `Run` Arrow schema, myxcel's sidecar JSON `schema_version`, or wire formats (env var names, JSON keys) |

## Rollout sequence

1. **cisternal**: implement + release as the next pre-release after the current
   export-surfaces work (0.1.1a6) lands — this spec's primary deliverable.
2. **bathos**: bump `cisternal` floor to the new release; refactor `git.py` to delegate;
   run bathos's existing `git.py` test suite (behavior parity is the bar; add AC-5's parity
   test if none already covers this).
3. **myxcel**: same pattern for `provenance.py`; add AC-6's parity test.
4. **contemplex**: flagged as a follow-up, not in this spec's scope.

## Risks

- **Async/sync boundary in myxcel**: `capture_git_state()` is sync; `provenance.py` is
  async throughout. Wrapping via `asyncio.to_thread` must not change error-handling timing
  or ordering relative to the rest of `build_provenance_record`'s await chain — verify with
  AC-6 rather than assuming.
- **`toplevel` field**: bathos's reconciliation (`_same_root(toplevel, prov.get("root"))`)
  needs the git toplevel path from the *same* fresh shellout batch it's comparing against a
  channel's claimed root. Proposed fix: add `toplevel: str | None` as a field on the shared
  `GitState` (one more `git rev-parse --show-toplevel` call inside the same never-raise
  block cisternal already runs) rather than having bathos issue a second, separate git
  subprocess call after delegating. **This is a design call worth confirming during
  implementation, not decided by fiat here** — the alternative (bathos keeps its own
  toplevel lookup) also works, just duplicates one more subprocess call per capture.
- **Never-raise contract inheritance**: cisternal's `capture_git_state()` needs to satisfy
  the same "never raises" bar bathos and myxcel already independently guarantee (CH-5/C6 in
  their respective specs) — this is a hard requirement, not a nice-to-have, since both
  consumers currently rely on it structurally (bathos wraps its whole `capture_git_state()`
  orchestrator in a bare `except Exception: return _UNKNOWN`; myxcel's callers assume
  `build_provenance_record` degrades to warnings, never an exception).

## Out of scope for this pass (noted for future work)

- contemplex adopting git provenance.
- A `schema_version` field on `Record` (separate, valid gap noted during scoping).
- hostname/pid/cisternal-package-version fields on `Record` (same).
- bathos's `dependency_lock_sha256` pattern generalized into cisternal.
