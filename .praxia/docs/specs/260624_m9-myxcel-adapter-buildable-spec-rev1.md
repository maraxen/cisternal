---
title: M9 MyxcelAdapter — buildable spec rev1
brainstorm: .praxia/docs/specs/260623_m9-milestone-for-cisterna-after-m8-xpe.md
task_id: 260624_m9-myxcel-adapter
depends_on_epic: 2628
---

# M9 MyxcelAdapter — buildable spec (rev1)

**Goal:** `MyxcelAdapter` + `job_span()` helper + shadow tests; close #2146. Recon-gated envelope shape.

## Child packages

| ID | Deliverable |
|----|-------------|
| **M9.0** | Recon `myxcel` MCP return shapes |
| **M9.1** | `MyxcelAdapter` in `base.py` |
| **M9.2** | `job_span()` context helper (task_id / run_uuid) |
| **M9.3** | `tests/shadow/test_myxcel_shadow.py` (AC-SHADOW-4) |

## AC matrix (draft)

| AC | Then |
|----|------|
| AC-M9-0 | ≥328 tests green post-merge |
| AC-M9-1 | `MyxcelAdapter.shape_ok/shape_error` match recon |
| AC-M9-2 | `job_span()` emits `*.start/end` with task_id in Record |
| AC-M9-3 | Shadow parity for MCP + job span fixtures |

## Out of scope

- myxcel repo `telemetry_bridge` (M9.2 external)
- M8.2 xperiri cutover
- M7.1 OTLP hardening
