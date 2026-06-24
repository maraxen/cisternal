# Cisterna telemetry operator runbook

Authoritative operator guide for enabling cisterna telemetry in consumer repos,
optional OTLP egress, log inspection, and verification. Closes backlog **#2647**.

**Spec:** `.praxia/docs/specs/260624_m10-operator-runbook-for-cisterna-docume.md`

**Source of truth (code):**

| Topic | Module |
|-------|--------|
| `CISTERNA_TELEMETRY` gate | `src/cisterna/probe/telemetry_env.py` |
| JSONL log directory | `src/cisterna/telemetry/pipeline.py` (`init_pipeline`) |
| OTLP exporter | `src/cisterna/telemetry/otlp_exporter.py` |
| HPC job spans | `src/cisterna/telemetry/span.py` (`job_span`) |
| MCP tool wrapper | `src/cisterna/adapters/v2_decorator.py` (`traced_tool`) |

---

## Quick decision tree

```
Need telemetry?
├─ No  → leave CISTERNA_TELEMETRY unset (default; legacy paths in each consumer)
├─ Yes → which consumer?
│   ├─ One repo     → CISTERNA_TELEMETRY=<consumer>  (bathos|contemplex|xperiri|myxcel)
│   └─ All at once  → CISTERNA_TELEMETRY=all  (or 1|true|yes)
└─ Where should events go?
    ├─ JSONL only   → default; set log dir vars if needed (see below)
    ├─ OTLP only    → not supported alone; OTLP fans out alongside JSONL
    └─ JSONL + OTLP → set CISTERNA_OTLP_ENDPOINT (+ optional PROTOCOL); install cisterna[otlp]
```

**Invariant:** Telemetry is **never-raise** — export failures log to stderr and do not crash the host process.

---

## Environment contract

### `CISTERNA_TELEMETRY` (cutover gate)

Read by `consumer_telemetry_enabled()` and each sibling `telemetry_bridge.py`.

| Value | Effect |
|-------|--------|
| unset / empty | Telemetry **disabled** for all consumers |
| `all`, `1`, `true`, `yes` | Enabled for **every** known consumer |
| `bathos` | Enabled only for bathos |
| `contemplex` | Enabled only for contemplex |
| `xperiri` | Enabled only for xperiri |
| `myxcel` | Enabled only for myxcel |

Comparison is **case-insensitive**.

```bash
# Examples
export CISTERNA_TELEMETRY=contemplex   # single consumer
export CISTERNA_TELEMETRY=all          # enable all bridges
unset CISTERNA_TELEMETRY               # legacy telemetry only
```

### JSONL log directory

Resolved when `cisterna.init()` / `init_pipeline()` runs without an explicit `log_dir`:

| Precedence | Variable | Default if all unset |
|------------|----------|----------------------|
| 1 | `CISTERNA_LOG_DIR` | |
| 2 | `BTH_LOG_DIR` | |
| 3 | `CTXP_LOG_DIR` | |
| 4 | — | `~/.cisterna/logs` |

Sibling bridges may use their own default under `~/.local/share/<consumer>/cisterna_logs` when initializing locally — cisterna still honors the precedence above when it owns `init_pipeline`.

Rotated JSONL files are written by `JsonlExporter` (default fan-out sink).

### OTLP egress (optional)

Requires `uv pip install 'cisterna[otlp]'` or `uv sync --extra otlp` in cisterna; consumer repos typically depend on `cisterna` with the optional extra.

| Variable | Default | Notes |
|----------|---------|-------|
| `CISTERNA_OTLP_ENDPOINT` | unset (OTLP off) | Collector URL, e.g. `http://localhost:4317` |
| `CISTERNA_OTLP_PROTOCOL` | `grpc` | `grpc` or `http` / `http/protobuf` |
| `OTEL_SERVICE_NAME` | `cisterna` | OpenTelemetry resource `service.name` |

**Port callout (M7.1):**

| Protocol | Typical port | Endpoint example |
|----------|--------------|------------------|
| gRPC | **4317** | `http://localhost:4317` |
| HTTP | **4318** | `http://localhost:4318` |

Mismatching protocol and port is the most common OTLP misconfiguration.

```bash
# gRPC (default)
export CISTERNA_OTLP_ENDPOINT=http://localhost:4317
export CISTERNA_OTLP_PROTOCOL=grpc

# HTTP/protobuf
export CISTERNA_OTLP_ENDPOINT=http://localhost:4318
export CISTERNA_OTLP_PROTOCOL=http

uv sync --extra otlp   # in cisterna checkout
```

When `CISTERNA_OTLP_ENDPOINT` is set but the OpenTelemetry SDK is missing, cisterna prints a stderr warning and continues JSONL-only.

### `job_span` environment (HPC / SLURM)

Used by myxcel and bathos job paths via `cisterna.job_span()`:

| Field | Env vars (precedence) |
|-------|------------------------|
| `task_id` | explicit kwarg → `MYX_JOB_ID` → `BTH_TASK_ID` |
| `run_uuid` | explicit kwarg → `MYX_RUN_UUID` → `BTH_RUN_UUID` |

---

## Per-consumer cutover

Each consumer ships a `telemetry_bridge.py` that calls `init_server_telemetry()` at MCP startup and routes tool calls through `cisterna.traced_tool(<Adapter>())` when the flag is set.

| Consumer | Flag | Bridge module | `traced_tool` |
|----------|------|---------------|---------------|
| **bathos** | `CISTERNA_TELEMETRY=bathos` | `bathos/src/bathos/telemetry_bridge.py` | sync |
| **contemplex** | `CISTERNA_TELEMETRY=contemplex` | `contemplex/src/contemplex/telemetry_bridge.py` | sync |
| **xperiri** | `CISTERNA_TELEMETRY=xperiri` | `xperiri/src/xperiri/telemetry_bridge.py` | sync |
| **myxcel** | `CISTERNA_TELEMETRY=myxcel` | `myxcel/src/myxcel/telemetry_bridge.py` | **async** |

### Cutover checklist (per consumer)

1. Install consumer with cisterna dependency (sibling repos: `cisterna; python_version >= '3.13'` or equivalent).
2. Set `CISTERNA_TELEMETRY=<consumer>` in the MCP server environment (systemd, Cursor MCP config, SLURM job env, etc.).
3. Restart the MCP server or job runner so `init_server_telemetry()` runs.
4. Run shadow parity gate (below) before promoting to production.
5. Optional: set `CISTERNA_OTLP_*` for Grafana Tempo / Jaeger / etc.

### myxcel-specific notes

- All **19 MCP tools** are `async def`; `traced_tool` wraps them with an async-aware decorator.
- SLURM submit/run paths should use `job_span()` with `MYX_JOB_ID` / `MYX_RUN_UUID` (or bathos-compatible `BTH_*` vars) in the job environment.
- Error envelopes are dict-shaped `{error, message}` (not the bathos MCP envelope).

### xperiri-specific notes

- MCP tools return **JSON strings**; `XpeririAdapter` shapes errors for the shadow harness.
- Logger name for legacy parity: `"xperiri"`.

---

## Verification commands

Run from the **cisterna** repo root after `uv sync`.

### Operator diagnostic

```bash
uv run cisterna telemetry doctor
```

Prints effective `CISTERNA_TELEMETRY`, log directory, OTLP settings, and pipeline status.

**CI / cutover preflight** (machine-readable, fail on warnings):

```bash
uv run cisterna telemetry doctor --json --strict
# or: CISTERNA_DOCTOR_STRICT=1 uv run cisterna telemetry doctor --json
```

Set `CISTERNA_TELEMETRY` to the target consumer (or `all`) before running in a sibling repo cutover script.

### Shadow parity (required before cutover promotion)

```bash
uv run pytest tests/shadow/ -q
```

Covers bathos, contemplex, xperiri, and myxcel golden patterns.

### Per-consumer gate tests

```bash
uv run pytest tests/test_bathos_telemetry_cutover.py -q
uv run pytest tests/test_contemplex_telemetry_cutover.py -q
uv run pytest tests/test_xperiri_telemetry_cutover.py -q
uv run pytest tests/test_myxcel_telemetry_cutover.py -q
```

### Full regression suite

```bash
uv run pytest -q
```

CI runs shadow + full suite in `.github/workflows/export-dogfood.yml` (`dogfood` job).

---

## OTLP smoke (local collector)

Fixture config: `tests/fixtures/otel-collector-config.yaml` (gRPC **4317**, HTTP **4318**).

```bash
# Start collector (from cisterna repo root)
docker run -d --name cisterna-otel \
  -p 4317:4317 -p 4318:4318 \
  -v "$(pwd)/tests/fixtures/otel-collector-config.yaml:/etc/otelcol/config.yaml" \
  otel/opentelemetry-collector:0.109.0 \
  --config=/etc/otelcol/config.yaml

# Integration tests (requires collector reachable)
uv run pytest tests/test_otlp_http.py -m integration -q

# Teardown
docker rm -f cisterna-otel
```

**CI:** `export-dogfood.yml` job `otlp-collector-advisory` runs the same integration smoke with `continue-on-error: true` (advisory, not a merge blocker).

---

## JSONL query appendix

Logs are newline-delimited JSON (`Record` schema). Default path: `~/.cisterna/logs/events.jsonl` (rotated).

### jq — recent MCP tool calls

```bash
LOG=~/.cisterna/logs/events.jsonl
jq -c 'select(.name | startswith("mcp.call"))' "$LOG" | tail -20
```

### jq — errors only

```bash
jq -c 'select(.name == "mcp.tool_error")' "$LOG" | tail -20
```

### DuckDB — aggregate tool durations

```bash
duckdb -c "
  SELECT fields.tool AS tool,
         avg(cast(fields.duration_ms AS DOUBLE)) AS avg_ms,
         count(*) AS calls
  FROM read_json_auto('~/.cisterna/logs/events.jsonl')
  WHERE name = 'mcp.call_end'
  GROUP BY 1
  ORDER BY calls DESC
  LIMIT 20;
"
```

Adjust the path if `CISTERNA_LOG_DIR` or consumer-specific log dirs are used.

---

## Troubleshooting

### 1. No telemetry / empty JSONL

**Symptom:** No events file, or pipeline never initialized.

**Checks:**

- `CISTERNA_TELEMETRY` unset → cutover bridge is a no-op by design.
- Consumer MCP server not restarted after setting the flag.
- `init_server_telemetry()` not called on startup (grep consumer `main` / `mcp_server`).

### 2. OTLP SDK missing

**Symptom:** stderr message:

```text
[cisterna] CISTERNA_OTLP_ENDPOINT set but opentelemetry-sdk not installed; install cisterna[otlp]
```

**Fix:** `uv pip install 'cisterna[otlp]'` or add the `[otlp]` extra to the consumer environment. JSONL continues to work.

### 3. Wrong OTLP protocol or port

**Symptom:** Spans never arrive in collector; connection errors in collector logs.

**Fix:** Match `CISTERNA_OTLP_PROTOCOL` to the listener:

- `grpc` → port **4317**
- `http` → port **4318**

Verify with the docker smoke section above before debugging production collectors.

### 4. Shadow / gate test failures after cutover

**Symptom:** `tests/shadow/` or `test_*_telemetry_cutover.py` fails.

**Fix:** Do not flip production flags until shadow parity passes. Compare adapter envelope shaping in `src/cisterna/adapters/base.py` with the failing golden in `tests/shadow/`.

---

## Deferred (post-M10.2)

- `--consumer` filter for doctor output
- Tiered exit codes (0/1/2)
- Auto-strict when `CI=true`

---

## Related CI jobs

| Job | Workflow | Blocking? |
|-----|----------|-----------|
| `dogfood` | `export-dogfood.yml` | Yes — full pytest + shadow |
| `otlp-collector-advisory` | `export-dogfood.yml` | No (`continue-on-error: true`) |
| `native-validate` | `export-dogfood.yml` | Yes — subprocess export digest parity (`--use-native-cli`) |
