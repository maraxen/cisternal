---
name: closing-session
description: "Use at session close-out when shadow items were touched: build a ruling packet, publish the owner's ruling page, and record its URL in the handoff. At pickup, import the rulings. Not for scoring or gate checks (use developing-in-shadow)."
covers_families: []
distinctive_strings:
  - "closing-session"
  - "cisternal shadow packet"
  - "cisternal shadow page"
  - "cisternal shadow import-labels"
  - "cisternal_rulings"
---

# closing-session

Hands the owner a ruling page for shadow items this session touched, so the owner can rule on them from any device at close-out. Rulings come back at the next pickup and are imported into the shadow records.

## When to Use

Use at session close-out (the handoff step, see praxia `handoff`) when this session ran or touched a shadow adapter, or when a pickup has ruling-page URLs waiting in the handoff's `open_questions`. For running and scoring shadow features themselves, use `developing-in-shadow`.

## Close-out steps

1. **Build a packet per adapter the session touched.** Run once per adapter:

   ```bash
   cisternal shadow packet --adapter NAME --store PATH [--limit 40] [--out ruling_packet.json] --session-id S --task-id T
   ```

   Adapters:
   - `maraxiom.prose`: `--store` is the maraxiom rubric store root.
   - `maraxiom.fig`: `--store` is the cisternal records dir.
   - `cisternal.records`: import only, not a packet source.

   The output is JSON `{packet, items, probes, sheet_only}`. If it is `{"packet": null, "message": "nothing to rule"}`, the adapter has no open items: skip the rest for that adapter.

2. **If there are items, build and publish the page.**
   - `cisternal shadow page --packet P --out page.html`
   - Publish `page.html` as a **private** Artifact with exactly these capabilities:
     `{"db": {"rules": [{"path": "cisternal_rulings", "write": "admin"}]}, "user": {}}`
   - Give the owner the link.
   - Record the page URL in the handoff `open_questions` until the rulings are imported.

3. **Never show the owner a verdict.** Do not show the owner the agent's or the judge's verdict on any item. The owner rules blind.

4. **Never write to `cisternal_rulings`.** A hook denies writes to it. The page is the only writer.

## Pickup: import the rulings

Run at the next pickup in an **interactive** Claude Code session. Publish and import need page tools, which are disabled in headless `claude -p`. Cluster and batch jobs can produce records and packets only.

1. Pull the owner's rulings:
   `ArtifactData list` on collection `cisternal_rulings` with `out_dir=<dir>`.
2. Import them, on the machine whose records the packet came from:
   `cisternal shadow import-labels <dir> --packet ruling_packet.json --page-url <artifact url>`
3. Relay the report to the owner: imported, skipped, refused (with reasons), not_written, still_open.
   Exit 1 means something was refused or not written. Say so; do not treat it as success.
4. Once imported, remove the page URL from the handoff `open_questions`.

**Import refuses `origin_mismatch`** when run on a machine other than the packet's origin host and store. Records never move. Either run the import on the origin machine, or write a standalone labels file with `--labels-out FILE` and carry that file to the origin.

## Different organization

If `ArtifactData` cannot find the page, it belongs to another claude.ai organization. Do not retry or work around it. Tell the owner: "This page belongs to another claude.ai organization. Sign in to that organization with `/login`, then run the pickup again."

## Offline fallback

When the owner cannot open a page, send the sheet instead:

- `cisternal shadow sheet --packet P --out sheet.html`, and send `sheet.html` to the owner.
- The owner imports the returned labels with their own line:
  `! cisternal shadow import-labels labels.json --packet ruling_packet.json --confirm-owner`

The agent never runs `--confirm-owner` itself. Only the owner's own line confirms owner rulings.
