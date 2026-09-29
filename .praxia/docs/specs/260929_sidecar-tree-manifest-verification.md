---
title: Sidecar tree-manifest verification — buildable spec
description: Stop the provenance reader from presenting an unverified sidecar/env git sha as authoritative; add one shared tree-manifest writer+verifier for no-.git hosts
status: accepted-rev-a
task_id: 260929_sidecar-verify-2060
date: '260929'
backlog_ids: 'praxia debt #2060 (consumers: bathos #2058, myxcel #2059)'
adversarial_review: 'rev. A — challenger has_gaps / defender needs_revision, resolved in §7'
---
# Sidecar tree-manifest verification — buildable spec

## 1. Problem (verified 2026-09-29)

`src/cisternal/provenance/channels.py`:

- `_sidecar_channel()` (line 92) ascends from cwd, returns `None` at the first `.git`, otherwise
  returns the sidecar's `git_sha` once `schema_version`/`provenance_status` parse. It never
  compares anything to the files on disk.
- `capture_git_state()` (line 182) surfaces that value as `GitState.hash` with
  `provenance_source="myxcel-sidecar"`. The env channel (`_env_channel`, line 58) has the same
  flaw.
- `sync_state` is computed by myxcel **at push time on the local side**
  (`myxcel/src/myxcel/provenance.py:449-456`: stored push record vs local sha/dirty id). It says
  nothing about the remote tree after later out-of-band deploys. `dirty_content_id` is a git tree
  OID computed through a throwaway index **in the local repo** (`capture.py:256`,
  `telemetry/git_state.py:124`). The reader cannot recompute it without a repo.

Measured harm: `titanix:/home/solab/projects/protamer` sidecar from 2026-08-28 (`git_sha`
9d0b875, not an ancestor of the code that ran) was recorded by bathos on runs fb86e0d1 and
911587f9. Exposure: 11 sidecars in directories without `.git` (3 titanix, 7 Engaging).

Consumer facts that constrain the design (read from source, not recalled):

- `bathos/src/bathos/git.py` re-exports `GitState`, `capture_git_state`, **and the private
  `_sidecar_channel` and `_same_root`** (bathos `tests/test_git.py:300` imports
  `_sidecar_channel`).
- bathos gates on the **string** sentinel: `postmortem.py:280` (`git_state.hash != "unknown"`),
  `mcp.py:3463` (`if git_state.hash == "unknown": refuse gate stamp`), `checker.py:92`
  (`run.git_hash == "unknown"` → `UNKNOWN_CODE`). `decorators.py:46`, `runner.py:604`,
  `runlog/envelope.py:126` and `artifact_archive.py:285` copy `.hash` into records.
- myxcel does **not** use cisternal's writer yet: it keeps its own `ProvenanceRecord` in
  `myxcel/src/myxcel/provenance.py` and writes the sidecar in `rsync.py:550` from
  `to_json_bytes`. Its push already computes the exact transferred file set
  (`rsync.py:164-173`, `git ls-files -z --cached --others --exclude-standard` minus profile
  excludes → `--include-from … --exclude '*'`).
- The name "manifest" is taken in this package: `durable.py`'s `refs/manifest.jsonl` run-pin
  ledger (out of scope). The new concept is the **tree manifest** everywhere in code and docs.

## 2. Measured cost and eol behaviour

Pre-registered benchmark `scripts/bench/tree_manifest_hash_cost.py` (+ `.bth.toml`, committed
before the run), bathos run `b605abb0`. Synthetic 5,000-file tree, 40.5 MB, **outside any
repo** (`tree_inside_git_repo: false`):

| check | result |
|---|---|
| pure-Python `sha1(b"blob %d\0"+bytes)` vs one batched `git hash-object --no-filters --stdin-paths` | 5000/5000 agree |
| negative control: one-byte edit changes hash | fired |
| negative control: CRLF file with filters under `core.autocrlf=true` ≠ `--no-filters` | fired |
| CRLF `--no-filters` == pure Python | true |
| wall time, best of 3 | Python 0.074 s · git 0.149 s |

Caveat: bathos recorded `outcome=null` for this run (the wrapped `bth run -- uv run …` form did
not bind the sidecar), so the outcome was evaluated by hand against the committed
`[outcomes.pass]` condition: **pass**.

Conclusions: verification is cheap enough to run on every capture (no caching layer). Filters
(autocrlf, LFS, `text`/`eol` attributes) change git's blob ids, so both sides must hash **raw
working-tree bytes with no filters**, never index blobs.

## 3. Decisions

### D1 — Tree manifest format and scope

```json
{
  "manifest_version": 1,
  "hash_algo": "git-blob-sha1-nofilter",
  "commit": "<40-hex or null>",
  "tree_id": "<40-hex git tree OID computed from `files`>",
  "declared_dirs": ["scripts", "src"],
  "matches_commit": false,
  "extra_excludes": ["*.swp", ".ipynb_checkpoints/"],
  "files": {"src/pkg/mod.py": ["100644", "<40-hex blob id>"], "...": ["120000", "..."]},
  "skipped": []
}
```

- `matches_commit` (rev. A, B1). The writer computes this from the **same bytes** it hashed. It
  is true iff (a) every manifest entry is tracked in `commit` and its raw blob id equals the
  `git ls-tree -r <commit>` blob id, and (b) the manifest has no untracked entries. Tracked files
  the push deliberately excluded (profile excludes) do not count against it: they were not
  transferred. autocrlf/LFS make raw blobs differ from index blobs, which gives `false`, the
  safe direction.
- `extra_excludes` (rev. A, M2) holds the ignore patterns that shaped the push allowlist but do
  not live in the tree's own `.gitignore` files: `.git/info/exclude`, `core.excludesFile`, and
  the myxcel profile excludes. The reader applies them to the extras listing.

- **Recommendation: scope = every file the push transferred**, not only declared directories.
  The protamer drift could have been in any file, and hashing everything costs 0.07 s per 5k
  files. Default enumeration when the writer passes no `paths`:
  `git ls-files -z --cached --others --exclude-standard`, dropping tracked-but-deleted paths.
  That is the same set as `dirty_content_id`'s throwaway-index `add -A` and myxcel's push
  allowlist. myxcel passes its computed allowlist explicitly (`paths=`), so the manifest equals
  what was actually transferred, profile excludes included.
- Modes: `100644`, `100755`, `120000` (symlink: blob = link target bytes, not followed).
  Submodule gitlinks are skipped and listed in a `skipped` array. Paths are POSIX, relative, and
  sorted. `PROVENANCE_FILENAME` is always excluded.
- `declared_dirs` = the directories scanned for **extra** files. Default: the sorted set of
  top-level directory components of the manifest's files. The root is **not** scanned unless
  `"."` is declared, because roots accumulate outputs, venvs and the sidecar itself.
- **Untracked files under declared dirs are reported and FAIL verification** (D2). The listing
  is ignore-aware: a hermetic `git -c safe.directory=* -c core.excludesFile=<tmp file of
  extra_excludes> --git-dir=<tmp empty repo> --work-tree=<root> ls-files -z -o
  --exclude-standard -- <scan dirs>` with `GIT_CONFIG_GLOBAL=/dev/null` and
  `GIT_CONFIG_NOSYSTEM=1`. That needs git but no `.git` in the root, and it applies the tree's
  own `.gitignore` files plus `extra_excludes` exactly as the push did. `safe.directory=*`
  avoids git's dubious-ownership refusal on shared trees owned by another user.
  - **git absent** (FileNotFoundError): fall back to a Python walk that skips `.git`,
    `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ipynb_checkpoints`, and `*.egg-info`, with
    `extras_ignore_aware=False`. It over-reports, which withholds the sha.
  - **git present but exits nonzero:** `verified=False` with `error` set. There is no fallback.
- **cwd coverage (rev. A, B2).** Scan dirs = `declared_dirs`, plus cwd's directory
  (non-recursive) when cwd is not under a declared dir. If cwd is not inside the sidecar's
  directory, the sha is withheld. Known, documented gap: root-level extras are not scanned unless
  `"."` is declared. Root-level *manifest* files are still hashed, so edits and deletions there
  are caught. A default recursive `"."` scan was rejected: outputs that are not gitignored would
  make every subsequent capture fail.
- Storage: **embedded in the sidecar** as `ProvenanceRecord.tree_manifest` (sidecar
  `schema_version` 2). One atomic write (myxcel's existing tmp+mv), so the sidecar and manifest
  cannot drift apart. `to_env()` omits it (too large for env).

### D2 — `verify_tree(root, manifest) -> TreeVerification`

```python
@dataclass(frozen=True)
class TreeVerification:
    verified: bool            # manifest_ok and not mismatched and not missing and not extra
    n_files: int
    n_match: int
    mismatched: tuple[str, ...]                       # content differs
    missing: tuple[str, ...]
    extra_untracked_under_declared_dirs: tuple[str, ...]
    mode_changed: tuple[str, ...]                     # reported, does NOT fail
    manifest_ok: bool         # recomputed tree_id == manifest.tree_id, known version/algo
    extras_ignore_aware: bool
    tree_id: str | None       # recomputed from disk; == manifest.tree_id iff content matches
    error: str | None         # set => verified False
```

- Never raises. Any exception (including PermissionError on a single file) gives
  `verified=False` with `error` set.
- **Budget (rev. A, M4):** `max_bytes` (default 4 GiB) and `max_seconds` (default 60). Exceeding
  either gives `verified=False`, `error="budget exceeded: …"`. **No cache.** A cache keyed on the
  sidecar's stat was rejected: the thing that changes is the tree, so a cached `verified=True`
  would outlive an edit and break the hard rule. §2's "no caching needed" was measured on local
  disk only. Engaging's network filesystem is unmeasured, which is why the budget exists.
- Paths are handled as UTF-8. Entries are sorted by their UTF-8 bytes (git order). A file name
  that is not valid UTF-8 goes into `skipped` and sets `verified=False`. Symlinks are read with
  `os.readlink` and never followed.
- Verification describes the tree **at capture time**. Edits after capture (TOCTOU) are outside
  what any capture-time check can see.
- Hashing is **pure-Python git-blob-sha1 over raw bytes**. This deviates from the brief's
  "use `git hash-object`": the measurement shows identical ids on 5000/5000 files, half the time,
  and no dependency on a git binary on the compute host. A test cross-checks against
  `git hash-object --no-filters` so the equivalence stays enforced.
- Content comparison uses blob ids only. The mode (exec bit) is reported but not compared,
  because rsync `-a` usually preserves it and a chmod is not a code change.
- `tree_id` is a git tree OID computed in Python from `(mode, path, blob)` entries (git's
  sort order, with trees sorted as `name + "/"`). A test checks it against `git write-tree`.

### D3 — `GitState` and the hard rule

`channels.GitState` gains:

```python
code_verified: bool | None = None   # True: the reported identity (hash, dirty,
                                    #   dirty_content_id) was checked against disk NOW.
                                    #   It does NOT mean "disk == commit"; read `dirty`.
                                    # False: checked and did not match; None: could not check
verification: TreeVerification | None = None
@property
def sha(self) -> str | None: ...    # the hash iff it is 40 lowercase hex, else None
```

- **Hard rule.** A sidecar or env channel surfaces its sha **only** when every one of these
  holds:
  1. the record carries a parseable tree manifest;
  2. `manifest.commit == record.git_sha`. This mainly catches spliced or hand-edited sidecars,
     since both come from one `rev-parse`;
  3. cwd is inside the sidecar's directory;
  4. `verify_tree(<the sidecar's directory>, manifest).verified`.
- **`dirty` for a verified channel (rev. A, B1):**
  `dirty = (record.git_dirty is not False) or not manifest.matches_commit`. `False` requires
  positive evidence from both the record and the manifest. The old fallback to `False` for a
  missing or malformed `git_dirty` (`channels.py:233-239`) no longer applies to channel results.
  A verified dirty push surfaces `(hash=HEAD, dirty=True, dirty_content_id)`, exactly what live
  git reports for a dirty tree.

  Otherwise it returns `hash="unknown"`, `branch="unknown"`, `dirty=True`,
  `dirty_content_id=None`, `code_verified=False` (checked and failed) or `None` (no manifest /
  unreadable), and `provenance_source="unverified-sidecar"` / `"unverified-env"`.
- **Why `hash="unknown"` rather than `None`.** Every bathos guard compares against the string
  `"unknown"` (§1). `None` would pass `mcp.py:3463`'s check and stamp a gate with a null sha.
  `"unknown"` makes each existing guard fail closed with no consumer change. `GitState.sha`
  gives the requested `None`-valued accessor, and the claimed sha appears nowhere on the
  returned `GitState`. Forensics use `read_sidecar()`.
- Where verification runs: the sidecar's own directory (the channel root) for the sidecar
  channel. For the env channel, `MYXCEL_PROVENANCE_ROOT/PROVENANCE_FILENAME` is read for the
  manifest, and its `git_sha` must equal `MYXCEL_GIT_SHA`.
- Live git keeps precedence exactly as today (same root, or linked worktree of the channel's
  repo) and reports `code_verified=True`. `_UNKNOWN` keeps `code_verified=None` and is returned
  as a fresh instance per call, never a shared mutable object.
- `provenance_status == "nogit"` records keep `hash="nogit"` (no sha to protect).
  `code_verified` comes from the manifest if present, else `None`.
- `dirty_content_id` for a verified channel = the record's own value (vouched for transitively:
  captured at the same instant as a manifest the disk now matches).
- `_sidecar_channel()` keeps its signature and dict shape. It adds the keys `tree_manifest` and
  `sidecar_path` (additive; bathos's `test_git.py` imports it).

### D4 — Back-compat: enforce immediately, no restore flag

**Recommendation: enforce now.** No warn-only phase and no flag that restores the old behaviour.

- The harm is active: every capture on a no-`.git` host writes a possibly false sha into bathos
  records today. A warn phase keeps producing them.
- The failure direction is a state every consumer already handles (`"unknown"` →
  `UNKNOWN_CODE`, gate refusal, drift check skipped).
- A restore flag would be a switch that re-enables the defect. Anyone who needs the old value
  can still get it from `read_sidecar()`.

On first withholding per sidecar path per process, the reader emits a `warnings.warn` naming
the path, the reason (`no tree manifest (schema v1 sidecar)` / `N mismatched, M missing, K
extra` / `manifest commit != git_sha`) and the fix: re-push with a manifest-writing myxcel
(#2059), or run `myxcel clean` for stale leftovers. **The warning text never contains a sha.**
It is emitted inside its own `try`, so `-W error` cannot turn an `unverified-*` result into the
catch-all `_UNKNOWN`.

**Release order (rev. A, m8).** Nothing changes for bathos until it bumps its cisternal pin.
Ship cisternal (this change), then the bathos pin bump (#2058), then the myxcel v2 writer
(#2059). Between steps 2 and 3, no-`.git` hosts report `"unknown"`, which is the intended
fail-closed interim.

**Rejected: writing `git_sha: null` in v2 so old readers fall back to `"unknown"`
(challenger M1).** myxcel's submit-time drift check compares `stored.git_sha` with the fresh sha
(`myxcel/provenance.py:449-452`), so a null would mark every submit `drifted`. It would also
drop hard-rule condition 2. Old readers already leak the same sha from today's v1 sidecars, and
the pin bump is the fix.

What breaks until myxcel #2059 ships schema-v2 sidecars:

1. Every no-`.git` host (the 11 known sidecars) reports `hash="unknown"`. bathos records
   `git_hash="unknown"`, `git_provenance_source="unverified-sidecar"`.
2. bathos `mcp.py:3463` gate stamping refuses on those hosts, and `postmortem.py:280`'s drift
   check is skipped.
3. The bathos tests that assert a sidecar/env sha is surfaced
   (`tests/test_git.py::test_sidecar_channel_used_when_no_env` and the env-channel tests) fail.
   They belong to bathos #2058, not this change.
4. New `provenance_source` values appear. bathos stores the field as a free string
   (`schema.py:86`), so nothing breaks structurally.
5. Old readers (a bathos pinned to a pre-change cisternal) reading a v2 sidecar warn "newer
   schema" and still surface the sha. That cannot be fixed from here. It is why bathos must bump
   its cisternal pin (#2058).
6. `provenance_status="nogit"` still yields `hash="nogit"`. bathos `mcp.py:3463` refuses only on
   `"unknown"`, so it would stamp a gate with `"nogit"`. That gating decision belongs to #2058.
7. A push is additive (`myxcel/rsync.py:398`, "No --delete"). A file renamed or deleted locally
   stays on the remote. Under a scanned dir it fails verification until someone runs
   `myxcel clean` or does a `--delete` push. That is intended: a stale module can still be
   imported.

### D5 — What `dirty_content_id` means for a non-repo tree

- **Retained with its current meaning**: a git tree OID of the push-time working tree as the
  local repo's `add -A` saw it, filters included. It is **not recomputable** on a non-repo host
  and is **no longer a verification input**. It is surfaced only when the manifest verifies (D3).
- The recomputable content id for a non-repo tree is the manifest's `tree_id` (raw bytes, no
  filters). `TreeVerification.tree_id` is its value recomputed from disk. With no clean filters
  and scope equal to `add -A`, `tree_id == dirty_content_id` minus the `tree:` prefix. The
  verifier reports `dirty_content_id_consistent: bool | None` as information only, because
  filters legitimately break the equality.

### D6 — One module, public API

New module `src/cisternal/provenance/tree_manifest.py` holds both halves. Writer and reader
import nothing from each other's repo, only from here:

```python
# writer (myxcel, at push)
build_tree_manifest(root: Path, *, commit: str | None, paths: Iterable[str] | None = None,
                    declared_dirs: Iterable[str] | None = None) -> TreeManifest | None
build_provenance_record(..., tree_manifest: TreeManifest | None = None)  # schema 2 when set
to_json_bytes(record)                        # unchanged call, now embeds tree_manifest

# reader (bathos, or anyone)
capture_git_state(cwd) -> GitState           # behaviour change per D3
verify_tree(root: Path, manifest: TreeManifest) -> TreeVerification
read_sidecar(path_or_dir: Path) -> ProvenanceRecord | None   # raw record, forensics

# types
TreeManifest(manifest_version, hash_algo, commit, tree_id, declared_dirs, files, skipped)
    .to_dict() / TreeManifest.from_dict(d) -> TreeManifest | None
TreeVerification (D2)
```

`ProvenanceRecord` gains `tree_manifest: dict | None = None` (JSON form).
`read_state_record` parses it. The reader's max known `schema_version` becomes 2.
`build_tree_manifest` returns `None` (with a logged reason) on failure, matching the
best-effort convention in `capture.py`.

## 4. Tests (negative first; each must be able to fail)

New `tests/test_provenance_tree_manifest.py`, extended `tests/test_provenance_channels.py`,
`tests/test_provenance_record.py`:

1. File modified after the manifest was written → `verified=False`, path in `mismatched`.
2. Manifest for a different commit (`manifest.commit != record.git_sha`) → channel withholds
   the sha.
3. Missing file → `verified=False`, path in `missing`.
4. Extra untracked non-ignored file under a declared dir → listed in
   `extra_untracked_under_declared_dirs` and `verified=False`. The same file matched by the
   tree's `.gitignore` → not listed.
5. **Real protamer fixture** (verbatim JSON from the debt) next to a non-matching tree → `hash
   == "unknown"`, `sha is None`, `"9d0b875" not in repr(state)`,
   `provenance_source == "unverified-sidecar"`, `code_verified is None`.
6. The same fixture with a manifest that does not match → `code_verified is False`.
7. Env channel with no manifest at the root → `"unverified-env"`, sha withheld.
8. Untouched tree → `verified=True`, the channel surfaces the sha, `code_verified=True`.
9. Equivalence: pure-Python blob ids == `git hash-object --no-filters`; Python `tree_id` ==
   `git write-tree` of the same files in a temp repo.
10. A live `.git` at the channel root still wins over any sidecar (existing tests stay green).
11. Record round-trip: a v2 record with a manifest survives `to_json_bytes` →
    `read_state_record`, and `to_env` omits the manifest.
12. (rev. A) A verified dirty push → sha surfaced with `dirty is True`. A verified clean record
    with `matches_commit=False` → `dirty is True`. A missing `git_dirty` → `dirty is True`.
13. (rev. A) An ancestor sidecar with cwd in an uncovered subdir holding an extra file →
    withheld. cwd outside the sidecar dir → withheld.
14. (rev. A) A stale leftover file (present remotely, absent from the manifest, under a declared
    dir) → withheld.
15. (rev. A) A tampered `tree_id` → `manifest_ok=False`. A malformed manifest → `from_dict` is
    `None` and `code_verified is None`. A v2 record without a manifest → withheld.
16. (rev. A) git exits nonzero → `verified=False` with `error` set. git absent → fallback walk
    with `extras_ignore_aware=False`. A file matched by `extra_excludes` → not an extra.
17. (rev. A) Budget exceeded → `verified=False`. PermissionError on one file → `error` set.
18. (rev. A) The warning text contains no sha. Under `warnings.simplefilter("error")` the result
    is still `unverified-sidecar`. `dataclasses.asdict(state)` contains no sha for test 5.
19. (rev. A) `matches_commit` writer-side: a clean repo → true; a modified tracked file → false;
    an untracked file in `paths` → false.

Existing channel tests that assert a manifest-less sidecar/env sha is surfaced get updated to the
new contract (manifest present → surfaced; absent → withheld). Each change is listed in the PR.

## 5. Fixer tasks

| # | change | files | gate |
|---|---|---|---|
| F1 | `tree_manifest.py`: `TreeManifest`, `TreeVerification`, `build_tree_manifest`, `verify_tree`, blob/tree hashing | new module + `tests/test_provenance_tree_manifest.py` | tests 1, 3, 4, 8 (tree level), 9 |
| F2 | `record.py`/`capture.py`: `tree_manifest` field, schema 2, `read_sidecar`, `build_provenance_record(tree_manifest=)` | record.py, capture.py, `tests/test_provenance_record.py` | test 11 |
| F3 | `channels.py`: gating per D3, `GitState` fields, env channel, warnings | channels.py, `tests/test_provenance_channels.py` | tests 2, 5, 6, 7, 8, 10 |
| F4 | exports in `provenance/__init__.py` | `__init__.py` | import smoke |

Out of scope: bathos fail-closed policy (#2058), myxcel bundle deploy / stamp / manifest writing
(#2059), `refs/manifest` pin on pull, any consumer-repo edit.

## 6. Risks

| risk | mitigation |
|---|---|
| Declared-dir extras flap on generated files (e.g. `_version.py`) | ignore-aware listing uses the tree's own `.gitignore`; generated files that are not ignored are real divergence |
| `hash="unknown"` fleet-wide until #2059 | intended (D4); warning names the fix |
| Large sidecar (≈110 B/file ≈ 550 KB at 5k files) | one read per capture; measured hashing dominates |
| Symlink escaping root | hash link target bytes, never follow |
| Additive push leaves stale files → permanent `"unknown"` | intended fail-closed; warning names `myxcel clean` / `--delete` push (test 14) |
| Network-filesystem hashing cost unmeasured | `max_bytes`/`max_seconds` budget → withheld, never cached |

## 6b. Implementation review amendments (rev. B, 2026-09-29)

A Sonnet code review of the implementation returned NEEDS_WORK. The orchestrator reproduced the
first two items below before accepting any of them.

- **Empty manifest fails.** `verify_tree` on a manifest with no files returns `verified=False`
  (`error="empty manifest"`), and `build_tree_manifest` returns `None` for an empty file set.
  Reproduced: an empty allowlist previously verified vacuously and would have surfaced the sha.
- **Built-in bytecode exclude (rev. C: `__pycache__/` only).** Bytecode inside `__pycache__`
  is always excluded from the extras listing. Reproduced: without this, the first Python import
  on a host whose `.gitignore` lacks `__pycache__` withholds the sha permanently. This is safe
  because a sourceless `.pyc` inside `__pycache__` is never imported. Rev. B's unanchored
  `*.pyc`/`*.pyo` was **reverted** after the re-review: a sourceless legacy-location
  `src/pkg/mod.pyc` is importable (SourcelessFileLoader) and was reproduced passing
  verification. It must be reported as an extra.
- **Gitlinks (rev. C: fail closed).** Nested repos and submodules are recorded as
  `skipped: "gitlink:<path>"`. Their contents are not hashed, so **any skipped entry, gitlinks
  included, fails verification** and the sha is withheld. Their contents are left out of the
  extras listing only because the gitlink reason already explains the failure. Rev. B's
  "gitlinks pass" was rejected: build classifies *any* directory entry as a gitlink, so exempting
  them would let a code directory escape all checks. Verifying submodules properly (mode 160000
  plus the recorded commit) is deferred. Until then, trees with submodules report `"unknown"`.
- **Non-UTF-8 names from `ls-files`** are recorded as `non-utf8:<repr>` in `skipped`, never
  dropped (rev. C).
- **The budget covers the extras phase** (rev. C): every subprocess timeout and each step of the
  fallback walk draws on the remaining `max_seconds`. The budget is re-checked after the final
  file.
- **Streaming hashing.** Files are hashed in chunks. The budget is checked after each file, and
  the extras scan counts against `max_seconds`. A path that is not a regular file (e.g. a FIFO)
  fails verification instead of blocking. A symlink changed to a regular file, or back, counts as
  mismatched.
- **Strict `from_dict`.** `matches_commit` must be a bool. Hex fields must be 40 lowercase hex
  characters.
- **Warning key.** The withheld warning for a record with no sidecar path uses a fixed key, never
  the claimed sha. This was reproduced as a leak.

## 7. Adversarial review (rev. A, 2026-09-29)

- spec-challenger (Opus): `has_gaps`, 2 blockers, 5 majors, 8 minors. Audit
  `260929_sidecar-verify-2060_spec_challenge`.
- spec-defender (Opus): `needs_revision`. Conceded M2, m4-m8. Partial on B1, B2, M3, M4, m2.
  Rebutted M1, M5 (wording only), m3. Audit `260929_sidecar-verify-2060_spec_defense`.
- Orchestrator re-verified every load-bearing citation before accepting:
  - `myxcel/provenance.py:93,119` (sha and dirty captured separately);
  - `:449-452` (drift check on `stored.git_sha`);
  - `rsync.py:398` (additive push);
  - bathos `mcp.py:3463-3466`, `blast_radius.py:538`;
  - `channels.py:233-239`.
- Changes adopted: `matches_commit` with the positive-evidence `dirty` rule; cwd coverage;
  `extra_excludes` + `safe.directory` + git-nonzero means fail; budget with no cache; wording
  "the sidecar's directory"; warning hygiene; release order; UTF-8/sha/fresh-sentinel details;
  stale-file risk; tests 12-19. `matches_commit` excludes deliberately unpushed tracked files
  (orchestrator refinement).
- Rejected with reasons: renaming `code_verified` (user-mandated name); null `git_sha` in v2
  (breaks myxcel drift check); a stat-keyed cache (breaks the hard rule); a default recursive
  `"."` scan (false fails on ungitignored outputs).
