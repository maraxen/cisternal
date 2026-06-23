# Epic closeout audit — M8 XpeririAdapter (#2145)

**task_id:** `260624_epic-audit_m8`  
**closed_epic:** M8 XpeririAdapter — JSON-string MCP adapter + shadow parity  
**depends_on:** M7 (#2627) OTLP egress  
**next_milestone:** #2146 MyxcelAdapter (M9) · M8.2 xperiri repo cutover  
**date:** 2026-06-24

## Shipped vs claimed

> **Note:** M8 implementation verified on working tree; **not yet committed** to `main` at audit time.

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M8-0 | PASS | `uv run pytest -q` → **328 passed** (baseline 320 post-M7) |
| AC-M8-0b (shadow) | PASS | `uv run pytest tests/shadow/ -q` → **7 passed** (+3 xperiri) |

### M8.1 — XpeririAdapter

| AC | Status | Evidence |
|----|--------|----------|
| AC-M8-1a | PASS | `tests/test_xperiri_adapter.py::test_shape_ok_passthrough_str` |
| AC-M8-1b | PASS | `tests/test_xperiri_adapter.py::test_shape_ok_serializes_dict` |
| AC-M8-1c | PASS | `tests/test_xperiri_adapter.py::test_shape_error_json_string` |
| ALLOWED_NAMES | PASS | `tests/test_mcp.py::TestAdapterAllowedNames::test_xperiri_adapter_allowed_names` |
| Implementation | PASS | `src/cisterna/adapters/base.py::XpeririAdapter` |

### M8.2 — Shadow parity (AC-SHADOW-3)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M8-2a | PASS | `tests/shadow/test_xperiri_shadow.py::test_xperiri_shadow_parity` |
| AC-M8-2b | PASS | `tests/shadow/test_xperiri_shadow.py::test_xperiri_shadow_start_end_ordering` |
| JSON return shape | PASS | `tests/shadow/test_xperiri_shadow.py::test_xperiri_traced_tool_returns_json_str` |

**Total:** 7/7 parent ACs satisfied on working tree.

## Recon validation

| Claim | Status | Evidence |
|-------|--------|----------|
| xperiri MCP returns `str` | VERIFIED | `xperiri/src/xperiri/mcp_server.py` — `expert_list`, `expert_describe`, `expert_resolve`, `expert_consult_tool` all `-> str` |
| Legacy telemetry is stdout `event_log` | VERIFIED | `xperiri/src/xperiri/telemetry.py::event_log` prints JSON |
| Shadow uses logger `xperiri` as cutover contract | DOCUMENTED | `tests/shadow/harness.py` comment; fixture emits via `logging.getLogger("xperiri")` |

## Git delta (uncommitted)

| Path | Role |
|------|------|
| `src/cisterna/adapters/base.py` | `XpeririAdapter` class |
| `tests/test_xperiri_adapter.py` | Unit tests (4) |
| `tests/shadow/test_xperiri_shadow.py` | AC-SHADOW-3 (3) |
| `tests/test_mcp.py` | ALLOWED_NAMES test |
| `tests/shadow/harness.py` | xperiri logger doc |
| `.praxia/docs/specs/260624_m8-xperiri-adapter-buildable-spec-rev1.md` | Buildable spec |

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 328 passed; All checks passed!

uv run pytest tests/shadow/ -q → 7 passed
```

Net **+8** tests vs M7 closeout (320 → 328).

## Pillar balance

| Pillar | Status post-M8 |
|--------|----------------|
| Export trust (M4) | Unchanged |
| Telemetry adoption | 3 adapters (bathos, contemplex, xperiri); 2 consumer cutovers shipped (contemplex, bathos) |
| OTLP egress (M7) | Unchanged |
| Adapter matrix | Xperiri closes M2.5 #2145; Myxcel #2146 remains |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| M8 not committed to `main` | P1 | Commit before treating epic shipped |
| xperiri repo cutover (M8.2) | P2 | Adapter + shadow only; no `telemetry_bridge` in xperiri |
| Shadow vs `event_log` mismatch | P3 | Fixture uses stdlib logger; production xperiri uses stdout JSON today |
| #2146 MyxcelAdapter | open | M9 candidate — job-span semantics |

## Adversarial verdict (condensed)

**ACCEPT** — Implementation matches M1 spec §5.4 XpeririAdapter; no frozen API changes; shadow harness extended without breaking bathos/contemplex tests.

**Nits:**
1. Commit M8 delta to `main`.
2. M8.2 should align xperiri `event_log` → logger or document stdout bridge.

## Verdict

**VERIFY: APPROVE** — M8 parent DoD satisfied (7/7 ACs) on working tree. Route to **TRIAGE** for M9 Myxcel (#2146) or M8.2 xperiri cutover after commit.
