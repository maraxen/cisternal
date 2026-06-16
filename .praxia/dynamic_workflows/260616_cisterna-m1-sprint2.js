// Sprint 2 runner — hand-authored, mirrors Sprint 1 runner pattern.
// Source: .praxia/sprint_plans/260616_cisterna-m1-sprint2.toml
// task_id: 260616_cisterna-m1-sprint2   sprint_id: 2
//
// RACE SAFETY: writing chain (A, B, C) is STRICTLY SEQUENTIAL —
// exactly one fixer touches the working tree at a time.

export const meta = {
  name: "260616_cisterna-m1-sprint2",
  description: "Cisterna M1 Sprint 2: MCP adapter layer + CLI adapter + EC-3 warn policy. Sequential A->B->C to keep merges clean.",
  phases: [
    { title: "M1-MCP — adapter layer + MCP surfaces + name-freeze" },
    { title: "M1-CLI — Typer/Cyclopts CLI timing adapter" },
    { title: "M1-SELF — EC-3 warn-on-dead-pipeline policy" },
    { title: "Audit" },
  ],
};

const TASK_ID = "260616_cisterna-m1-sprint2";
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

const EMITTER_CTX = `Project: cisterna (Python 3.13 lib, uv/pytest/ruff). Spec is authoritative:
.praxia/docs/specs/260616_cisterna-m1-telemetry-spec.md (v2, post-adversarial-review).

Foundation complete (Sprint 1): context.py, record.py, pipeline.py, exporter.py, span.py,
self_obs.py, __init__.py. 21 tests green. Adapter skeletons (empty __init__.py) exist in
src/cisterna/adapters/ and src/cisterna/probe/.

Stack rules: uv run python (never bare python); pytest; ruff. Do NOT touch telemetry/ files.
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
    "Review on main: run git log " + _pre + "..HEAD --oneline then git diff " + _pre + "..HEAD. " +
    "If git log " + _pre + "..HEAD is EMPTY, the merge failed — return FAIL.";
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

// ===== TRACK A — M1-MCP =============================================================
const trackA = () =>
  track(
    "M1-MCP",
    "M1-MCP — adapter layer + MCP surfaces + name-freeze",
    `task_id: ${TASK_ID}

## Objective
Implement the adapter layer per spec §3.6-3.8, §4, §5. Foundation (telemetry/) is already
built — do NOT touch it. Create only new files in src/cisterna/adapters/ and
src/cisterna/probe/; write tests in tests/test_mcp.py and tests/test_namefreeze.py.

${EMITTER_CTX}

## Files to create

### src/cisterna/adapters/base.py
AdapterBase ABC + BathosAdapter + ContemplexAdapter (spec §3.6, §5.4):

- AdapterBase: ALLOWED_NAMES: frozenset[str] (subclass must define as class variable).
  emit_start(tool_name, arg_keys, request_id): check name in ALLOWED_NAMES else _swallow;
  call emit_event("mcp.call_start", tool=tool_name, arg_keys=arg_keys, request_id=request_id).
  emit_end(tool_name, request_id, duration_ms): emit "mcp.call_end".
  emit_error(tool_name, request_id, exc): emit "mcp.tool_error" with exc_type/exc_msg.
  shape_ok/shape_error: abstract.
  _swallow_name_error(name) -> bool: print to stderr, return True.
- BathosAdapter: ALLOWED_NAMES = frozenset({"mcp.call_start","mcp.call_end","mcp.tool_error"}).
  shape_ok: if isinstance(result,dict) return {**result,"ok":True,"error_code":None,"error":None,"resolution_hint":None};
    else return {"ok":True,"error_code":None,"error":None,"resolution_hint":None}.
  shape_error: return {"ok":False,"error_code":"INTERNAL","error":str(exc),"resolution_hint":""}.
- ContemplexAdapter: ALLOWED_NAMES same as BathosAdapter.
  shape_ok: return result unchanged.
  shape_error: try: from contemplex.errors import ErrorCode,err_envelope; return err_envelope(ErrorCode.INTERNAL,...).
    except ImportError: return {"ok":False,"error_code":"INTERNAL","error":str(exc)}.

### src/cisterna/adapters/v3_middleware.py
CisternaMiddleware(Middleware) — spec §3.7:
  from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext
  from mcp import types as mt
  MiddlewareContext[mt.CallToolRequestParams].message has .name: str and .arguments: dict|None.

  async def on_call_tool(self, context, call_next):
      tool_name = context.message.name
      arguments = context.message.arguments or {}
      arg_keys = sorted(arguments.keys())
      request_id = uuid.uuid4().hex
      token = mcp_request_id_var.set(request_id)
      adapter = BathosAdapter()
      adapter.emit_start(tool_name, arg_keys, request_id)
      t0 = time.monotonic_ns()
      try:
          result = await call_next(context)
          adapter.emit_end(tool_name, request_id, (time.monotonic_ns()-t0)/1e6)
          return adapter.shape_ok(tool_name, result)
      except Exception as exc:
          adapter.emit_error(tool_name, request_id, exc)
          return adapter.shape_error(tool_name, exc)
      finally:
          try:
              mcp_request_id_var.reset(token)
          except ValueError:
              pass  # AC-MCP-4: Token from different Context raises ValueError; swallow

### src/cisterna/adapters/v2_decorator.py
traced_tool(adapter: AdapterBase) double-decorator — spec §3.8. Same token/emit/reset
pattern. In except: emit_error then return shape_error (never re-raise). finally resets
token with except ValueError: pass.

### src/cisterna/probe/capability_probe.py
_has_v3_middleware() -> bool: try-import Middleware from fastmcp.server.middleware.middleware.
CONSUMER_SURFACE dict: bathos -> "v3_middleware" if _has_v3_middleware() else "v2_decorator";
contemplex/myxcel/xperiri -> "v2_decorator". surface_for(consumer) -> str.

### tests/test_mcp.py
Cover AC-MCP-1..4. Use ShadowExporter from cisterna.telemetry.exporter. Use same
temp_log_dir + cleanup fixtures as test_selfcheck.py (pass heartbeat_interval=0.05 to init).

AC-MCP-1: Create a mock MiddlewareContext with message.name="test_tool" and
  message.arguments={"a": 1} (SimpleNamespace works). Mock async call_next returning "ok".
  await CisternaMiddleware().on_call_tool(ctx, async_call_next). Assert shadow.records
  contains a record with name=="mcp.call_start" and fields["tool"]=="test_tool" and
  fields["arg_keys"]==["a"], and a record with name=="mcp.call_end".

AC-MCP-2: traced_tool(ContemplexAdapter()) wrapping a sync fn returning "result"; call with
  kwarg foo=1. Assert shadow has mcp.call_start (arg_keys=["foo"]) and mcp.call_end.

AC-MCP-3: Mock call_next raises RuntimeError("boom"). Run on_call_tool. Assert shadow has
  mcp.tool_error with exc_type=="RuntimeError". Assert return value has ok==False. Assert
  no exception escapes.

AC-MCP-3b: traced_tool(ContemplexAdapter()) wrapping fn that raises ValueError. Call wrapper.
  Assert mcp.tool_error in shadow.records. Assert no exception propagates.

AC-MCP-4: monkeypatch mcp_request_id_var.reset to raise ValueError. Run on_call_tool with
  a call_next that returns normally. Verify call completes without exception.

### tests/test_namefreeze.py
Helper: _emit_event_names_in_file(path: Path) -> list[str]: use ast.walk to collect first
positional string arg to emit_event() calls.

AC-NAMEFREEZE-1: call helper on src/cisterna/adapters/v3_middleware.py; assert all names
  are in BathosAdapter.ALLOWED_NAMES.

AC-NAMEFREEZE-2: define _validate_names(names, allowed) -> list[str] (returns violations);
  assert _validate_names(["mcp.call_begin"], BathosAdapter.ALLOWED_NAMES) == ["mcp.call_begin"].

AC-NAMEFREEZE-3: for f in Path("src/cisterna/adapters").glob("*.py"): assert "cisterna/adapters" in str(f).

AC-NAMEFREEZE-4: monkeypatch BathosAdapter._swallow_name_error to raise AssertionError;
  define class BadAdapter(AdapterBase) with ALLOWED_NAMES=frozenset(); call
  BadAdapter().emit_start("mcp.call_start",[],"r") on an instance with pipeline init;
  assert AssertionError propagates.

## Success criteria
uv run pytest tests/test_mcp.py tests/test_namefreeze.py green.
uv run pytest (full suite) green. uv run ruff check . clean.`,
    `task_id: ${TASK_ID}

## Checks (spec §3.6-3.8, §4, §5, AC-MCP-1..4, AC-NAMEFREEZE-1..4)
1. base.py: ALLOWED_NAMES check before emit_event; _swallow_name_error present.
2. BathosAdapter.shape_ok merges ok/error_code/error/resolution_hint into dict results.
3. ContemplexAdapter.shape_error has try-import fallback on ImportError.
4. v3_middleware.py: mcp_request_id_var token reset in finally with except ValueError: pass.
5. v2_decorator.py: same token/finally pattern; never re-raises tool exceptions.
6. probe: _has_v3_middleware() and CONSUMER_SURFACE dict present.
7. AC-MCP-1..4 tested with real assertions.
8. AC-NAMEFREEZE-1..4 covered in tests/test_namefreeze.py.
9. uv run pytest green; uv run ruff check . clean.
## Pass criterion: AC-MCP-1..4 and AC-NAMEFREEZE-1..4 pass; full suite green; ruff clean.`
  );

// ===== TRACK B — M1-CLI =============================================================
const trackB = () =>
  track(
    "M1-CLI",
    "M1-CLI — Typer/Cyclopts CLI timing adapter",
    `task_id: ${TASK_ID}

## Objective
Implement the CLI timing adapter per spec §4.2, gate AC-CLI-1. M1-MCP is already merged.
Create only new files.

${EMITTER_CTX}

## Files to create

### src/cisterna/adapters/cli.py
CliAdapter + timed_command decorator:

  class CliAdapter(AdapterBase):
      ALLOWED_NAMES = frozenset({"cli.cmd_start", "cli.cmd_end"})
      def shape_ok(self, tool_name, result): return None
      def shape_error(self, tool_name, exc, **fields): return None

  def timed_command(cmd_name: str | None = None):
      def decorator(fn):
          name = cmd_name or fn.__name__
          @functools.wraps(fn)
          def wrapper(*args, **kwargs):
              emit_event("cli.cmd_start", cmd=name)
              t0 = time.monotonic_ns()
              try:
                  result = fn(*args, **kwargs)
                  emit_event("cli.cmd_end", cmd=name,
                             duration_ms=(time.monotonic_ns()-t0)/1e6, ok=True)
                  return result
              except Exception as exc:
                  emit_event("cli.cmd_end", cmd=name,
                             duration_ms=(time.monotonic_ns()-t0)/1e6,
                             ok=False, exc_type=type(exc).__name__)
                  raise
          return wrapper
      return decorator

timed_command RE-RAISES on exception (CLI owns exit code; unlike MCP adapters).

### tests/test_cli.py
AC-CLI-1: init with ShadowExporter + heartbeat_interval=0.05. Decorate a function with
  @timed_command(). Call it. Assert cli.cmd_start and cli.cmd_end in shadow.records.
  Verify cmd field matches function name.

Also test: timed_command("custom_name") uses cmd="custom_name"; exception case emits
  cli.cmd_end ok=False and re-raises.

## Success criteria
uv run pytest tests/test_cli.py green. Full uv run pytest green. uv run ruff check . clean.`,
    `task_id: ${TASK_ID}

## Checks (§4.2, AC-CLI-1)
1. CliAdapter.ALLOWED_NAMES = frozenset({"cli.cmd_start", "cli.cmd_end"}).
2. timed_command emits cli.cmd_start before fn() and cli.cmd_end after with duration_ms.
3. On exception: cli.cmd_end ok=False emitted, then re-raise.
4. Tests cover: clean run (AC-CLI-1), explicit cmd_name, exception case.
5. uv run pytest tests/test_cli.py green; full uv run pytest green; ruff clean.
## Pass criterion: AC-CLI-1 passes; no regressions; ruff clean.`
  );

// ===== TRACK C — M1-SELF (EC-3 warn policy) =========================================
const trackC = () =>
  track(
    "M1-SELF",
    "M1-SELF — EC-3 warn-on-dead-pipeline policy",
    `task_id: ${TASK_ID}

## Objective
Implement the EC-3 dead-pipeline warn policy (spec §7.3): warn-and-continue (no auto-restart
in M1). Liveness probe already passes AC-SELFCHECK-1/2. Edit ONLY
src/cisterna/telemetry/self_obs.py and tests/test_selfcheck.py.

${EMITTER_CTX}

## Changes to src/cisterna/telemetry/self_obs.py

Add at module level:
  _last_ec3_warn: float = 0.0

Add two functions:

  def _check_ec3_warn() -> None:
      import sys, time
      from cisterna.telemetry import pipeline as _pipeline_mod
      p = _pipeline_mod.get_pipeline()
      if p is None or p.is_alive():
          return
      with _heartbeat_lock:
          last_growth = _last_stat.get("last_growth_ts")
          interval = _heartbeat_interval
      if last_growth is None:
          return
      staleness = time.time() - last_growth
      if staleness > 2 * interval:
          print(
              f"[cisterna] WARNING: pipeline consumer dead "
              f"(staleness={staleness:.1f}s); "
              "EC-3: warn-and-continue policy active",
              file=sys.stderr,
          )

  def _maybe_warn_ec3() -> None:
      global _last_ec3_warn
      import time
      now = time.time()
      if now - _last_ec3_warn < 60.0:
          return
      _last_ec3_warn = now
      _check_ec3_warn()

Find the function that performs the liveness probe (called inside the heartbeat thread —
the function that does the mtime/size stat check of the JSONL file). At the END of that
function (after the liveness update logic), add a call to _maybe_warn_ec3().

## Changes to tests/test_selfcheck.py

1. In the cleanup fixture: add
     self_obs_module._last_ec3_warn = 0.0
   alongside the existing resets.

2. Add this test inside one of the existing classes or as a standalone function:

   def test_ec3_warn_emits_stderr(self, temp_log_dir, capsys):
       init(log_dir=temp_log_dir, heartbeat_interval=0.05)
       emit_event("initial.event")
       time.sleep(0.15)  # let file grow so last_growth_ts is set

       from cisterna.telemetry import pipeline as pipeline_module
       pipeline = pipeline_module._global_pipeline
       if pipeline and pipeline._listener:
           pipeline._listener.stop()
           pipeline._listener.join(timeout=1.0)

       time.sleep(0.15)  # let liveness go stale (> 2x interval)

       import cisterna.telemetry.self_obs as so
       so._last_ec3_warn = 0.0
       so._check_ec3_warn()

       captured = capsys.readouterr()
       assert "EC-3" in captured.err or "pipeline consumer dead" in captured.err

## Success criteria
uv run pytest green (all existing + new EC-3 test). uv run ruff check . clean.`,
    `task_id: ${TASK_ID}

## Checks (spec §7.3, EC-3)
1. _check_ec3_warn() present; checks p.is_alive()==False AND staleness > 2x interval.
2. _maybe_warn_ec3() throttles via _last_ec3_warn (60s window).
3. Warning message contains "EC-3" or "pipeline consumer dead".
4. _maybe_warn_ec3() called at end of liveness probe function.
5. test_ec3_warn_emits_stderr passes (asserts stderr content).
6. Full uv run pytest green; ruff clean.
## Pass criterion: EC-3 warn policy present and tested; all tests green; ruff clean.`
  );

// ---- orchestrate: A -> B -> C sequential -------------------------------------------
const _gitBase = (await agent(
  "Run: git rev-parse HEAD. Return only the 40-character SHA, nothing else.",
  { label: "git-base", phase: "M1-MCP — adapter layer + MCP surfaces + name-freeze" }
)).trim();

log("Cisterna M1 Sprint 2: M1-MCP -> M1-CLI -> M1-SELF (sequential)");

const a = await trackA();
const b = await trackB();
const c = await trackC();

phase("Audit");
const _auditVerdict = await agent(
  "task_id: " + TASK_ID + ". Audit Sprint 2 changes committed since " + _gitBase + ".\n" +
  "Run: git log " + _gitBase + "..HEAD --oneline to list commits.\n" +
  "Run: uv run pytest to confirm all tests pass.\n" +
  "Review all changed/created files against:\n" +
  "- AC-MCP-1..4, AC-NAMEFREEZE-1..4 (adapter layer)\n" +
  "- AC-CLI-1 (CLI adapter)\n" +
  "- EC-3 warn policy (self_obs.py)\n" +
  "Spec: .praxia/docs/specs/260616_cisterna-m1-telemetry-spec.md\n" +
  "Return PASS or FAIL with findings.",
  { label: "auditor", phase: "Audit", agentType: "auditor" }
);

return {
  task_id: TASK_ID,
  sprint_id: 2,
  verdicts: {
    "M1-MCP": a,
    "M1-CLI": b,
    "M1-SELF": c,
  },
  audit: _auditVerdict,
};
