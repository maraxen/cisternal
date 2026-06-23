---
title: M8 XpeririAdapter — buildable spec rev1
brainstorm: .praxia/docs/specs/260623_m8-milestone-for-cisterna-after-m7-otlp.md
task_id: 260624_m8-xperiri-adapter
depends_on_epic: 2627
---

# M8 XpeririAdapter — buildable spec (rev1)

**Goal:** Implement `XpeririAdapter` + shadow parity tests; close #2145. Repo cutover deferred to M8.2.

**Recon:** `xperiri/mcp_server.py` — all 4 tools return `str` (JSON); errors embedded in JSON, not raised.

## AC matrix

| AC | Given | When | Then |
|----|-------|------|------|
| **AC-M8-0** | M8 merged | `uv run pytest -q` | ≥320 tests green |
| **AC-M8-1a** | `XpeririAdapter` | `shape_ok` with str | Passthrough unchanged |
| **AC-M8-1b** | `XpeririAdapter` | `shape_ok` with dict | `json.dumps` sorted |
| **AC-M8-1c** | `XpeririAdapter` | `shape_error` | JSON str `{"ok": false, "error": ...}` |
| **AC-M8-2a** | Shadow harness | `expert_list` traced tool | `assert_parity` passes (AC-SHADOW-3) |
| **AC-M8-2b** | Shadow harness | traced tool call | `mcp.call_start` before `mcp.call_end` |

## Out of scope

- xperiri repo `telemetry_bridge` (M8.2)
- MyxcelAdapter (#2146 → M9)
