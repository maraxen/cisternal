---
title: 'Shadow ruling UI: session-handed ruling page with offline sheet fallback'
description: Design for owner rulings on cisternal shadow records via a claude.ai page handed out at session close-out, with an offline HTML sheet fallback; remote-robust.
status: draft
task_id: 261124_shadow-ruling-ui
date: '261124'
backlog_ids: ''
adversarial_review: ''
---
# Shadow ruling UI: session-handed ruling page with offline sheet fallback

## 1. Intent

Shadow-mode features (detectors and gates that log predictions until owner labels show they can be
trusted) only advance when the owner rules on their records. Today owner rulings come from one shell
command per item on the machine that holds the store, so they are rarely made: in maraxiom's prose
rubric store, 91 of 232 rulings (39%) are agent-relayed rows that count for nothing (measured
261124 from `~/.local/share/maraxiom/rubric_review/rulings.jsonl`). The owner mostly rules **at the
end of a session**, sometimes **from a phone**, and sessions run on the laptop, on Engaging, on
titanix or in the cloud.

Goal: at session close-out the agent hands the owner one page of open items; the owner rules on it
from any device; the rulings land as owner labels in the right store, whichever machine the session
or the store is on.

## 2. Goals, non-goals, anti-goals

Goals
- G1. One ruling flow shared by every shadow feature, owned by cisternal; projects plug in adapters.
- G2. Works when the agent runs on a remote with no browser; the owner needs only a phone or laptop.
- G3. A ruling enters a store as `owner_confirmed` only through one checked import path.
- G4. Probes (unflagged, randomly sampled items) are first in line, since they are the only recall evidence.
- G5. Offline fallback (B) built from the same packet and importer.

Non-goals (MVP)
- An always-on inbox aggregating every machine's records (approach C, rejected).
- Syncing shadow record stores between machines.
- Changing promotion thresholds, ladders or the scorer.
- Adapters for bathos Bearings and praxia d3f shadow (later; the packet format must not preclude them).

Anti-goals (failure even if it works)
- An agent can mint owner labels more easily than today. The guard must be at least as strong as
  maraxiom's hitl hook on `mrx prose rule`.
- The page shows the agent's or the relayed verdict before the owner answers (anchoring; the rubric
  spec forbids copying relayed verdicts).
- A label lands against verdicts on a different machine than the one that produced them, silently.

## 3. Constraints and verified assumptions

| # | Assumption | Status |
|---|---|---|
| A1 | `cisternal.shadow.emit_label(feature, subject_key, label, *, label_source, labeller, **extra_fields)` accepts extra fields, so a label can carry evidence | verified, `src/cisternal/shadow/events.py:96-129` |
| A2 | The scorer reads a separate labels JSONL (`--labels-file`) and filters by `allowed_label_sources` | verified, `src/cisternal/shadow/cli.py:45`, `scoring.py:305-413` |
| A3 | A claude.ai Artifact page with `db` + `user` stores documents server-side and knows the viewer's opaque id; agents read it via the `ArtifactData` tool (`list` with `out_dir` saves documents as JSON files) | verified, artifact-capabilities contract 0.2.47 (`db.d.ts`, `user.d.ts`) and the ArtifactData tool schema |
| A4 | The page store does **not** record whether a write came from the viewer in the page or from Claude via `ArtifactData`; `ArtifactData` writes "as the user", including into `data/users/me` | verified (documented behaviour); so attestation cannot come from the store |
| A5 | Every `ArtifactData` write names its `collection` (top level or per `writes[]` entry), so a PreToolUse hook can match on it | verified from schema; **hook firing on ArtifactData unverified** (spike S1) |
| A6 | Artifact/ArtifactData tools are available to a Claude Code session running on Engaging or titanix under the owner's claude.ai login | **unverified** (spike S2) |
| A7 | An artifact is scoped to one claude.ai organization; a session signed in to another org cannot read it | observed 261124 (watch on the parity deck ended for this reason) |
| A8 | `!`-prefixed commands typed from the phone (Remote Control) run in the session | **unverified** (spike S3); B does not depend on it |
| A9 | maraxiom's prose rubric uses its own ruling store with multi-tag verdicts (`tag: clear|mild`, empty map = fine), not binary cisternal labels | verified, rubric spec `maraxiom/.praxia/docs/superpowers/specs/261117_rubric-review-loop-design.md:115-140` |
| A11 | Every document `ArtifactData` reads carries a `version` (also returned by every write) | verified, ArtifactData tool schema (`if_version` description) |
| A12 | `emit_label` returns "enqueued, not written"; a write is confirmed only by draining and reading back (maraxiom's `mrx shadow label` already does drain + read-back) | verified, `events.py:113-118`, `maraxiom/src/maraxiom/shadow_cli.py:212-226` |
| A13 | maraxiom can write a rubric ruling (verdicts + `owner_rewrite`) from Python via `make_ruling` / `RulingStore.append` without the `mrx prose rule` CLI | verified, `maraxiom/src/maraxiom/rubric_review/core/rule.py:63-131`, `core/store.py:286`; but the rubric spec reserves `owner_confirmed` for the owner's plain shell line (owner decision, §8) |
| A10 | maraxiom fig_* shadow features label binary present/absent via cisternal; `mrx shadow label-sheet` already builds an offline HTML sheet returning `labels.json`; `label-batch` requires `--confirm-owner` | verified, `maraxiom/src/maraxiom/shadow_cli.py:190-370` |

## 4. Approaches

- **A. Session-handed ruling page (chosen).** The agent publishes a private claude.ai page from a
  packet at close-out; the owner rules on it from any device; a later session imports. Fits
  end-of-session and phone use; no machine sync. Costs: attestation is procedural (hook), the page is
  org-scoped, rulings land only when a session imports.
- **B. Offline sheet (chosen as fallback).** The same packet rendered as a self-contained HTML file,
  sent to the owner (SendUserFile or a path); answers download as a labels file the owner imports with
  an owner-run `!` command. No hosted dependency; returning the file from a phone to a remote session is
  clumsy.
- **C. Always-on inbox (rejected).** A titanix web app with sync of all stores: a server, auth and
  five-store sync, suited to a weekly sweep rather than close-out.

The owner chose A with B as fallback for the MVP (261124).

## 5. Design

### 5.1 The packet (cisternal, project-neutral)

`cisternal shadow packet` writes `ruling_packet.json`, built from adapter output:

```json
{
  "packet_v": 1,
  "packet_id": "pkt_<16 hex>",
  "created_at": "...",
  "origin": {"host": "<hostname>", "store_kind": "cisternal_records|maraxiom_rubric",
             "store_path": "<resolved abs path>", "session_id": "...", "task_id": "..."},
  "items": [
    {"item_id": "<feature>|<subject_key>",
     "feature": "...", "subject_key": "...", "is_probe": true,
     "inputs_sha256": "...",
     "answer": {"kind": "binary", "positive": "present", "negative": "absent"}
              | {"kind": "tags", "tags": ["claudish", "..."], "severities": ["clear","mild"], "allow_rewrite": true},
     "show": {"text": "...", "context": "...", "surface": "slide_text", "image_svg": "<sanitized svg or null>"},
     "adapter": "maraxiom.prose|maraxiom.fig"}
  ]
}
```

- Order: probes first, then findings, each in the adapter's order. A cap (default 40) per packet.
- `image_svg` (fig adapter): the adapter embeds the verdict's rendered SVG after an allowlist
  sanitize (no script, no foreignObject, no external hrefs); per item at most 300 KB, packet total at
  most 8 MB (under the 16 MB page cap). An oversize item is left out of the page packet and listed as
  "sheet only" (path B) (designer's call).
- `show` never contains the agent's verdict, judge hints or any relayed answer (anti-goal).
- Adapters are entry points (`cisternal.ruling_adapters`) exposing `open_items(store, limit)` and
  `import_rulings(rulings, origin) -> report`. MVP adapters live in maraxiom: `maraxiom.prose`
  (rubric units, grouped by `unit_key` so one unit is one item) and `maraxiom.fig` (fig_* verdicts).

### 5.2 Path A: the ruling page

- The agent publishes a private Artifact from a cisternal-provided HTML template plus the packet,
  capabilities `{db: {rules: ...}, user: {}}`. One item per screen, phone-first: the text or figure,
  the answer controls (two buttons for binary; tag chips each with clear/mild plus "Fine" for tags),
  optional rewrite box, "Skip", and a progress count. Desktop shows the same with keyboard shortcuts.
- Each answer is written by the page to `cisternal_rulings/<item_id>` with `{item_id, packet_id, answer,
  rewrite?, viewer_id: user.id(), ruled_at}`. Re-answering overwrites (latest wins); the page shows
  ruled items as done.
- db rules: `cisternal_rulings` writable at `admin` (the owner's level); `packet` read-only.
- The packet is embedded in the page (it is the page's content); no seed rows.

### 5.3 Attestation guard

Because the page store cannot tell the owner from the agent (A4), the guard is procedural, matching
the strength of maraxiom's hitl hook:
- The ruling collection has a reserved name, `cisternal_rulings`. A PreToolUse hook (cisternal
  plugin) denies any `ArtifactData` write (`set`, `update`, `str_replace`, `delete`, or a `batch`
  with any entry) whose collection starts with `cisternal_rulings`, on **any** artifact. No registry
  of ruling pages is needed, so the hook works the same on every machine (designer's call; replaces a
  local URL registry that would not travel).
- `viewer_id` is recorded for audit only. It is **not** attestation: an agent writing through
  `ArtifactData` writes as the user and could set it (A4). There is no `meta/owner` bootstrap doc.
- **Owner decision (261124):** page rulings guarded by this hook count as owner labels
  (`owner_confirmed`), the same trust as today's hitl-guarded shell line. If spike S1 shows the hook
  does not fire on `ArtifactData`, building stops and the guard is redesigned with the owner; there is
  no hook-less MVP.
- Known limit (stated, as in the rubric spec): this is not a hard boundary; an agent that bypasses
  the hook or edits the downloaded JSON could forge rows. Import records evidence so forged rows are
  auditable.

### 5.4 Import

`cisternal shadow import-labels <dir|labels.json> --packet ruling_packet.json`:
- In path A the agent first runs `ArtifactData list` on `cisternal_rulings` with `out_dir`, then the importer.
- Refuses when the current host/store does not match `packet.origin` (prevents labels landing beside
  the wrong verdicts), unless `--labels-out <file>` writes a standalone labels file instead.
- Refuses an item whose `inputs_sha256` no longer matches the current verdict (the subject changed).
- Writes through the adapter: binary items via `emit_label(..., label_source="owner_confirmed",
  labeller=<viewer_id>, ruling_page=<url>, ruling_doc_version=<n>, packet_id=...)`; tag items via
  maraxiom's `make_ruling` + `RulingStore.append` (A13) as `owner_confirmed` with `owner_rewrite`
  when given, plus the same evidence fields.
- **Owner decision (261124):** page rulings count as `owner_confirmed` for the prose rubric too. This
  amends the rubric spec (`261117_rubric-review-loop-design.md`, Ruling `source`): `owner_confirmed`
  may come from the owner's plain shell line **or** a hook-guarded ruling page import, with the page
  URL, document version and packet id stored on the ruling. Part of the work: amend that spec, add a
  maraxiom entry point for the adapter, and keep the hitl guard on the CLI unchanged.
- Path A import may be run by the agent (the attestation is the page + guard); path B import of
  owner_confirmed requires `--confirm-owner`, typed by the owner as a `!` line (same as `label-batch`).
- Idempotent: an item already imported from the same document `version` (A11) is skipped; a newer
  version supersedes per the store's own rules.
- "Imported" means read back from the store after a drain (A12), not enqueued; an item enqueued but
  not found on read-back is reported as `not_written` and the command exits non-zero.
- Prints a report: imported, skipped, refused (with reason), not_written, still open.

### 5.5 Path B: the offline sheet

`cisternal shadow sheet --packet ruling_packet.json` renders the same template without capabilities:
answers kept in the page, a "Download labels.json" button; no OS-specific paths (drop the
`/mnt/c/Users/*/Downloads` guess; print where to put the file). The owner imports with
`! cisternal shadow import-labels labels.json --packet ... --confirm-owner`.

### 5.6 Close-out integration

The praxia `handoff` skill, Phase 1 row 10 (plugin checks), gets a cisternal `closing-session` skill:
"open shadow items touched this session → build packet → publish ruling page → give the owner the link;
at next pickup, import." The handoff record lists the ruling page URL under `open_questions` until
imported.

### 5.7 Remote behaviour

- Records never move. The packet records its origin; import runs in a session on that machine (or
  writes a standalone labels file with `--labels-out`).
- The page lives on claude.ai, so the owner's device never needs to reach the remote.
- Org scoping: the page is published under the session's login; a different-org session asked to
  import says "sign in to <org> with /login" instead of failing silently.

### 5.8 Also fixes

- maraxiom debt #3610 (`mrx shadow label --source owner_confirmed` without confirmation): route
  through the shared check.
- maraxiom debt #3607 (relayed rows pile up): the prose adapter replaces the per-unit shell ritual.
- maraxiom debt #3608 (bulleted body as one unit): the adapter groups by unit today; splitting units
  is the walker's fix, independent.

## 6. Spikes before building (throwaway)

- S1. Install a PreToolUse hook matching `ArtifactData`; confirm it fires and can deny a `set` to
  `rulings/x` on a scratch artifact, and allows other collections.
- S2. From a Claude Code session on titanix (and one on an Engaging login node), call
  `Artifact list` and `ArtifactData list` on a scratch page.
- S3. Owner test: from the phone via Remote Control, type a harmless `! echo` and confirm it runs in
  the session (decides whether B is phone-usable).

Outcomes (261124):
- **S1 PASSED.** Interactive Claude Code session started with `--settings` carrying a PreToolUse hook
  (matcher `ArtifactData`): `set` to `cisternal_rulings/x` denied, `batch` with a
  `cisternal_rulings` entry denied, `set` to `other/x` committed, `list cisternal_rulings` empty. The
  hook received the full `tool_input` (including `writes[]`) for all four calls
  (`~/scratch/s1_261124/hook_seen.jsonl`). Deny shape: `hookSpecificOutput.permissionDecision = "deny"`.
- **Headless sessions have no page tools.** `claude -p` reported "ArtifactData is disabled for this
  session", so ruling-page publish and import need an interactive session; batch jobs only produce
  records (and can build a packet), never publish or import.
- S2 (remote hosts) and S3 (phone `!`): pending, non-blocking.

S1 is a gate: if it fails, building stops and the guard is redesigned with the owner (owner decision
261124). S2 failing limits path A to sessions where the tools exist (the packet can still be carried
to such a session); S3 failing makes B laptop-only.

## 7. Left to the builder

Template styling, exact db rule syntax, adapter entry-point plumbing, report formatting, test layout
(fixtures for both answer kinds; an isolation test that import cannot write `owner_confirmed` without
the page path or `--confirm-owner`).

## 8. Decisions

Owner (261124): approach A with B fallback; hook guard counts as owner attestation, S1 gates the
build; page rulings are `owner_confirmed` for the prose rubric too (rubric spec amended).

Calls made by the designer (owner to check):
- Reserved collection name `cisternal_rulings` instead of a per-machine registry of ruling pages.
- `viewer_id` is audit only, not attestation.
- SVG items: sanitized, at most 300 KB each and 8 MB per packet; oversize items go to the sheet.
- "Imported" means read back after a drain.

- MVP adapters: maraxiom prose rubric and maraxiom fig_* only; bathos Bearings and praxia d3f later.
- Packet cap 40 items, probes first.
- Import refuses host/store mismatch by default.
- Agent may run path A import; path B needs owner `--confirm-owner`.
- Close-out hook via a cisternal `closing-session` skill.
