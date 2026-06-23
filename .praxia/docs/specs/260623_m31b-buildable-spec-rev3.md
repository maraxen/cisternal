---
title: Cisterna M3.1b — Cursor + Copilot emitters — Buildable Spec (rev3, adversarially reconciled)
backlog_id: 2487
parent_backlog_id: 2326
brainstorm_session: f04480ad
adversarial_task_id: 260623_m31b-adversarial
prior_spec: 260623_m31-buildable-spec.md
created_at: 2026-06-23
---

# Cisterna M3.1b — Buildable Spec (rev3)

**Scope:** Backlog **#2487** — `CursorEmitter`, `CopilotEmitter`, HookSpec surface filter, golden `cursor|copilot`, `export --surface`.  
**Out of scope:** Antigravity → **M3.1c #2559** (OPTION-C). Parent **#2326** closes after M3.1c, not M3.1b.

**Adversarial verdict:** ACCEPT (reconciled). Challenger FATALs CH-001..003 resolved via L15–L20 below.

---

## Locked decisions (M3.1b additions)

| ID | Decision |
|----|----------|
| L15 | **HookSpec surface filter** — include hook when `surfaces==()` (all) OR `emit_surface in surfaces`. Allowed tokens: `claude`, `cursor`, `copilot` (cisterna adds **copilot**; praxia `hooks_emit.rs` omits it). |
| L16 | **Surface vocabulary** — emit/validate/export: `claude`\|`cursor`\|`copilot`. Capability/inspect resolve_tools: `claude_code`\|`cursor`\|`copilot`\|`antigravity_cli`. |
| L17 | **Cursor fail-closed (cisterna > praxia)** — omit `agents`/`skills` keys from `.cursor-plugin/plugin.json` when corresponding files are not emitted; never empty arrays (AC-M31b-6/7). Praxia lists agents without files when unverified; cisterna **does not**. |
| L18 | **Provenance** — `cisterna-provenance.json` sidecar is **Claude-only**. Cursor/Copilot golden digests hash emitted files only (no sidecar). |
| L19 | **Commands** — cursor/copilot emitters **omit** `commands` in manifest JSON (praxia parity). Registry/manifest commands remain **Claude-only** via `export_command.claude_code`. |
| L20 | **`assets export --surface`** — `claude`\|`cursor`\|`copilot` (default `claude`); dispatches matching `Emitter`. Required for N11 dogfooding; validate already accepts `--surface`. |
| L21 | **Epic closure** — #2487 DoD = AC-M31b-1..7. #2326 closes after **M3.1c #2559** Antigravity ships. Rev2 L10 M3.2 list updated: Antigravity → M3.1c; entry_point plugins remain M3.2+. |

---

## Emitter contracts

### CursorEmitter (`src/cisterna/export/cursor.py`)

Port `praxia/bundle_cursor.rs` with L17 amendments:

| Output path | Content |
|-------------|---------|
| `.cursor-plugin/plugin.json` | `name`, `version`, `description`; optional `agents`, `skills`, `hooks`, `mcpServers` — keys **absent** when empty/not emitted |
| `agents/<n>.agent.md` | When agent has non-empty `body` after manifest load |
| `skills/<n>/SKILL.md` | When skill has non-empty `body` |
| `.cursor/hooks.json` | Cursor camelCase hook dialect (v1); filtered by L15 |
| `.mcp.json` | When `mcp_servers` non-empty |

**Hooks:** Emit hooks in **both** `.cursor-plugin/plugin.json["hooks"]` and `.cursor/hooks.json` (praxia parity). Golden hashes include both.

### CopilotEmitter (`src/cisterna/export/copilot.py`)

Port `praxia/bundle_copilot.rs`:

| Output path | Content |
|-------------|---------|
| `plugin.json` | Top-level; **inline** `hooks` object (camelCase events) |
| `agents/<n>.agent.md` | All agents with non-empty body (no L17 fail-closed) |
| `skills/<n>/SKILL.md` | All skills with non-empty body |
| `.mcp.json` | When MCP non-empty |

**Copilot asymmetry:** L17 applies to **Cursor only**. Copilot lists agents/skills names when bodies present; praxia always lists names — cisterna lists only when files emitted.

### HookSpec filter (shared)

```python
def hooks_for_surface(hook_specs, surface: str) -> tuple[HookSpecAsset, ...]:
    allowed = {"claude", "cursor", "copilot"}
    # surface must be in allowed; filter specs per L15
```

AC-M31b-3 fixture: hook with `surfaces=["cursor"]` appears in cursor export only.

---

## CLI contracts (M3.1b delta)

| Subcommand | New/changed flags |
|------------|-------------------|
| `export` | `--surface claude\|cursor\|copilot` (default `claude`) |
| `validate` | `--surface cursor\|copilot` (extend `surface_digest`) |
| `inspect` | unchanged |

`--emit-command-bodies` applies to **claude** only; ignored for cursor/copilot (L19).

---

## Golden harness

| Surface | Mode | Fixture bundle | Path |
|---------|------|----------------|------|
| `cursor` | `names_only` | `tests/fixtures/manifest_minimal/` via Composite | `tests/golden/cursor/names_only/digest.sha256` |
| `copilot` | `names_only` | same | `tests/golden/copilot/names_only/digest.sha256` |

Digest = `bundle_sha256({path: contents})` over emitted files excluding any provenance sidecar (L18).

---

## Acceptance criteria

| AC | Given | When | Then |
|----|-------|------|------|
| AC-M31b-1 | bundle agents+hooks+skills (manifest_minimal) | `CursorEmitter.emit()` | `.cursor-plugin/plugin.json` + `.cursor/hooks.json` camelCase; agent/skill files when bodies non-empty |
| AC-M31b-2 | same | `CopilotEmitter.emit()` | `plugin.json` inline hooks; `agents/*.agent.md` |
| AC-M31b-3 | hook `surfaces=["cursor"]` | cursor vs copilot emit | hook only on cursor |
| AC-M31b-4 | golden fixtures | `validate --surface cursor\|copilot` | exit 0 |
| AC-M31b-5 | M3 + M3.1a paths | full pytest | all prior ACs green |
| AC-M31b-6 | cursor export, agents without emit bodies | emit | `agents` key **absent** from plugin.json |
| AC-M31b-7 | manifest skill path missing | `validate --surface cursor` | exit 1 (load warning) |
| AC-M31b-8 | any bundle | `export --surface cursor` | writes cursor layout (L20) |

---

## Implementation DAG

```
N9   CursorEmitter + L17 fail-closed + tests
N10  CopilotEmitter + hooks_for_surface (L15) + AC-M31b-3 tests
N11  export --surface + validate surface_digest cursor|copilot + golden fixtures
N12  regression: ClaudeEmitter default + claude golden unchanged (AC-M31b-5)
```

---

## Adversarial reconciliation log

| Finding | Resolution |
|---------|------------|
| CH-001 FATAL copilot missing from valid_surfaces | L15 |
| CH-002 FATAL export no --surface | L20, AC-M31b-8 |
| CH-003 FATAL golden undefined | Golden table + manifest_minimal |
| CH-004 MAJOR cursor fail-closed partial | L17 + AC-M31b-6/7 |
| CH-005 MAJOR cursor hook placement | Both plugin.json hooks + .cursor/hooks.json (praxia parity) |
| CH-006 MAJOR commands on cursor/copilot | L19 |
| CH-007 MAJOR Antigravity epic conflict | L21, M3.1c #2559 |
| CH-008 MAJOR surface vocabulary | L16 |
| CH-009 MAJOR copilot agent rules | Copilot asymmetry note — no L17 |
| CH-010 MAJOR tools resolution at emit | Agent tools pass through as IR tokens (praxia parity); resolve_tools for inspect only |
| CH-011 MAJOR emit_command_bodies on cursor/copilot | Claude-only; ignored elsewhere |
| CH-012 MINOR brainstorm placeholder ACs | This rev3 supersedes brainstorm artifact for gates |
| CH-013 MINOR provenance | L18 |
| CH-014 MINOR stale research Option A | M3.1c per L21 |
| CH-015 MINOR regression test gap | N12 explicit |
| CH-016 MINOR AC-M31b-7 traceability | manifest_minimal + missing-path fixture in tests |

---

## References

- Rev2: `.praxia/docs/specs/260623_m31-buildable-spec.md`
- M3.1a closeout: `.praxia/docs/research/260623_m31a-epic-closeout-audit.md`
- Antigravity scope: `.praxia/docs/research/260623_m31b-antigravity-scope.md`
- Praxia: `bundle_cursor.rs`, `bundle_copilot.rs`, `hooks_emit.rs`
