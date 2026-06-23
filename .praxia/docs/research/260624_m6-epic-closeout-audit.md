# Epic closeout audit — M6 Bathos Telemetry Cutover (#2622/#2623)

**task_id:** `260624_epic-audit_m6`  
**closed_epic:** M6 Bathos Telemetry Cutover — second consumer adoption  
**children:** M6.1a (#2622 cisterna gate), M6.1b (#2623 bathos bridge)  
**depends_on:** M5 (#2609) + M5.2 contemplex cutover (#2613)  
**next_milestone:** M7 OTLP egress (brainstorm runner-up) · #2145/#2146 external adapters  
**date:** 2026-06-24

## Shipped vs claimed

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M6-0 | PASS | `uv run pytest -q` → **314 passed** (baseline 311 post-M5) |
| AC-M6-0b | PASS | `uv run pytest tests/shadow/ -q` → **4 passed** |

### M6.1a — cisterna gate (#2622)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M6-2a | PASS | `tests/test_bathos_telemetry_cutover.py::test_consumer_telemetry_enabled_bathos_flag` |
| AC-M6-2b | PASS | `tests/test_bathos_telemetry_cutover.py::test_consumer_telemetry_disabled_when_unset` |
| AC-M6-2c | PASS | `tests/test_bathos_telemetry_cutover.py::test_traced_tool_emits_when_cutover_enabled` |
| Flaky fix | PASS | `tests/test_core.py::TestNeverRaise::test_raising_exporter_swallowed` — poll loop (debt #238) |

### M6.1b — bathos bridge (#2623, external repo)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M6-3a | PASS | `bathos/tests/test_telemetry_bridge.py::test_legacy_event_writes_jsonl` |
| AC-M6-3b | PASS | `bathos/tests/test_telemetry_bridge.py::test_cisterna_event_when_flag_set` (py≥3.13) |
| AC-M6-3c | PASS | `bathos/src/bathos/mcp.py::mcp_server` → `init_server_telemetry()` |
| Bridge | PASS | `bathos/src/bathos/telemetry_bridge.py` — `init_via_cisterna`, `emit_via_cisterna`, `span_via_cisterna` |
| Delegation | PASS | `bathos/src/bathos/telemetry.py` — init/event/span delegate when flag set |

**Total:** 9/9 parent ACs satisfied.

## Git delta

| Repo | Commit | Summary |
|------|--------|---------|
| cisterna | `cea0cf9` | Gate tests, flaky fix, M6 specs, loop_state |
| bathos | `ced0d47` | telemetry_bridge, telemetry hooks, mcp entry, bridge tests |

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 314 passed; All checks passed!

uv run pytest tests/shadow/ -q → 4 passed
```

Net **+3** tests vs M5 closeout (311 → 314).

Bathos (sibling, py3.13 + cisterna extra): full suite green; 8 bridge tests pass.

## Pillar balance

| Pillar | Status post-M6 |
|--------|----------------|
| Export trust (M4) | Unchanged; export-dogfood workflow still green |
| Telemetry adoption | **Two consumers** cut over (contemplex #2613, bathos #2623); env-gated pattern proven twice |
| Shadow parity | Bathos/contemplex shadow fixtures unchanged — still gate before cutover |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| Bathos cutover requires Python ≥3.13 for cisterna dep | P2 | Document in bathos SKILL; py3.12 bathos keeps legacy telemetry |
| `consumer_telemetry_enabled` not wired inside bathos package | P3 | Bridge uses duplicate env check; acceptable for optional dep |
| Debt #238 | RESOLVED | Poll loop in test_raising_exporter_swallowed |
| M7 OTLP egress | deferred | M6 brainstorm runner-up |
| #2145 / #2146 external adapters | open | Out of M6 scope |

## Verdict

**VERIFY: APPROVE** — M6 parent DoD satisfied (9/9 ACs). Route to **TRIAGE** for M7 (OTLP) or external adapter epics.
