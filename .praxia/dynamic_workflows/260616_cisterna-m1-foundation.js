// Sprint 1 runner — emitted by `praxia dw emit-sprint`
// Source: .praxia/sprint_plans/260616_cisterna-m1-foundation.toml
// Regenerate: praxia dw emit-sprint 260616_cisterna-m1-foundation.toml
// task_id: 260616_cisterna-m1-foundation   sprint_id: 1
//
// RACE SAFETY (memory: parallel fixers race on git-status scope checks in praxia):
//   the writing chain (A,B,C) runs STRICTLY SEQUENTIAL —
//   exactly one fixer touches the working tree at a time.

export const meta = {
  name: "260616_cisterna-m1-foundation",
  description: "Foundation chain of the M1 telemetry milestone: packaging/dependency contract, the dual-emit fan-out core, and init/self-observability. Strictly sequential (PKG -> CORE -> INIT); unblocks the parallel MCP/CLI/shadow/perf tracks in Sprint 2+.",
  phases: [
    { title: "M1-PKG — dependency contract + pyproject (DAG root)" },
    { title: "M1-CORE — fan-out core: context, Record, pipeline, exporter, public API" },
    { title: "M1-INIT — init_telemetry + self-observability (heartbeat, liveness, status)" },
  ],
};

const TASK_ID = "260616_cisterna-m1-foundation";
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

// Shared context for the writing tracks (from recon, task 260616_cisterna-m1-foundation).
const EMITTER_CTX = `Project: cisterna (greenfield Python 3.13 lib, uv/pytest/ruff). Spec is authoritative:\n.praxia/docs/specs/260616_cisterna-m1-telemetry-spec.md (v2, post-adversarial-review).\nDecision record: .praxia/docs/specs/260616_design-the-implementation-spec-for-ciste.md.\n\nArchitecture: dual-emit fan-out core (G) as keystone of the layered design. span()/event()\nbuild ONE OTel-superset Record once (record-BUILD wrapped never-raise), fan out to N\nper-exporter-isolated sinks. Default exporter = non-blocking queue->JSONL (put_nowait/\ndrop-on-full, counted drops). OTel-API-only core (trace/span IDs LOCAL-SCOPE in M1; SDK in\nan [otlp] extra). Never crash the caller; <1ms/call; off the hot path.\n\nStack rules: uv run python (never bare python); pytest; ruff. Edit only on existing files.\n`;

// ---- per-track stage helpers ---------------------------------------------
const fixer = (prompt, label, phaseName, isolation = null, context = null) => {
  const opts = { agentType: "fixer", label, phase: phaseName };
  if (isolation) opts.isolation = isolation;
  if (context) Object.assign(opts, context);
  return agent(`${prompt}\n\nWhen done, end your message with 'verdict: done' on its own line.`, opts);
};

const reviewer = (itemId, prompt, label, phaseName, isolation = null, context = null) => {
  const opts = { agentType: "reviewer", label, phase: phaseName, schema: VERDICT_SCHEMA };
  if (isolation) opts.isolation = isolation;
  if (context) Object.assign(opts, context);
  return agent(prompt, opts);
};

// Sequential implement->review with bounded NEEDS_WORK repair cycles.
async function track(itemId, phaseName, fixerPrompt, reviewerPrompt, isolation = null, context = null, reconExecutorKey = 'recon') {
  log(`[${itemId}] implement`);
  const _recon = await agent(
    `task_id: ${TASK_ID}. Run recon for: ${phaseName}. Task: ${fixerPrompt.slice(0, 500)}`,
    { label: 'recon:' + itemId, phase: phaseName, agentType: reconExecutorKey }
  );
  const _fixerPromptWithRecon = 'RECON FINDINGS:\n' + (_recon || '(no findings)') + '\n\n---\n\n' + fixerPrompt;
  const _preFixerHead = (await agent(
    'Run: git rev-parse HEAD. Return only the 40-character SHA, nothing else.',
    { label: 'head:' + itemId, phase: phaseName }
  )).trim().match(/[0-9a-f]{40}/)?.[0] || 'unknown';
  await fixer(_fixerPromptWithRecon, `fix:${itemId}`, phaseName, isolation, context);
  let _effRp = reviewerPrompt;
  if (isolation === 'worktree') {
    const _branch = (await agent(
      'Run: git branch --show-current. Return only the branch name, nothing else.',
      { label: 'branch:' + itemId, phase: phaseName }
    )).trim().match(/[a-zA-Z0-9_./-]+/)?.[0] || '';
    _effRp = reviewerPrompt + '\n\nIMPORTANT -- WORKTREE BRANCH: The fixer committed to branch ' + _branch + '. Before evaluating, run: git log main...' + _branch + ' --oneline && git diff main...' + _branch + '. Do NOT evaluate main HEAD. Review ONLY the commits on branch ' + _branch + '.';
  }
  _effRp = _effRp + '\n\nIMPORTANT — NO-COMMIT DETECTION: Before evaluating anything, run: ' +
    'git log ' + _preFixerHead + '..HEAD --oneline' +
    '\n' +
    'If the output is EMPTY (no commits since ' + _preFixerHead + '), return FAIL immediately with issue: ' +
    '"fixer made no commit — git log shows no new commits since pre-fixer HEAD ' + _preFixerHead + '". ' +
    'Do NOT evaluate file content if no commit was made.';
  let verdict = await reviewer(itemId, _effRp, `review:${itemId}`, phaseName, isolation, context);
  for (let retry = 0; retry < MAX_FIX_RETRIES && verdict && verdict.verdict === "NEEDS_WORK"; retry++) {
    log(`[${itemId}] NEEDS_WORK — repair cycle ${retry + 1}/${MAX_FIX_RETRIES}`);
    const issues = (verdict.issues || [])
      .map((i) => `- ${i.where}: ${i.problem} -> ${i.fix}`)
      .join("\n");
    await fixer(
      `${fixerPrompt}\n\nA reviewer found issues — fix exactly these, nothing else:\n${issues}`,
      `fix:${itemId}:repair:${retry}`,
      phaseName,
      isolation,
      context
    );
    verdict = await reviewer(itemId, _effRp, `review:${itemId}:re:${retry}`, phaseName, isolation, context);
  }
  return verdict;
}

// ===== TRACK A — M1-PKG — dependency contract + pyproject (DAG root) =========================
const trackA = () =>
  track(
    "M1-PKG",
    "M1-PKG — dependency contract + pyproject (DAG root)",
    `task_id: ${TASK_ID}. task_id: 260616_cisterna-m1-foundation\n\n## Objective\nResolve the dependency contract per spec §9/§13-C1 and §3 (CH-3): cisterna's core uses\nONLY opentelemetry-api; the SDK + semantic-conventions move to an optional [otlp] extra.\n\n## Changes (pyproject.toml)\nSet [project].dependencies to exactly:\n  cyclopts>=4.18.0, fastmcp>=3.4.2, opentelemetry-api>=1.42.1\nAdd [project.optional-dependencies] otlp = [\n  opentelemetry-sdk>=1.42.1, opentelemetry-semantic-conventions>=0.63b1,\n  opentelemetry-exporter-otlp-proto-grpc>=1.42.1 ]\nKeep the existing [dependency-groups] dev block.\nCreate the package skeleton dirs under src/cisterna/ per spec §2 (empty __init__.py +\npy.typed) so the package imports.\n\n## Success criteria (AC-PKG-1)\n\`uv sync\` succeeds. With no extras, \`uv run python -c "import opentelemetry.sdk"\` FAILS\nand \`uv run python -c "import opentelemetry"\` (api) succeeds. \`uv run ruff check .\` clean.\n\n\n${EMITTER_CTX}`,
    `task_id: ${TASK_ID}. task_id: 260616_cisterna-m1-foundation\n\n## Checks\n1. pyproject [project].dependencies contains opentelemetry-api but NOT opentelemetry-sdk.\n2. [project.optional-dependencies].otlp contains sdk + semantic-conventions + otlp exporter.\n3. \`uv run python -c "import opentelemetry.sdk"\` exits non-zero (sdk not in default env).\n4. \`uv run python -c "import opentelemetry"\` exits 0.\n5. src/cisterna/ skeleton imports (\`uv run python -c "import cisterna"\`).\n## Pass criterion: AC-PKG-1 holds; ruff clean.\n`,
    null,
    null
    , "recon"
  );

// ===== TRACK B — M1-CORE — fan-out core: context, Record, pipeline, exporter, public API =========================
const trackB = () =>
  track(
    "M1-CORE",
    "M1-CORE — fan-out core: context, Record, pipeline, exporter, public API",
    `task_id: ${TASK_ID}. task_id: 260616_cisterna-m1-foundation\n\n## Objective\nBuild the keystone per spec §3 (3.1-3.5), §2 module layout. Files:\n- cisterna/telemetry/context.py: ContextVar objects (run_uuid_var, mcp_request_id_var,\n  task_id_var, request_id_var, session_id_var, phase_var) + _build_record(name, ts, **fields)\n  that SNAPSHOTS contextvars on the producer thread (CH-4). Never-raise: returns a degraded\n  record (or None) on any exception in record-build (CH-5/EC-2 — wrap the BUILD step).\n- cisterna/telemetry/record.py: frozen slots Record dataclass (spec §3.3).\n- cisterna/telemetry/exporter.py: ExporterBase ABC (export/flush/close, all never-raise);\n  JsonlExporter (bounded queue, put_nowait -> drop -> counted _drop_count, QueueListener ->\n  RotatingFileHandler, file events.<host>.<pid>.jsonl; NEVER reads ContextVars — CH-4);\n  ShadowExporter spy.\n- cisterna/telemetry/pipeline.py: EventPipeline (fan-out: _fanout delivers to each exporter\n  in its own try/except so one raising exporter can't crash the caller or starve others).\n  Module docstring documents the fork prohibition (C9: spawn required, fork unsupported).\n- cisterna/telemetry/span.py: span()/aspan() context managers that emit <name>.start/.end\n  and RE-RAISE caller exceptions after recording status=ERROR (CH-5, intentional).\n- cisterna/__init__.py: export emit_event, span, aspan, init, status.\nEdit only on existing files; create the new modules.\n\n## Success criteria (AC-CORE-1..5, AC-JSONL drop/omit-if-None)\nAll AC-CORE tests pass: emit_event writes JSONL within 100ms; two exporters both receive\none record; contextvar snapshot round-trips (incl. async-task isolation); idempotent init;\na raising exporter is swallowed; non-serializable field never propagates. \`uv run pytest\`\ngreen for tests/test_core.py + tests/test_jsonl_exporter.py. ruff clean.\n\n\n${EMITTER_CTX}`,
    `task_id: ${TASK_ID}. task_id: 260616_cisterna-m1-foundation\n\n## Checks (against spec §3 + §8 ACs)\n1. _build_record snapshots contextvars on the CALLING thread; JsonlExporter never reads any\n   ContextVar (grep for *_var.get inside exporter.py -> must be absent). (CH-4)\n2. record-BUILD is wrapped never-raise (feed a non-serializable field; no exception escapes). (EC-2)\n3. JsonlExporter uses put_nowait + counted drop; file is events.<host>.<pid>.jsonl. (CH-9/AC-JSONL)\n4. span()/aspan() RE-RAISE caller exceptions after emitting .end with status=ERROR. (CH-5)\n5. _fanout isolates each exporter in try/except (a raising exporter doesn't starve peers). (AC-CORE-1)\n6. \`uv run pytest tests/test_core.py tests/test_jsonl_exporter.py\` green; ruff clean.\n## Pass criterion: AC-CORE-1..5 pass; CH-4/CH-5/EC-2 invariants verified in code.\n`,
    null,
    null
    , "recon"
  );

// ===== TRACK C — M1-INIT — init_telemetry + self-observability (heartbeat, liveness, status) =========================
const trackC = () =>
  track(
    "M1-INIT",
    "M1-INIT — init_telemetry + self-observability (heartbeat, liveness, status)",
    `task_id: ${TASK_ID}. task_id: 260616_cisterna-m1-foundation\n\n## Objective\nBuild init + self-observability per spec §3.2, §7, §3.4 init resolution.\n- cisterna init()/init_telemetry: idempotent (exactly one QueueListener — AC-CORE-5);\n  log_dir env resolution CISTERNA_LOG_DIR > BTH_LOG_DIR > CTXP_LOG_DIR > ~/.cisterna/logs;\n  install-time write-probe (fall back to tempdir on failure).\n- cisterna/telemetry/self_obs.py: status() -> StatusReport (pipeline_alive, queue_depth,\n  events_emitted, events_exported, drop_count, heartbeat_alive, write_probe_ok); heartbeat\n  daemon thread emitting "heartbeat" events; LIVENESS via CONSUMER-SIDE evidence — record the\n  JSONL output file mtime+size at each heartbeat and confirm they advance; a dead QueueListener\n  must be detectable (heartbeat_alive=False) within 2x the interval (CH-12, EC-3 home).\n\n## Success criteria (AC-SELFCHECK-1, AC-SELFCHECK-2, AC-CORE-5)\nHeartbeat fires; status().heartbeat_alive AND write_probe_ok True when the file grows; with\nthe QueueListener killed, status().pipeline_alive AND heartbeat_alive go False within 2x the\ninterval. Double init() leaves exactly one listener. \`uv run pytest tests/test_selfcheck.py\`\ngreen; ruff clean.\n\n\n${EMITTER_CTX}`,
    `task_id: ${TASK_ID}. task_id: 260616_cisterna-m1-foundation\n\n## Checks (spec §7 + §8)\n1. heartbeat_alive/write_probe_ok derive from output-file mtime+size advancing, NOT merely\n   that a heartbeat was enqueued (CH-12). Kill the listener -> both go False.\n2. log_dir env resolution order matches spec §3.4; write-probe falls back to tempdir.\n3. init() idempotent: exactly one QueueListener after two calls (AC-CORE-5).\n4. \`uv run pytest tests/test_selfcheck.py\` green; ruff clean.\n## Pass criterion: AC-SELFCHECK-1/2 + AC-CORE-5 pass; dead-listener detectable.\n`,
    null,
    null
    , "recon"
  );

// ---- orchestrate: writing chain (A -> B -> C, sequential) ----
const _gitBase = (await agent(
  'Run: git rev-parse HEAD. Return only the 40-character SHA, nothing else.',
  { label: 'git-base', phase: 'Execute' }
)).trim();
log("Cisterna M1 — Telemetry Foundation: writing chain (A -> B -> C, sequential)");
const a = await trackA();
// Log track completion via transduction_log
await agent(
  `task_id: ${TASK_ID}. ` +
  `Call mcp__praxia__transduction_log(action='append_audit', payload={` +
  `audit_id: '${TASK_ID}-track-a', ` +
  `task_id: '${TASK_ID}', ` +
  `verdict: '${a?.verdict ?? 'unknown'}', ` +
  `issues: []` +
  `}). ` +
  `This is a telemetry call — execute it and return 'logged'.`,
  { label: 'transduction-log:track-a', phase: 'Telemetry' }
);

const b = await trackB();
// Log track completion via transduction_log
await agent(
  `task_id: ${TASK_ID}. ` +
  `Call mcp__praxia__transduction_log(action='append_audit', payload={` +
  `audit_id: '${TASK_ID}-track-b', ` +
  `task_id: '${TASK_ID}', ` +
  `verdict: '${b?.verdict ?? 'unknown'}', ` +
  `issues: []` +
  `}). ` +
  `This is a telemetry call — execute it and return 'logged'.`,
  { label: 'transduction-log:track-b', phase: 'Telemetry' }
);

const c = await trackC();
// Log track completion via transduction_log
await agent(
  `task_id: ${TASK_ID}. ` +
  `Call mcp__praxia__transduction_log(action='append_audit', payload={` +
  `audit_id: '${TASK_ID}-track-c', ` +
  `task_id: '${TASK_ID}', ` +
  `verdict: '${c?.verdict ?? 'unknown'}', ` +
  `issues: []` +
  `}). ` +
  `This is a telemetry call — execute it and return 'logged'.`,
  { label: 'transduction-log:track-c', phase: 'Telemetry' }
);


phase("Audit");
const _auditVerdict = await agent(
  'task_id: ' + TASK_ID + '. Audit sprint ' + TASK_ID + ' changes committed since ' + _gitBase + '. Run: git log ' + _gitBase + '..HEAD --oneline to list commits. Review all changed files against the sprint requirements and return PASS or FAIL with findings.',
  { label: 'auditor', phase: 'Audit', agentType: 'auditor' }
);

// Log sprint completion via transduction_log
await agent(
  `task_id: ${TASK_ID}. ` +
  `Call mcp__praxia__transduction_log(action='append_audit', payload={` +
  `audit_id: '${TASK_ID}-final', ` +
  `task_id: '${TASK_ID}', ` +
  `verdict: '${_auditVerdict?.verdict ?? 'unknown'}', ` +
  `issues: []` +
  `}). ` +
  `This is a telemetry call — execute it and return 'logged'.`,
  { label: 'transduction-log:final', phase: 'Telemetry' }
);

return {
  task_id: TASK_ID,
  sprint_id: 1,
  verdicts: {
    "M1-PKG": a,
    "M1-CORE": b,
    "M1-INIT": c
  },
  audit: _auditVerdict,
};
