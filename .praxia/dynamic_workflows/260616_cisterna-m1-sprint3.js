// Sprint 3 runner — hand-authored, mirrors Sprint 1/2 runner pattern.
// Source: .praxia/sprint_plans/260616_cisterna-m1-sprint3.toml
// task_id: 260616_cisterna-m1-sprint3   sprint_id: 3
//
// RACE SAFETY: writing chain (A, B) is STRICTLY SEQUENTIAL.
// M1-SHADOW (track A) -> M1-PERF (track B)

export const meta = {
  name: "260616_cisterna-m1-sprint3",
  description: "Cisterna M1 Sprint 3: shadow harness + parity tests (M1-SHADOW) and timing benchmarks (M1-PERF). Sequential A->B.",
  phases: [
    { title: "M1-SHADOW — shadow harness + parity tests (AC-SHADOW-1/2)" },
    { title: "M1-PERF — timing benchmarks (AC-PERF-1a/b/c)" },
    { title: "Audit" },
  ],
};

const TASK_ID = "260616_cisterna-m1-sprint3";
const MAX_FIX_RETRIES = 1;

const VERDICT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["item_id", "verdict", "summary"],
  properties: {
    item_id: { type: "string" },
    verdict: { type: "string", enum: ["PASS", "NEEDS_WORK", "FAIL"] },
    summary: { type: "string" },
    issues: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["where", "problem", "fix"],
        properties: {
          where: { type: "string" },
          problem: { type: "string" },
          fix: { type: "string" },
        },
      },
    },
  },
};

const EMITTER_CTX = `Project: cisterna (Python 3.13 lib, uv/pytest/ruff). Spec:
.praxia/docs/specs/260616_cisterna-m1-telemetry-spec.md (v2).

Foundation + adapters complete (Sprints 1-2). 50 tests green.
IMPORTANT: bathos and contemplex are NOT installed — shadow tests must use
self-contained stubs (log to named logger + cisterna adapter wrap).
Do NOT touch src/.
`;

async function _mainHead(label, phaseName) {
  const out = await agent(
    "Run: git rev-parse HEAD. Return ONLY the 40-character SHA, nothing else.",
    { label, phase: phaseName }
  );
  return (out || "").trim().match(/[0-9a-f]{40}/)?.[0] || "unknown";
}

async function _mergeIntoMain(itemId, phaseName, mergeLabel) {
  return agent(
    "task_id: " + TASK_ID + ". A fixer just implemented \"" + itemId + "\" inside an ISOLATED git worktree " +
    "and committed to an auto-named branch (pattern 'worktree-agent-*'). Integrate it into main:\n" +
    "1. Find the unmerged branch with commits ahead of main:\n" +
    "   for b in $(git for-each-ref --format='%(refname:short)' refs/heads/ | grep '^worktree-agent-'); do " +
    "if [ -n \"$(git log main..$b --oneline 2>/dev/null)\" ]; then echo \"$b\"; fi; done\n" +
    "2. If exactly one branch is listed, merge it into main:\n" +
    "   git checkout main && git merge --no-ff \"<branch>\" -m \"merge " + itemId + " into main\"\n" +
    "   Expect disjoint files / no conflicts. If a conflict occurs, resolve preserving BOTH sides.\n" +
    "3. Do NOT delete the branch or its worktree (the workflow runtime owns cleanup).\n" +
    "4. Report the new main HEAD SHA. If NO branch has commits ahead of main, report 'NO_COMMITS'.",
    { agentType: "merge-specialist", label: mergeLabel, phase: phaseName }
  );
}

async function track(itemId, phaseName, fixerPrompt, reviewerPrompt) {
  log("[" + itemId + "] implement (worktree) -> merge -> review");
  const _pre = await _mainHead("head:" + itemId, phaseName);

  await agent(
    fixerPrompt + "\n\n## WORKTREE PROTOCOL\nYou are in an ISOLATED git worktree branched from main. " +
    "Implement the changes, run `uv run pytest` and `uv run ruff check .` to verify. Then commit: " +
    "git add -A && git commit -m \"" + itemId + ": <one-line summary>\". " +
    "If you do not commit, your work is lost. End with 'verdict: done'.",
    { agentType: "fixer", isolation: "worktree", label: "fix:" + itemId, phase: phaseName }
  );

  await _mergeIntoMain(itemId, phaseName, "merge:" + itemId);

  let _rp = reviewerPrompt + "\n\n## REVIEW TARGET\nThe " + itemId + " changes are now MERGED into main. " +
    "Review on main: git log " + _pre + "..HEAD --oneline then git diff " + _pre + "..HEAD. " +
    "If git log " + _pre + "..HEAD is EMPTY, merge failed — return FAIL.";
  let verdict = await agent(_rp, {
    agentType: "reviewer",
    schema: VERDICT_SCHEMA,
    label: "review:" + itemId,
    phase: phaseName,
  });

  for (let retry = 0; retry < MAX_FIX_RETRIES && verdict && verdict.verdict === "NEEDS_WORK"; retry++) {
    log("[" + itemId + "] NEEDS_WORK — repair " + (retry + 1) + "/" + MAX_FIX_RETRIES);
    const issues = (verdict.issues || []).map((i) => "- " + i.where + ": " + i.problem + " -> " + i.fix).join("\n");
    const _pre2 = await _mainHead("head:" + itemId + ":re" + retry, phaseName);
    await agent(
      fixerPrompt + "\n\n## REPAIR (worktree)\nThe " + itemId + " work is already merged into main. " +
      "Fix EXACTLY these reviewer issues:\n" + issues + "\n\n" +
      "Commit: git add -A && git commit -m \"" + itemId + ": address review\". End with 'verdict: done'.",
      { agentType: "fixer", isolation: "worktree", label: "fix:" + itemId + ":repair" + retry, phase: phaseName }
    );
    await _mergeIntoMain(itemId, phaseName, "merge:" + itemId + ":re" + retry);
    _rp = reviewerPrompt + "\n\n## RE-REVIEW\nReview repaired " + itemId + " on main: git diff " + _pre2 + "..HEAD.";
    verdict = await agent(_rp, {
      agentType: "reviewer",
      schema: VERDICT_SCHEMA,
      label: "review:" + itemId + ":re" + retry,
      phase: phaseName,
    });
  }
  return verdict;
}

// ===== TRACK A — M1-SHADOW ===========================================================
const trackA = () =>
  track(
    "M1-SHADOW",
    "M1-SHADOW — shadow harness + parity tests (AC-SHADOW-1/2)",
    `task_id: ${TASK_ID}

## Objective
Implement the shadow harness (spec §6) and parity tests (AC-SHADOW-1/2).
bathos and contemplex are NOT installed. Self-contained stubs only. Create only new files
in tests/shadow/. Do NOT touch src/.

${EMITTER_CTX}

## Files to create

### tests/shadow/__init__.py
Empty file.

### tests/shadow/harness.py
Shadow harness utilities (spec §6.1-6.3):

  import logging
  from contextlib import contextmanager
  from typing import Iterator
  from cisterna.telemetry.record import Record

  @contextmanager
  def capture_legacy(consumer: str) -> Iterator[list[logging.LogRecord]]:
      """Attach spy logging.Handler to consumer's logger; yield records; detach after."""
      logger = logging.getLogger(consumer)
      original_level = logger.level
      logger.setLevel(logging.DEBUG)
      records: list[logging.LogRecord] = []
      class _Handler(logging.Handler):
          def emit(self, record: logging.LogRecord) -> None:
              records.append(record)
      handler = _Handler()
      logger.addHandler(handler)
      try:
          yield records
      finally:
          logger.removeHandler(handler)
          logger.setLevel(original_level)

  def assert_parity(
      legacy: list[logging.LogRecord],
      cisterna_records: list[Record],
      *,
      duration_tolerance_ms: float = 5.0,
  ) -> None:
      """Assert both streams non-empty and share >= 1 tool name (spec §6.3)."""
      assert len(legacy) >= 1, "Legacy stream must have >= 1 record"
      assert len(cisterna_records) >= 1, "Cisterna stream must have >= 1 record"
      legacy_tools: set[str] = set()
      for lr in legacy:
          # extra kwargs land as attributes directly on LogRecord
          tool = getattr(lr, "tool", None)
          if tool:
              legacy_tools.add(str(tool))
      cisterna_tools: set[str] = {
          r.fields.get("tool", "") for r in cisterna_records if r.fields.get("tool")
      }
      overlap = legacy_tools & cisterna_tools
      assert overlap, (
          f"No matching tool names: legacy={legacy_tools} vs cisterna={cisterna_tools}"
      )

### tests/shadow/test_bathos_shadow.py
AC-SHADOW-1: bathos stub pattern.

Important note: logging.info(msg, extra={...}) puts extra dict keys as ATTRIBUTES on
the LogRecord, not in getMessage(). So extra={"tool": "list_runs_tool"} means
getattr(lr, "tool") == "list_runs_tool". Do NOT use lr.getMessage() to access extra fields.

  import logging, tempfile, time
  from pathlib import Path
  import pytest
  from cisterna import init
  from cisterna.adapters.base import BathosAdapter
  from cisterna.adapters.v2_decorator import traced_tool
  from cisterna.telemetry.exporter import ShadowExporter
  from tests.shadow.harness import assert_parity, capture_legacy

  _bathos_logger = logging.getLogger("bathos")

  @pytest.fixture
  def temp_log_dir():
      with tempfile.TemporaryDirectory() as d:
          yield Path(d)

  @pytest.fixture(autouse=True)
  def cleanup():
      yield
      from cisterna.telemetry import pipeline as pm
      import cisterna.telemetry.self_obs as so_mod
      if pm._global_pipeline:
          pm._global_pipeline.shutdown()
          pm._global_pipeline = None
      with so_mod._heartbeat_lock:
          so_mod._heartbeat_thread = None
          so_mod._last_stat = {"mtime": None, "size": None, "ts": None, "last_growth_ts": None}
          so_mod._jsonl_path = None
      so_mod._last_ec3_warn = 0.0

  class TestAcShadow1:
      def test_bathos_shadow_parity(self, temp_log_dir):
          shadow = ShadowExporter()
          init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

          @traced_tool(BathosAdapter())
          def list_runs_tool():
              _bathos_logger.info("call", extra={"tool": "list_runs_tool", "event": "call"})
              return {"runs": []}

          with capture_legacy("bathos") as legacy:
              list_runs_tool()
              time.sleep(0.05)

          mcp_records = [r for r in shadow.records if r.fields.get("tool") == "list_runs_tool"]
          assert len(legacy) >= 1
          assert len(mcp_records) >= 1
          assert_parity(legacy, mcp_records)

      def test_bathos_shadow_start_end_ordering(self, temp_log_dir):
          shadow = ShadowExporter()
          init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

          @traced_tool(BathosAdapter())
          def list_runs_tool():
              return {"runs": []}

          list_runs_tool()
          time.sleep(0.05)

          tool_records = [r for r in shadow.records if r.fields.get("tool") == "list_runs_tool"]
          names = [r.name for r in tool_records]
          assert "mcp.call_start" in names
          assert "mcp.call_end" in names
          assert names.index("mcp.call_start") < names.index("mcp.call_end")

### tests/shadow/test_contemplex_shadow.py
AC-SHADOW-2: contemplex stub pattern; start->end ordering in both streams.

  import logging, tempfile, time
  from pathlib import Path
  import pytest
  from cisterna import init
  from cisterna.adapters.base import ContemplexAdapter
  from cisterna.adapters.v2_decorator import traced_tool
  from cisterna.telemetry.exporter import ShadowExporter
  from tests.shadow.harness import assert_parity, capture_legacy

  _contemplex_logger = logging.getLogger("contemplex")

  @pytest.fixture
  def temp_log_dir():
      with tempfile.TemporaryDirectory() as d:
          yield Path(d)

  @pytest.fixture(autouse=True)
  def cleanup():
      yield
      from cisterna.telemetry import pipeline as pm
      import cisterna.telemetry.self_obs as so_mod
      if pm._global_pipeline:
          pm._global_pipeline.shutdown()
          pm._global_pipeline = None
      with so_mod._heartbeat_lock:
          so_mod._heartbeat_thread = None
          so_mod._last_stat = {"mtime": None, "size": None, "ts": None, "last_growth_ts": None}
          so_mod._jsonl_path = None
      so_mod._last_ec3_warn = 0.0

  class TestAcShadow2:
      def test_start_end_ordering_in_cisterna(self, temp_log_dir):
          shadow = ShadowExporter()
          init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

          @traced_tool(ContemplexAdapter())
          def brainstorm_start(session_id: str = "test"):
              _contemplex_logger.info("start", extra={"tool": "brainstorm_start"})
              _contemplex_logger.info("end", extra={"tool": "brainstorm_start"})
              return {"session_id": session_id, "ok": True}

          with capture_legacy("contemplex") as legacy:
              brainstorm_start()
              time.sleep(0.05)

          mcp_records = [r for r in shadow.records if r.fields.get("tool") == "brainstorm_start"]
          assert len(legacy) >= 2
          assert len(mcp_records) >= 2
          names = [r.name for r in mcp_records]
          assert names.index("mcp.call_start") < names.index("mcp.call_end")

      def test_contemplex_parity(self, temp_log_dir):
          shadow = ShadowExporter()
          init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

          @traced_tool(ContemplexAdapter())
          def brainstorm_reply(reply: str = "idea"):
              _contemplex_logger.info("reply", extra={"tool": "brainstorm_reply"})
              return {"ok": True}

          with capture_legacy("contemplex") as legacy:
              brainstorm_reply()
              time.sleep(0.05)

          mcp_records = [r for r in shadow.records if r.fields.get("tool") == "brainstorm_reply"]
          assert_parity(legacy, mcp_records)

## Success criteria
uv run pytest tests/shadow/ green. Full uv run pytest green. uv run ruff check . clean.`,
    `task_id: ${TASK_ID}

## Checks (spec §6, AC-SHADOW-1/2)
1. tests/shadow/__init__.py exists.
2. harness.py: capture_legacy uses logging.Handler; assert_parity checks non-empty + tool overlap.
3. harness uses getattr(lr, "tool") not lr.getMessage() to read extra fields.
4. test_bathos_shadow.py: AC-SHADOW-1 — >= 1 records each side; tool names match; ordering.
5. test_contemplex_shadow.py: AC-SHADOW-2 — start->end ordering; parity.
6. Self-contained (no real bathos/contemplex needed).
7. uv run pytest tests/shadow/ green. Full uv run pytest green. uv run ruff check . clean.
## Pass criterion: AC-SHADOW-1/2 pass; full suite green; ruff clean.`
  );

// ===== TRACK B — M1-PERF =============================================================
const trackB = () =>
  track(
    "M1-PERF",
    "M1-PERF — timing benchmarks (AC-PERF-1a/b/c)",
    `task_id: ${TASK_ID}

## Objective
Implement timing benchmarks for AC-PERF-1a/b/c. Create tests/test_perf.py.
M1-SHADOW is already merged. Do NOT touch src/.

${EMITTER_CTX}

## File to create: tests/test_perf.py

```python
"""Performance benchmarks: AC-PERF-1a, AC-PERF-1b, AC-PERF-1c (spec §8)."""
import asyncio
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from cisterna import emit_event, init
from cisterna.adapters.base import BathosAdapter
from cisterna.adapters.v3_middleware import CisternaMiddleware
from cisterna.telemetry.context import _build_record
from cisterna.telemetry.exporter import ShadowExporter
from cisterna.telemetry.pipeline import EventPipeline


@pytest.fixture
def temp_log_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    from cisterna.telemetry import pipeline as pm
    import cisterna.telemetry.self_obs as so_mod
    if pm._global_pipeline:
        pm._global_pipeline.shutdown()
        pm._global_pipeline = None
    with so_mod._heartbeat_lock:
        so_mod._heartbeat_thread = None
        so_mod._last_stat = {"mtime": None, "size": None, "ts": None, "last_growth_ts": None}
        so_mod._jsonl_path = None
    so_mod._last_ec3_warn = 0.0


class TestAcPerf1a:
    """AC-PERF-1a: emit_event x1000 with 2 exporters; median per-call < 1ms."""

    def test_emit_event_median_under_1ms(self, temp_log_dir):
        shadow1, shadow2 = ShadowExporter(), ShadowExporter()
        # Use ShadowExporters only — pure enqueue path, no disk I/O
        init(log_dir=temp_log_dir, exporters=[shadow1, shadow2], heartbeat_interval=30.0)

        durations_ns: list[int] = []
        for _ in range(1000):
            t0 = time.perf_counter_ns()
            emit_event("mcp.call_start", tool="bench", request_id="r")
            durations_ns.append(time.perf_counter_ns() - t0)

        median_ms = statistics.median(durations_ns) / 1_000_000
        assert median_ms < 1.0, (
            f"Median emit_event {median_ms:.4f}ms >= 1ms threshold (AC-PERF-1a)"
        )


class TestAcPerf1b:
    """AC-PERF-1b: CisternaMiddleware on_call_tool x500; median overhead < 1ms."""

    def test_middleware_overhead_median_under_1ms(self, temp_log_dir):
        shadow = ShadowExporter()
        init(log_dir=temp_log_dir, exporters=[shadow], heartbeat_interval=30.0)

        middleware = CisternaMiddleware()
        ctx = Mock()
        ctx.message.name = "bench_tool"
        ctx.message.arguments = {}

        async def call_next(_):
            return {}

        async def run_benchmark() -> list[int]:
            durations_ns: list[int] = []
            for _ in range(500):
                t0 = time.perf_counter_ns()
                await middleware.on_call_tool(ctx, call_next)
                durations_ns.append(time.perf_counter_ns() - t0)
            return durations_ns

        durations_ns = asyncio.run(run_benchmark())
        median_ms = statistics.median(durations_ns) / 1_000_000
        assert median_ms < 1.0, (
            f"Median middleware overhead {median_ms:.4f}ms >= 1ms threshold (AC-PERF-1b)"
        )


class TestAcPerf1c:
    """AC-PERF-1c: queue capacity 10, 100 events before drain; drop_count >= 90."""

    def test_drop_on_full_no_exception(self):
        shadow = ShadowExporter()
        pipeline = EventPipeline(queue_size=10, exporters=[shadow])

        # Build a minimal record for raw pipeline emit
        record = _build_record("mcp.call_start", ts=time.time(), tool="t", request_id="r")

        # Rapid-fire 100 emits into the tiny queue before consumer can drain
        for _ in range(100):
            pipeline.emit(record)

        # Wait briefly for consumer to process what it can
        time.sleep(0.1)

        assert pipeline.drop_count >= 90, (
            f"drop_count={pipeline.drop_count} < 90; queue may have drained too fast "
            "(AC-PERF-1c: expected >= 90 drops with queue_size=10 and 100 rapid emits)"
        )

        pipeline.shutdown()
```

## Success criteria
uv run pytest tests/test_perf.py green. Full uv run pytest green. uv run ruff check . clean.`,
    `task_id: ${TASK_ID}

## Checks (spec §8 AC-PERF-1a/b/c)
1. AC-PERF-1a: 2 ShadowExporters, emit_event x1000, assert median_ms < 1.0.
2. AC-PERF-1b: CisternaMiddleware, mock call_next, 500 asyncio iterations, assert median_ms < 1.0.
3. AC-PERF-1c: EventPipeline(queue_size=10), 100 rapid emits, assert drop_count >= 90.
4. time.perf_counter_ns() used for timing precision.
5. cleanup fixture resets global pipeline + self_obs state (including _last_ec3_warn).
6. uv run pytest tests/test_perf.py green. Full uv run pytest green. uv run ruff check . clean.
## Pass criterion: AC-PERF-1a/b/c all pass; full suite green; ruff clean.`
  );

// ---- orchestrate: A -> B sequential -------------------------------------------------
const _gitBase = (await agent(
  "Run: git rev-parse HEAD. Return only the 40-character SHA, nothing else.",
  { label: "git-base", phase: "M1-SHADOW — shadow harness + parity tests (AC-SHADOW-1/2)" }
)).trim();

log("Cisterna M1 Sprint 3: M1-SHADOW -> M1-PERF (sequential)");

const a = await trackA();
const b = await trackB();

phase("Audit");
const _auditVerdict = await agent(
  "task_id: " + TASK_ID + ". Audit Sprint 3 changes committed since " + _gitBase + ".\n" +
  "Run: git log " + _gitBase + "..HEAD --oneline to list commits.\n" +
  "Run: uv run pytest to confirm all tests pass.\n" +
  "Review all new files against:\n" +
  "- AC-SHADOW-1/2 (shadow harness + parity tests; bathos + contemplex patterns)\n" +
  "- AC-PERF-1a/b/c (emit < 1ms median; middleware < 1ms; drop_count >= 90)\n" +
  "Spec: .praxia/docs/specs/260616_cisterna-m1-telemetry-spec.md\n" +
  "Return PASS or FAIL with findings.",
  { label: "auditor", phase: "Audit", agentType: "auditor" }
);

return {
  task_id: TASK_ID,
  sprint_id: 3,
  verdicts: {
    "M1-SHADOW": a,
    "M1-PERF": b,
  },
  audit: _auditVerdict,
};
