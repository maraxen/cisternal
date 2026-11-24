---
title: Shadow ruling UI implementation plan
description: 'Task plan for the shadow ruling page + offline sheet: S1 hook gate, ruling packet, page/sheet renderer, ArtifactData guard, import-labels, maraxiom adapters, close-out skill.'
status: draft
task_id: 261124_shadow-ruling-ui
date: '261124'
sprint: ''
backlog_ids: ''
---
# Shadow ruling UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner rules on open shadow items from a claude.ai page (or an offline sheet) handed out at session close-out, and the rulings land as `owner_confirmed` labels in the right store on any machine.

**Architecture:** cisternal owns a project-neutral ruling packet, a page/sheet renderer, a PreToolUse guard on `ArtifactData` writes to `cisternal_rulings*`, and `import-labels`; projects plug in adapters through the `cisternal.ruling_adapters` entry-point group. Binary items import through `cisternal.shadow.emit_label`; maraxiom's prose adapter imports tag rulings through its own ruling store.

**Tech Stack:** Python 3.12, cyclopts, pytest, uv; claude.ai Artifact runtime contract 0.2.47 (`db`, `user`); Claude Code PreToolUse hooks.

**Spec:** `.praxia/docs/specs/261124_shadow-ruling-ui.md` (branch `spec/shadow-ruling-ui`).

## Global Constraints

- Task 0 (spike S1) is a gate: if the PreToolUse hook does not fire on `ArtifactData` and deny a write, STOP; do not start Task 1 (owner decision 261124).
- Reserved collection name: `cisternal_rulings`. Packet version `packet_v: 1`. Packet id `pkt_<16 hex>`.
- Packet cap default 40 items; probes first, then findings.
- `image_svg`: sanitized (no `<script>`, no `foreignObject`, no external `href`/`xlink:href`), ≤ 300 KB per item, ≤ 8 MB per packet; oversize items are left out of the page and listed as `sheet_only`.
- `show` never carries a verdict, judge hint or relayed answer.
- `owner_confirmed` from path B requires `--confirm-owner`; path A import carries `ruling_page`, `ruling_doc_version`, `packet_id` evidence on every label.
- "Imported" = read back from the store after a drain; otherwise `not_written` and a non-zero exit.
- Import refuses when current host/store ≠ `packet.origin` unless `--labels-out <file>`.
- No OS-specific paths in output (no `/mnt/c/Users/*/Downloads` guess).
- Never run the full test suite locally; run single files (`uv run pytest tests/shadow/test_x.py`).

## Review Focus

1. A packet built on Engaging imported in a laptop session: refuse with the origin named (Task 5 test `test_import_refuses_origin_mismatch`).
2. The owner re-answers an item after it was imported: the newer document version supersedes, the same version is skipped (Task 5 `test_import_version_idempotent_and_supersedes`).
3. A collaborator with edit access opens the page: answer controls show only for `user.isOwner()` (Task 3 `test_page_controls_gated_on_is_owner`).
4. Quote or context text containing `</script>` or HTML: rendered as text, packet JSON escapes `<` as `<` (Task 3 `test_render_escapes_markup`).
5. Nothing open: `shadow packet` exits 0 with `nothing to rule`, writes no packet (Task 2 `test_packet_cli_nothing_open`).

---

### Task 0: Spike gate (S1, S2, S3) — throwaway

**Files:** scratch only (`$TMPDIR/s1/`); results recorded in the spec §6.

- [ ] **Step 1 (S1):** Add a temporary project hook in a scratch dir's `.claude/settings.local.json`: PreToolUse, matcher `ArtifactData`, command `python3 $TMPDIR/s1/deny.py`, where `deny.py` prints `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"s1"}}` when `tool_input.collection` (or any `tool_input.writes[].collection`) starts with `cisternal_rulings`, else exits 0.
- [ ] **Step 2:** Publish a scratch Artifact declaring `{db:{}}`. From a session in that dir: `ArtifactData set` to `cisternal_rulings/x` → expect denied with reason `s1`; `set` to `other/x` → expect written; `batch` with one `cisternal_rulings` entry → denied.
- [ ] **Step 3 (S2):** From a Claude Code session on titanix and on an Engaging login node: `Artifact list` and `ArtifactData list` on the scratch page. Record works/fails per host.
- [ ] **Step 4 (S3, owner):** Owner types `! echo s3` from the phone (Remote Control). Record whether it ran.
- [ ] **Step 5:** Write the three outcomes into spec §6 with dates; delete the scratch artifact (ask first). If S1 failed: STOP and report.
- [ ] **Step 6: Commit** `git add .praxia/docs/specs/261124_shadow-ruling-ui.md && git commit -m "spec: record S1-S3 spike outcomes"`

### Task 1: Ruling packet model and adapter protocol

**Files:**
- Create: `src/cisternal/shadow/ruling/__init__.py`, `src/cisternal/shadow/ruling/packet.py`, `src/cisternal/shadow/ruling/adapters.py`, `src/cisternal/shadow/ruling/svg.py`
- Modify: `pyproject.toml` (entry-point group `cisternal.ruling_adapters`, built-in `cisternal.records = "cisternal.shadow.ruling.records_adapter:RecordsAdapter"` added in Task 5)
- Test: `tests/shadow/test_ruling_packet.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Origin(host: str, store_kind: str, store_path: str, session_id: str, task_id: str)`
  - `@dataclass(frozen=True) RulingItem(item_id: str, feature: str, subject_key: str, is_probe: bool, inputs_sha256: str, answer: dict, show: dict, adapter: str)`; `item_id == f"{feature}|{subject_key}"`
  - `@dataclass RulingPacket(packet_id: str, created_at: str, origin: Origin, items: list[RulingItem], sheet_only: list[str], packet_v: int = 1)`; `to_json() -> str`; `load_packet(path: Path) -> RulingPacket` (raises `PacketError` on unknown `packet_v`)
  - `build_packet(items: list[RulingItem], origin: Origin, cap: int = 40) -> RulingPacket` (orders probes first, stable within kind, applies cap and SVG budget)
  - `sanitize_svg(svg: str) -> str` (raises `SvgRejected` when unsafe content cannot be stripped)
  - `class RulingAdapter(Protocol)`: `name: str`; `open_items(store: Path, limit: int) -> list[RulingItem]`; `import_rulings(rulings: list[OwnerRuling], packet: RulingPacket) -> ImportReport`
  - `@dataclass OwnerRuling(item_id: str, answer: dict, rewrite: str | None, viewer_id: str | None, ruled_at: str, doc_version: int | None, source_path: str)`
  - `@dataclass ImportReport(imported: list[str], skipped: list[str], refused: dict[str, str], not_written: list[str], still_open: list[str])`
  - `load_adapter(name: str) -> RulingAdapter` (entry points; `KeyError` with known names on miss)

- [ ] **Step 1: Write failing tests** in `tests/shadow/test_ruling_packet.py`:
  - `test_build_packet_orders_probes_first_and_caps`: 45 items (5 probes last in input) → `len(items)==40`, first 5 are probes.
  - `test_show_rejects_verdict_keys`: `RulingItem` whose `show` has any of `verdict`, `tag`, `severity`, `hint`, `relayed` → `build_packet` raises `PacketError`.
  - `test_svg_sanitize_strips_script_and_external_href`: output contains no `<script`, no `foreignObject`, no `href="http`.
  - `test_svg_budget_moves_oversize_to_sheet_only`: item with 301 KB svg → not in `items`, `item_id in sheet_only`; total over 8 MB trims from the end into `sheet_only`.
  - `test_packet_roundtrip_and_unknown_version`: `load_packet(to_json())` equals original; `packet_v: 2` raises `PacketError`.
- [ ] **Step 2:** `uv run pytest tests/shadow/test_ruling_packet.py -q` → FAIL (import error).
- [ ] **Step 3:** Implement the interfaces above; SVG sanitize with `xml.etree.ElementTree` allowlist walk (drop disallowed elements/attributes; reject on parse error).
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat(shadow): ruling packet model and adapter protocol`

### Task 2: `cisternal shadow packet`

**Files:** Modify `src/cisternal/shadow/cli.py`; Test `tests/shadow/test_ruling_cli.py`

**Interfaces:**
- Consumes: `load_adapter`, `build_packet`, `Origin` (Task 1).
- Produces: CLI `cisternal shadow packet --adapter NAME --store PATH [--limit 40] [--out ruling_packet.json] --session-id S --task-id T`; prints one JSON object `{"packet": path, "items": n, "probes": k, "sheet_only": m}`; exit 0 with `{"packet": null, "message": "nothing to rule"}` and no file when no items; exit 2 on unknown adapter.

- [ ] **Step 1: Failing tests:** `test_packet_cli_writes_packet` (fake adapter registered via monkeypatched entry points returns 3 items → file exists, stdout JSON `items==3`, `origin.host == socket.gethostname()`, `origin.store_path` is resolved absolute); `test_packet_cli_nothing_open` (0 items → exit 0, no file, message `nothing to rule`); `test_packet_cli_unknown_adapter` (exit 2).
- [ ] **Step 2:** run → FAIL. **Step 3:** implement `shadow_packet` command. **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat(shadow): packet command`

### Task 3: Page and sheet renderer (paths A and B)

**Files:** Create `src/cisternal/shadow/ruling/template.html`, `src/cisternal/shadow/ruling/render.py`; Modify `src/cisternal/shadow/cli.py` (`shadow sheet`, `shadow page`); Test `tests/shadow/test_ruling_render.py`

**Interfaces:**
- Consumes: `RulingPacket` (Task 1).
- Produces: `render(packet: RulingPacket, mode: Literal["page", "sheet"]) -> str`; CLI `cisternal shadow page --packet P --out page.html` (agent then publishes it with capabilities `{"db": {"rules": [{"path": "cisternal_rulings", "write": "admin"}]}, "user": {}}`) and `cisternal shadow sheet --packet P --out sheet.html`.
- Page writes each answer to `cisternal_rulings/<item_id with "|" replaced by "~">` with fields `item_id, packet_id, answer, rewrite, viewer_id, ruled_at`. Sheet keeps answers in memory and offers "Download labels.json" as `{"packet_id": ..., "rulings": [OwnerRuling-shaped dicts]}`.

- [ ] **Step 1: Failing tests** (string assertions on rendered HTML):
  - `test_render_escapes_markup`: item text `</script><b>x` → no raw `</script><b>` in output; embedded packet JSON contains `<`.
  - `test_page_mode_uses_db_and_reserved_collection`: page output contains `claude.use("db")`, `claude.use("user")` and `cisternal_rulings`.
  - `test_page_controls_gated_on_is_owner`: page script hides answer controls unless `isOwner()` resolves true (assert the `isOwner()` call guards the controls' render function).
  - `test_sheet_mode_has_no_capabilities_and_no_os_paths`: sheet output contains no `claude.use`, no `/mnt/c`, no `Downloads`; contains `labels.json`.
  - `test_binary_and_tags_controls`: binary item renders its `positive`/`negative` labels; tags item renders each tag with `clear`/`mild` and a `Fine` control, rewrite box iff `allow_rewrite`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement; one item per screen, phone-first; values set via `textContent`; sheet_only items listed but not rulable on the page. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat(shadow): ruling page and offline sheet renderer`

### Task 4: `ArtifactData` guard hook

**Files:** Create `src/cisternal/usage/ruling_guard.py`; Modify `src/cisternal/usage/cli_hook.py` (dispatch `ArtifactData` in `pre-tool-use`), `src/cisternal/agent_plugin.json` (add PreToolUse matcher `ArtifactData` → `cisternal-hook pre-tool-use`); Test `tests/test_ruling_guard.py`

**Interfaces:**
- Produces: `ruling_write_denial(tool_name: str, tool_input: dict) -> str | None` (reason string when denied). The hook prints the PreToolUse deny JSON proven in Task 0 when it returns a reason.

- [ ] **Step 1: Failing tests:** deny for `set`/`update`/`str_replace`/`delete` with `collection="cisternal_rulings"` and `"cisternal_rulings/sub"`; deny `batch` when any `writes[].collection` starts with `cisternal_rulings`; allow `get`/`list`/`query`/`profiles` on it; allow writes to `other`; allow non-`ArtifactData` tools; `test_hook_cli_emits_deny_json` runs `main(["pre-tool-use"])` with a stdin payload and asserts `permissionDecision == "deny"`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS; also `uv run pytest tests/test_usage_paths.py -q` still passes (hook wiring).
- [ ] **Step 5:** Re-run the Task 0 S1 live check against the real hook via the installed plugin (`cisternal assets export` + plugin update per the run-cisternal skill); record pass in spec §6.
- [ ] **Step 6: Commit** `feat(usage): guard ArtifactData writes to cisternal_rulings`

### Task 5: `cisternal shadow import-labels` and the built-in records adapter

**Files:** Create `src/cisternal/shadow/ruling/importer.py`, `src/cisternal/shadow/ruling/records_adapter.py`; Modify `src/cisternal/shadow/cli.py`, `pyproject.toml` (entry point `cisternal.records`); Test `tests/shadow/test_ruling_import.py`

**Interfaces:**
- Consumes: `load_packet`, `load_adapter`, `OwnerRuling`, `ImportReport` (Task 1); `emit_label` (`events.py:96`).
- Produces:
  - `read_rulings(source: Path) -> tuple[list[OwnerRuling], Literal["page", "sheet"]]`: a directory in ArtifactData `out_dir` layout (`<dir>/cisternal_rulings/*.json`, each carrying `version`) → `"page"`; a `labels.json` file → `"sheet"`.
  - `import_labels(source: Path, packet: RulingPacket, *, confirm_owner: bool, labels_out: Path | None, records_dir: Path | None) -> ImportReport`
  - CLI `cisternal shadow import-labels SOURCE --packet P [--confirm-owner] [--labels-out F] [--records-dir D]`; exit 0 all imported/skipped; 1 any `refused`/`not_written`; 2 usage (incl. sheet without `--confirm-owner`).
  - `RecordsAdapter` (name `cisternal.records`): `import_rulings` calls `emit_label(feature, subject_key, answer["value"] == positive, label_source="owner_confirmed", labeller=viewer_id or "owner", ruling_page=..., ruling_doc_version=..., packet_id=...)`, drains, reads back by `(feature, subject_key, label_source, packet_id)`.
- [ ] **Step 1: Failing tests:**
  - `test_import_refuses_origin_mismatch` (packet origin host `engaging-login` → every item `refused["origin_mismatch"]`, exit 1); with `labels_out` → writes a labels JSONL, no refusal.
  - `test_import_refuses_changed_subject` (current verdict `inputs_sha256` differs → `refused["subject_changed"]`).
  - `test_import_version_idempotent_and_supersedes` (same `doc_version` twice → second `skipped`; higher version → imported).
  - `test_sheet_import_requires_confirm_owner` (exit 2 without flag; `--dry-run` style not needed).
  - `test_import_reads_back` (records dir via `explicit_dirs`-style fixture from `tests/shadow/harness.py`; a label enqueued but filtered out of the store → `not_written`, exit 1).
  - `test_page_import_carries_evidence` (written label fields include `ruling_page`, `ruling_doc_version`, `packet_id`, `label_source == "owner_confirmed"`).
- [ ] **Step 2:** FAIL. **Step 3:** implement; current host = `socket.gethostname()`, store match = resolved path equality. **Step 4:** PASS, plus `uv run pytest tests/shadow/test_score.py -q` (scorer sees the new labels as `owner_confirmed`).
- [ ] **Step 5: Commit** `feat(shadow): import-labels with origin, version and read-back checks`

### Task 6: maraxiom adapters and rubric spec amendment (maraxiom repo, own branch)

**Files (maraxiom):** Create `src/maraxiom/ruling_adapters/__init__.py`, `fig.py`, `prose.py`; Modify `pyproject.toml` (entry points `maraxiom.fig`, `maraxiom.prose` in group `cisternal.ruling_adapters`), `src/maraxiom/shadow_cli.py:190-226` (owner_confirmed via `mrx shadow label` requires `--confirm-owner`, debt #3610), `.praxia/docs/superpowers/specs/261117_rubric-review-loop-design.md` (Ruling `source` amendment); Test `tests/test_ruling_adapters.py`, `tests/test_shadow_label_confirm.py`

**Interfaces:**
- Consumes: `RulingAdapter`, `RulingItem`, `OwnerRuling`, `ImportReport` (cisternal Task 1); maraxiom `make_ruling` (`rubric_review/core/rule.py:63`), `RulingStore.append` (`core/store.py:286`), `shadow_labels` subject keys (`shadow_labels.py:139-160`).
- Produces: `FigAdapter.open_items` → binary items for fig_* verdicts with no owner label (`answer={"kind":"binary","positive":"present","negative":"absent"}`, `show.image_svg` from the verdict's asset); import delegates to `cisternal.records`. `ProseAdapter.open_items` → one item per open `unit_key` of the latest run per deck (all its finding ids in `show.context` as audit, never tags), probes first, `answer={"kind":"tags","tags": <rubric tags>, "severities":["clear","mild"], "allow_rewrite": true}`; `import_rulings` writes `owner_confirmed` rulings with `owner_rewrite` and evidence fields, rejects a unit that already has an `owner_confirmed` ruling (`refused["already_ruled"]`).
- [ ] **Step 1: Failing tests:** prose open_items groups f3+f4-style findings of one unit into one item; prose import writes `source == "owner_confirmed"` with `owner_rewrite` and `ruling_page`; second import on the same unit → `already_ruled`; fig open_items skips subjects already owner-labelled; `mrx shadow label --source owner_confirmed` without `--confirm-owner` exits 2.
- [ ] **Step 2:** FAIL. **Step 3:** implement; amend the rubric spec's Ruling `source` paragraph: `owner_confirmed` comes from the owner's plain shell line or a hook-guarded ruling-page import carrying page URL, document version and packet id. **Step 4:** PASS (single files only).
- [ ] **Step 5: Commit** (maraxiom branch) `feat(review): cisternal ruling adapters; owner_confirmed via ruling page`

### Task 7: Close-out skill and end-to-end check

**Files:** Create `.praxia/skills/closing-session/SKILL.md` (cisternal); Modify `.praxia/manifest.toml` if skills are listed there; Test: manual end-to-end below.

**Interfaces:** Consumes the CLIs from Tasks 2-5.

- [ ] **Step 1:** Write the skill. Description starts "Use at session close-out". Body: run `cisternal shadow packet` per adapter the session touched; if items: `shadow page`, publish privately with the db+user capabilities from Task 3, give the owner the link, put the URL in the handoff `open_questions`; at pickup: `ArtifactData list` on `cisternal_rulings` with `out_dir`, then `cisternal shadow import-labels <out_dir> --packet ...`, relay the report; if `ArtifactData` cannot find the page, say the page belongs to another claude.ai organization and to sign in to it with `/login` (spec §5.7); offline: `shadow sheet` + owner's `! cisternal shadow import-labels labels.json --packet ... --confirm-owner`.
- [ ] **Step 2:** `cisternal assets validate` passes.
- [ ] **Step 3: End to end:** on the parity-lightning prose run (`run_722cac44a74f9880`), build a packet (expect 40 items, 21 probes first), publish the page, owner rules 3 items on the phone, import, then `mrx prose rulings --deck parity-lightning` shows 3 `owner_confirmed` rows with `ruling_page` set.
- [ ] **Step 4: Commit** `feat(skills): cisternal closing-session ruling hand-out`
