# Epic closeout audit — M9 MyxcelAdapter (#2146)

**task_id:** `260624_epic-audit_m9`  
**closed_epic:** M9 MyxcelAdapter — dict MCP adapter + `job_span()` HPC helper + shadow parity  
**depends_on:** M8 (#2145) XpeririAdapter  
**next_milestone:** M9.2 myxcel repo `telemetry_bridge` cutover · M8.2 xperiri cutover · M7.1 OTLP hardening  
**date:** 2026-06-24

## Shipped vs claimed

### Epic DoD

| AC | Status | Evidence |
|----|--------|----------|
| AC-M9-0 | PASS | `uv run pytest -q` → **342 passed** (baseline 328 post-M8) |
| AC-M9-0b (shadow) | PASS | `uv run pytest tests/shadow/ -q` → **11 passed** (+4 myxcel) |

### M9.1 — MyxcelAdapter

| AC | Status | Evidence |
|----|--------|----------|
| AC-M9-1a dict passthrough | PASS | `tests/test_myxcel_adapter.py::test_shape_ok_passthrough_dict` |
| AC-M9-1b list passthrough | PASS | `tests/test_myxcel_adapter.py::test_shape_ok_passthrough_list` |
| AC-M9-1c in-band error dict | PASS | `tests/test_myxcel_adapter.py::test_shape_ok_in_band_error_dict` |
| AC-M9-1d shape_error | PASS | `tests/test_myxcel_adapter.py::test_shape_error_matches_tool_error` |
| ALLOWED_NAMES | PASS | `tests/test_mcp.py::TestAdapterAllowedNames::test_myxcel_adapter_allowed_names` |
| Implementation | PASS | `src/cisterna/adapters/base.py::MyxcelAdapter` |

### M9.2 — job_span()

| AC | Status | Evidence |
|----|--------|----------|
| AC-M9-2a MYX_JOB_ID → Record.task_id | PASS | `tests/test_job_span.py::test_job_span_sets_task_id_from_myx_job_id` |
| AC-M9-2b BTH_TASK_ID fallback | PASS | `tests/test_job_span.py::test_job_span_falls_back_to_bth_task_id` |
| AC-M9-2c run_uuid from env | PASS | `tests/test_job_span.py::test_job_span_sets_run_uuid_from_env` |
| Public export | PASS | `cisterna.job_span` in `src/cisterna/__init__.py::__all__` |

### M9.3 — Shadow parity (AC-SHADOW-4)

| AC | Status | Evidence |
|----|--------|----------|
| AC-M9-3a MCP parity | PASS | `tests/shadow/test_myxcel_shadow.py::test_myxcel_shadow_parity` |
| AC-M9-3b start/end ordering | PASS | `tests/shadow/test_myxcel_shadow.py::test_myxcel_shadow_start_end_ordering` |
| AC-M9-3c in-band error shape | PASS | `tests/shadow/test_myxcel_shadow.py::test_myxcel_traced_tool_in_band_error_shape` |
| AC-M9-3d job span fixture | PASS | `tests/shadow/test_myxcel_shadow.py::test_myxcel_job_span_emits_with_task_id` |

**Total:** 4/4 parent ACs + 14 child checks satisfied on working tree.

## Recon validation

| Claim | Status | Evidence |
|-------|--------|----------|
| myxcel MCP returns `dict` on success | VERIFIED | `myxcel/src/myxcel/mcp_server.py::mount_project` → `_result_to_dict(result)` |
| myxcel errors use `{error, message}` | VERIFIED | `myxcel/src/myxcel/mcp_server.py::_tool_error` |
| myxcel `mount_status` returns `list[dict]` | VERIFIED | `myxcel/src/myxcel/mcp_server.py::mount_status` |
| Shadow uses logger `myxcel` as cutover contract | DOCUMENTED | `tests/shadow/harness.py`; fixtures use `logging.getLogger("myxcel")` |
| Bathos envelope **not** used for myxcel | VERIFIED | Recon corrected brainstorm assumption; `MyxcelAdapter.shape_error` matches `_tool_error` |

## Git delta (pre-commit)

| Path | Role |
|------|------|
| `src/cisterna/adapters/base.py` | `MyxcelAdapter` class |
| `src/cisterna/telemetry/span.py` | `job_span()` helper |
| `src/cisterna/__init__.py`, `telemetry/__init__.py` | Public `job_span` export |
| `tests/test_myxcel_adapter.py` | Unit tests (6) |
| `tests/test_job_span.py` | job_span tests (3) |
| `tests/shadow/test_myxcel_shadow.py` | AC-SHADOW-4 (4) |
| `tests/test_mcp.py` | ALLOWED_NAMES test |
| `tests/shadow/harness.py` | myxcel logger doc |
| `.praxia/docs/specs/260624_m9-myxcel-adapter-buildable-spec-rev1.md` | Buildable spec |

## Regression status

```
uv run pytest -q && uv run ruff check .
→ 342 passed; All checks passed!

uv run pytest tests/shadow/ -q → 11 passed
```

Net **+14** tests vs M8 closeout (328 → 342).

## Pillar balance

| Pillar | Status post-M9 |
|--------|----------------|
| Export trust (M4) | Unchanged |
| Telemetry adoption | 4 adapters (bathos, contemplex, xperiri, myxcel); 2 consumer cutovers shipped |
| OTLP egress (M7) | Unchanged |
| Adapter matrix | Myxcel closes M2.5 #2146; all M1.5 adapters now in cisterna |

## Open risks / debt

| Item | Severity | Notes |
|------|----------|-------|
| myxcel repo cutover (M9.2) | P2 | Adapter + shadow only; no `telemetry_bridge` in myxcel yet |
| `traced_tool` sync-only | P3 | myxcel MCP tools are async; cutover needs async wrapper or middleware path |
| xperiri repo cutover (M8.2) | P2 | Still open |
| M7.1 OTLP HTTP / collector CI | P3 | gRPC-only today |

## Adversarial verdict (condensed)

**ACCEPT** — Recon-gated envelope matches myxcel source; `job_span()` correctly snapshots `task_id_var`/`run_uuid_var`; no frozen API regressions; shadow suite extended without breaking bathos/contemplex/xperiri tests.

**Nits:**
1. M9.2 should wire `telemetry_bridge` in myxcel with `traced_tool(MyxcelAdapter())` on sync stubs or FastMCP middleware.
2. Document env var precedence (`MYX_JOB_ID` > `BTH_TASK_ID`) in operator runbook when M9.2 lands.

## Verdict

**VERIFY: APPROVE** — M9 parent DoD satisfied (4/4 ACs) on working tree. Route to **TRIAGE** for M9.2 myxcel cutover or M8.2 xperiri cutover.
