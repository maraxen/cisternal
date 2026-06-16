---
title: Cisterna Milestone 1 — Telemetry Core
version: 2 (post-adversarial-review)
date: 260616
status: draft
task_id: 260616_cisterna-m1-telemetry
---

## Changelog vs v1 (spec-challenger / spec-defender adversarial pass)

- CH-1: Corrected FastMCP v3 middleware import path (`fastmcp.server.middleware.middleware`) and `on_call_tool` signature; verified from installed source; resolves TBD-1; A2 now verified.
- CH-2: Replaced single global `v3_capable` boolean with a per-consumer surface table + fall-through semantics.
- CH-3: Moved `opentelemetry-sdk` + `opentelemetry-semantic-conventions` to `[optional-dependencies] otlp`; core keeps only `opentelemetry-api`; verbatim pyproject in §9; removes TBD-6; adds `M1-PKG` DAG node.
- CH-4: Replaced exporter-side `ContextVarCaptureQueueHandler` with `cisterna/telemetry/context.py` owning all ContextVars; `_build_record()` snapshots on the producer thread; exporter thread never reads contextvars.
- CH-5: Reconciled never-raise contract: `span()`/`aspan()` re-raise (timing primitive); MCP wrappers catch + return shaped envelope via `AdapterBase.shape_ok`/`shape_error`.
- CH-6: AdapterBase owns return shape (Bathos→dict, Xperiri→JSON str); M1-gated adapters = bathos + contemplex + CLI; xperiri/myxcel are M1.5 nodes; arg_keys parity caveat documented.
- CH-7: AC-PERF split into producer fan-out + async middleware overhead benchmarks with per-path <1ms thresholds and load conditions.
- CH-8: Shadow `capture_legacy` attaches a stdlib `logging.Handler` to the consumer's logger; spy `ShadowExporter` for cisterna; resolves TBD-4.
- CH-9: Name-freeze adds runtime guard (`ALLOWED_NAMES` per adapter) alongside the AST lint; adds AC-NAMEFREEZE-4.
- CH-10: AC-MCP-4 reproduction fixed to split Token set/reset across contexts so the `ValueError` actually fires.
- CH-11: DAG gains root `M1-PKG`, edges `M1-INIT -> M1-MCP` / `M1-INIT -> M1-CLI`, and EC-3 mitigation home on `M1-SELF`.
- CH-12: `status().heartbeat_alive` / `write_probe_ok` use consumer-side output-file mtime/size evidence so a dead QueueListener is detectable.
- CH-13: Added constraint C9 (fork prohibition; spawn required for per-pid file naming).
- TBD-1/TBD-4/TBD-6 resolved & removed; TBD-2/TBD-3/TBD-5 remain.

---

# Specification: Cisterna Milestone 1 — Telemetry Core

> Companion to the brainstorm decision record `260616_design-the-implementation-spec-for-ciste.md` (contemplex session ebe8a940), which holds the frame, idea pool, full decision log, and pre-mortem. This document is the buildable implementation spec derived from it.

## 1. Overview and Scope

Cisterna is a shared telemetry substrate for the praxia tool family (bathos, contemplex, xperiri, myxcel). Milestone 1 delivers the core event pipeline, a consumer-agnostic adapter protocol, integration surfaces for two consumers (bathos v3-middleware; contemplex v2-decorator/sync), one Typer CLI adapter, self-observability, and a shadow-harness parity test that verifies cisterna output matches each consumer's existing telemetry before cutover.

**What M1 does not include:** active cutover of any consumer (bathos/contemplex remain on their own telemetry until M2); xperiri and myxcel adapters (M1.5); OTLP export (optional extras only).

## 2. Module Layout

```
cisterna/
  __init__.py               # exports: emit_event, span, aspan, init, status
  telemetry/
    __init__.py
    context.py              # (CH-4) owns all ContextVar objects; _build_record() snapshots here
    record.py               # Record dataclass
    pipeline.py             # EventPipeline: fan-out queue, QueueListener, drain
    exporter.py             # ExporterBase ABC; JsonlExporter; ShadowExporter (test spy)
    span.py                 # span() / aspan() context managers (re-raise on caller exception)
    self_obs.py             # status() -> StatusReport; heartbeat; liveness probe
  adapters/
    __init__.py
    base.py                 # AdapterBase: shape_ok(), shape_error(); ALLOWED_NAMES frozenset
    v3_middleware.py        # CisternaMiddleware(Middleware) — FastMCP v3
    v2_decorator.py         # traced_tool decorator — FastMCP v2 / sync
    cli.py                  # Typer CLI timing decorator / context-manager
  probe/
    capability_probe.py     # per-consumer surface selection; try-import logic
  py.typed
```

## 3. Public API

### 3.1 cisterna/telemetry/context.py (CH-4)

Owns every ContextVar. `_build_record()` runs on the producer thread (the thread calling `emit_event`), snapshotting values before enqueue.

```python
from contextvars import ContextVar

run_uuid_var:       ContextVar[str | None] = ContextVar("cisterna.run_uuid",       default=None)
mcp_request_id_var: ContextVar[str | None] = ContextVar("cisterna.mcp_request_id", default=None)
task_id_var:        ContextVar[str | None] = ContextVar("cisterna.task_id",        default=None)
request_id_var:     ContextVar[str | None] = ContextVar("cisterna.request_id",     default=None)
session_id_var:     ContextVar[str | None] = ContextVar("cisterna.session_id",     default=None)
phase_var:          ContextVar[str | None] = ContextVar("cisterna.phase",          default=None)

def _build_record(name: str, ts: float, **fields) -> "Record":
    """Snapshot contextvars on the CALLING (producer) thread at build time."""
    return Record(
        name=name, ts=ts,
        run_uuid=run_uuid_var.get(), mcp_request_id=mcp_request_id_var.get(),
        task_id=task_id_var.get(), request_id=request_id_var.get(),
        session_id=session_id_var.get(), phase=phase_var.get(),
        fields=fields,
    )
```

The exporter thread (QueueListener consumer) only serializes an already-complete `Record`; it never reads any ContextVar.

### 3.2 cisterna/__init__.py — top-level API

```python
def init(log_dir: str | Path | None = None, max_bytes: int = 10_485_760,
         backup_count: int = 5, exporters: list[ExporterBase] | None = None) -> None: ...
def emit_event(name: str, **fields: Any) -> None: ...
@contextmanager
def span(name: str, **fields: Any) -> Iterator[None]: ...
@asynccontextmanager
async def aspan(name: str, **fields: Any) -> AsyncIterator[None]: ...
def status() -> StatusReport: ...
```

### 3.3 Record dataclass

```python
@dataclass(frozen=True, slots=True)
class Record:
    name: str
    ts: float                 # time.time() on producer thread
    run_uuid: str | None
    mcp_request_id: str | None
    task_id: str | None
    request_id: str | None
    session_id: str | None
    phase: str | None
    fields: dict[str, Any]
```

### 3.4 ExporterBase and JsonlExporter

```python
class ExporterBase(ABC):
    @abstractmethod
    def export(self, record: Record) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...

class JsonlExporter(ExporterBase):
    """Serializes a complete Record to JSONL. Never reads ContextVars (CH-4)."""
    def __init__(self, path: Path, max_bytes: int, backup_count: int) -> None: ...
    def export(self, record: Record) -> None: ...  # thread-safe write
```

`ShadowExporter` (test spy): collects `Record` objects into `self.records: list[Record]`.

### 3.5 span() / aspan() — re-raise contract (CH-5)

Generic timing primitives. On caller exception: record `status=ERROR, exc_type, exc_msg`, then **re-raise unconditionally**. Mirrors `bathos.telemetry.span`.

```python
@contextmanager
def span(name: str, **fields: Any) -> Iterator[None]:
    span_id = uuid.uuid4().hex
    t0 = time.monotonic_ns()
    emit_event(f"{name}.start", span_id=span_id, **fields)
    try:
        yield
        emit_event(f"{name}.end", span_id=span_id, duration_ms=(time.monotonic_ns()-t0)/1e6, ok=True)
    except Exception as exc:
        emit_event(f"{name}.end", span_id=span_id, duration_ms=(time.monotonic_ns()-t0)/1e6,
                   ok=False, exc_type=type(exc).__name__, exc_msg=str(exc))
        raise   # intentional — span() is a timing primitive, not a shield
```

### 3.6 AdapterBase (CH-5 / CH-6)

```python
class AdapterBase(ABC):
    ALLOWED_NAMES: frozenset[str]   # (CH-9) runtime name guard; subclass must define

    def emit_start(self, tool_name: str, arg_keys: list[str], request_id: str) -> None:
        name = "mcp.call_start"
        assert name in self.ALLOWED_NAMES or self._swallow_name_error(name)
        emit_event(name, tool=tool_name, arg_keys=arg_keys, request_id=request_id)
    def emit_end(self, tool_name: str, request_id: str, duration_ms: float) -> None: ...
    def emit_error(self, tool_name: str, request_id: str, exc: BaseException) -> None: ...

    @abstractmethod
    def shape_ok(self, tool_name: str, result: Any) -> Any:
        """Shaped success response. BathosAdapter -> dict; XpeririAdapter -> JSON str."""
    @abstractmethod
    def shape_error(self, tool_name: str, exc: BaseException, **fields: Any) -> Any:
        """Shaped error response (never re-raise). BathosAdapter -> dict; XpeririAdapter -> JSON str."""

    def _swallow_name_error(self, name: str) -> bool:
        import sys
        print(f"[cisterna] ILLEGAL event name: {name!r}", file=sys.stderr)
        return True  # tests monkeypatch this to raise
```

### 3.7 CisternaMiddleware — FastMCP v3 (CH-1)

Verified import path: `fastmcp/server/middleware/middleware.py`. `MiddlewareContext.message` is `mt.CallToolRequestParams` with `.name: str` and `.arguments: dict|None`; `on_call_tool` fires only for `tools/call`.

```python
from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext

class CisternaMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
        arguments = context.message.arguments or {}
        arg_keys = sorted(arguments.keys())       # (CH-6) only client-supplied keys here
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
            return adapter.shape_error(tool_name, exc)   # (CH-5) never re-raise
        finally:
            try:
                mcp_request_id_var.reset(token)
            except ValueError:
                pass   # (AC-MCP-4) token created in a different context; swallow
```

Wired via `server.add_middleware(CisternaMiddleware())`.

### 3.8 traced_tool — FastMCP v2 / sync (CH-5 / CH-6)

```python
def traced_tool(adapter: AdapterBase):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            request_id = uuid.uuid4().hex
            token = mcp_request_id_var.set(request_id)
            arg_keys = sorted(kwargs.keys())     # (CH-6) sees all declared params (parity caveat)
            adapter.emit_start(fn.__name__, arg_keys, request_id)
            t0 = time.monotonic_ns()
            try:
                result = fn(*args, **kwargs)
                adapter.emit_end(fn.__name__, request_id, (time.monotonic_ns()-t0)/1e6)
                return adapter.shape_ok(fn.__name__, result)
            except Exception as exc:
                adapter.emit_error(fn.__name__, request_id, exc)
                return adapter.shape_error(fn.__name__, exc)   # never re-raise (CH-5)
            finally:
                try:
                    mcp_request_id_var.reset(token)
                except ValueError:
                    pass   # (AC-MCP-4)
        return wrapper
    return decorator
```

**Parity caveat (CH-6):** v3 `arg_keys` = client-supplied args only; v2 `arg_keys` = all declared params incl. defaults. Documented; no code fix in M1.

## 4. Event Schema and Name Freeze

### 4.1 Canonical event names (frozen at M1)

```
mcp.call_start   mcp.call_end   mcp.tool_error   cli.cmd_start   cli.cmd_end   heartbeat
```

### 4.2 Per-adapter ALLOWED_NAMES (CH-9)

```python
class BathosAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
class ContemplexAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
class CliAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"cli.cmd_start", "cli.cmd_end"})
```

### 4.3 Name-freeze lint (CH-9)

AST lint in `tests/test_namefreeze.py` walks `cisterna/adapters/*.py` and asserts every string literal passed to `emit_event()` is in that file's allowed set. Covers cisterna's own adapters only (not consumer code).

### 4.4 Runtime guard (CH-9)

`emit_start/end/error` assert the emitted name is in `self.ALLOWED_NAMES`. Tests: raise `AssertionError`; production: stderr + continue.

## 5. Integration Seams

### 5.1 Per-consumer surface table (CH-2)

| Consumer | FastMCP | Surface | Return shape | M1 scope |
|---|---|---|---|---|
| bathos | >=3.4.2 (v3) | CisternaMiddleware via add_middleware() | dict envelope | M1-gated |
| contemplex | v2 sync @mcp.tool() | traced_tool v2 decorator | dict envelope | M1-gated |
| myxcel | fastmcp>=0.4 (v2) | traced_tool v2 decorator | dict envelope | M1.5 |
| xperiri | v2 sync, JSON-string return | traced_tool v2 decorator | JSON str | M1.5 |

Fall-through: if `hasattr(server,'add_middleware')` is False on a bathos server, probe warns and falls back to v2 decorator. M1.5 consumers' adapters are not loaded in M1.

### 5.2 Capability probe (CH-1 / CH-2)

```python
def _has_v3_middleware() -> bool:
    try:
        from fastmcp.server.middleware.middleware import Middleware  # noqa: F401
        return True
    except ImportError:
        return False

CONSUMER_SURFACE: dict[str, str] = {
    "bathos":     "v3_middleware" if _has_v3_middleware() else "v2_decorator",
    "contemplex": "v2_decorator",
    "myxcel":     "v2_decorator",
    "xperiri":    "v2_decorator",
}
def surface_for(consumer: str) -> str:
    return CONSUMER_SURFACE.get(consumer, "v2_decorator")
```

### 5.3 Never-raise invariant (CH-5) — stated once

> Telemetry instrumentation never raises into the caller. Instrumented code's own exceptions are handled per-path:
> - `span()`/`aspan()` record status=ERROR then **re-raise** (generic timing primitives).
> - `CisternaMiddleware.on_call_tool` and `traced_tool` v2 **catch** the tool exception, emit `mcp.tool_error`, and **return a shaped error envelope** via `adapter.shape_error()` — never re-raise to transport. Matches `bathos.mcp.traced_tool` (never re-raises) and `contemplex.mcp_server.traced_tool` (returns `err_envelope`).

### 5.4 Adapter shape_ok / shape_error

```python
class BathosAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
    def shape_ok(self, tool_name, result):
        if isinstance(result, dict):
            return {**result, "ok": True, "error_code": None, "error": None, "resolution_hint": None}
        return {"ok": True, "error_code": None, "error": None, "resolution_hint": None}
    def shape_error(self, tool_name, exc, **fields):
        return {"ok": False, "error_code": "INTERNAL", "error": str(exc), "resolution_hint": ""}

class ContemplexAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
    def shape_ok(self, tool_name, result): return result
    def shape_error(self, tool_name, exc, **fields):
        from contemplex.errors import ErrorCode, err_envelope
        return err_envelope(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}")

# M1.5
class XpeririAdapter(AdapterBase):
    ALLOWED_NAMES = frozenset({"mcp.call_start", "mcp.call_end", "mcp.tool_error"})
    def shape_ok(self, tool_name, result):
        return result if isinstance(result, str) else json.dumps(result)
    def shape_error(self, tool_name, exc, **fields):
        return json.dumps({"error": str(exc), "ok": False})
```

## 6. Shadow Harness (CH-8) — resolves TBD-4

### 6.1 capture_legacy — non-invasive stdlib logging attachment

```python
def capture_legacy(consumer: str) -> ContextManager[list[logging.LogRecord]]:
    """Attach a logging.Handler to the consumer's existing telemetry logger for the
    shadow window; detach after (non-invasive). Logger names verified from source:
      bathos -> "bathos"; contemplex -> "contemplex".
    """
```

A `MemoryHandler`/list-appender is added via `logging.getLogger("bathos").addHandler(spy)` and removed after the window.

### 6.2 capture_cisterna — spy ShadowExporter

```python
class ShadowExporter(ExporterBase):
    def __init__(self) -> None: self.records: list[Record] = []
    def export(self, record: Record) -> None: self.records.append(record)
```

### 6.3 Parity assertion

```python
def assert_parity(legacy: list[logging.LogRecord], cisterna: list[Record]) -> None:
    assert len(legacy) == len(cisterna)
    for lr, cr in zip(legacy, cisterna):
        assert lr.getMessage()["tool"] == cr.fields["tool"]
        assert abs(lr.getMessage()["duration_ms"] - cr.fields["duration_ms"]) < 5.0
```

Parity = field-subset equality modulo {ε-timestamp (5ms tolerance), additive trace columns, ordering by (event, request_id)}.

## 7. Self-Observability (CH-12 / CH-11)

### 7.1 StatusReport

```python
@dataclass
class StatusReport:
    pipeline_alive: bool        # QueueListener thread is_alive()
    queue_depth: int
    events_emitted: int         # producer-side counter
    events_exported: int        # exporter-side counter
    drop_count: int
    heartbeat_alive: bool       # (CH-12) consumer-side evidence (see 7.2)
    write_probe_ok: bool        # (CH-12) last heartbeat caused output file to grow
def status() -> StatusReport: ...
```

### 7.2 Liveness: consumer-side evidence (CH-12)

`heartbeat_alive` / `write_probe_ok` are determined by consumer-side evidence, not merely that a heartbeat was enqueued. `self_obs.py` records the JsonlExporter output file's mtime+size at each heartbeat enqueue; on the next heartbeat it re-stats. If mtime advanced AND size grew, both flags are True. If neither advances within 2x the heartbeat interval, a dead QueueListener (EC-3) is detected.

### 7.3 EC-3 mitigation home (CH-11)

QueueListener-death detection/restart logic lives in `M1-SELF`. If `pipeline_alive` is False and `heartbeat_alive` is False, policy (warn-and-continue vs auto-restart) is decided in M1-SELF.

## 8. Acceptance Criteria

### AC-CORE
- AC-CORE-1: Given init() with temp log dir; When `emit_event("mcp.call_start", tool="t", request_id="r")`; Then a JSONL line with that name+fields appears within 100ms.
- AC-CORE-2: Given JsonlExporter + ShadowExporter registered; When one emit_event; Then both the file contains the record AND ShadowExporter.records has length 1.
- AC-CORE-3: Given `run_uuid_var.set("uuid-x")` then emit_event("e"); When read back; Then line contains `"run_uuid":"uuid-x"`.
- AC-CORE-4: Given a second asyncio Task sets `run_uuid_var.set("uuid-y")` and emits; Then that line carries uuid-y (context isolation).
- AC-CORE-5: Given init() called twice; When status(); Then exactly one QueueListener thread (idempotent init).

### AC-MCP
- AC-MCP-1: Given CisternaMiddleware on a v3 server; When a tool is called; Then mcp.call_start+mcp.call_end appear, tool matches, arg_keys is sorted client keys.
- AC-MCP-2: Given traced_tool(ContemplexAdapter()) on a sync tool; When it returns; Then start+end appear, arg_keys sorted kwargs.
- AC-MCP-3 (CH-5): Given a v3 tool raises RuntimeError; Then mcp.tool_error emitted AND a shaped error envelope returned (ok=False), not re-raised.
- AC-MCP-3b: Given a v2 sync tool raises ValueError; Then mcp.tool_error emitted AND err_envelope returned; no exception escapes.
- AC-MCP-4 (CH-10): Given a Token set in the outer context; When `copy_context().run(lambda: mcp_request_id_var.reset(tok))` runs inside on_call_tool (different Context copy); Then reset() raises ValueError and the wrapper's `except ValueError: pass` swallows it; nothing propagates.

### AC-NAMEFREEZE
- AC-NAMEFREEZE-1: AST lint asserts every emit_event name in v3_middleware.py is in the allowed set.
- AC-NAMEFREEZE-2: Adding `"mcp.call_begin"` makes the lint fail with a clear message.
- AC-NAMEFREEZE-3: Lint covers cisterna's own adapters only (not consumer code).
- AC-NAMEFREEZE-4 (CH-9): With the test monkeypatch of `_swallow_name_error`, an out-of-set name raises AssertionError (runtime guard).

### AC-PERF (CH-7)
- AC-PERF-1a: Given 2 exporters, queue empty; When emit_event x1000; Then median per-call < 1ms (enqueue only).
- AC-PERF-1b: Given CisternaMiddleware, mock call_next returns immediately, queue empty; When 500 on_call_tool awaits; Then median overhead < 1ms.
- AC-PERF-1c: Given queue capacity 10, 100 events before drain; Then status().drop_count >= 90 and no exception raised.

### AC-SHADOW
- AC-SHADOW-1: Given bathos legacy telemetry + cisterna shadow active; When list_runs_tool called; Then capture_legacy("bathos") and capture_cisterna each captured >=1 matching record; parity passes.
- AC-SHADOW-2: Given contemplex brainstorm_start in the shadow window; Then same start->end ordering in both streams.

### AC-SELFCHECK
- AC-SELFCHECK-1 (CH-12): Given JsonlExporter to temp file, heartbeats every 50ms; When status() after 150ms; Then heartbeat_alive AND write_probe_ok are True (file mtime advanced + size grew).
- AC-SELFCHECK-2 (CH-12): Given the QueueListener thread killed; When status() after 2x interval; Then pipeline_alive False AND heartbeat_alive False.

### AC-CLI
- AC-CLI-1: Given a Typer command decorated with CliAdapter; When it runs and exits cleanly; Then cli.cmd_start+cli.cmd_end records appear.

### AC-PKG (CH-3)
- AC-PKG-1: Given pyproject has otel-sdk + semconv in [optional-dependencies] otlp only; When `uv pip install cisterna` (no extras); Then `import opentelemetry.sdk` fails and `import opentelemetry.api` succeeds.

## 9. Dependency Contract (CH-3) — resolves TBD-6

```toml
[project]
name = "cisterna"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "cyclopts>=4.18.0",
    "fastmcp>=3.4.2",
    "opentelemetry-api>=1.42.1",
]

[project.optional-dependencies]
otlp = [
    "opentelemetry-sdk>=1.42.1",
    "opentelemetry-semantic-conventions>=0.63b1",
    "opentelemetry-exporter-otlp-proto-grpc>=1.42.1",
]

[dependency-groups]
dev = ["pytest>=9.0.3", "pytest-cov>=7.1.0", "ruff>=0.15.17", "ty>=0.0.49"]
```

Core uses only `opentelemetry-api`; SDK + semconv are needed only for OTLP export (optional extra), keeping the default install footprint minimal.

## 10. Backlog DAG (CH-11)

```
M1-PKG  Resolve dependency contract; edit pyproject (§9 verbatim). Gate: AC-PKG-1.
   |
   v
M1-CORE  context.py (CH-4), record.py, pipeline.py, exporter.py, __init__.py
         (emit_event/span/aspan/init/status). Gate: AC-CORE-1..5.
   |
   v
M1-INIT  self_obs.py (heartbeat, liveness, EC-3 policy). depends M1-CORE.
   |--> M1-MCP   adapters/base.py (AdapterBase shape_ok/shape_error),
   |             adapters/v3_middleware.py, adapters/v2_decorator.py,
   |             probe/capability_probe.py. depends M1-INIT.
   |             Gate: AC-MCP-1..4, AC-NAMEFREEZE-1..4.
   |--> M1-CLI   adapters/cli.py (Typer). depends M1-INIT. Gate: AC-CLI-1.
   |
M1-SELF   liveness wire-up (CH-12), EC-3 restart policy. depends M1-INIT.
          Gate: AC-SELFCHECK-1, AC-SELFCHECK-2.
M1-SHADOW tests/shadow/{bathos,contemplex}. depends M1-MCP. Gate: AC-SHADOW-1,2.
M1-PERF   tests/perf. depends M1-MCP. Gate: AC-PERF-1a,1b,1c.

--- M1.5 ---
M1.5-XPERIRI  XpeririAdapter (JSON-str returns). depends M1-MCP.
M1.5-MYXCEL   MyxcelAdapter (v2 path). depends M1-MCP.
--- M2 ---
M2-OTLP   opentelemetry-sdk extra + OTLP exporter + ReadableSpan->Record bridge.
M2-PROP   cross-process trace-context propagation (traceparent inject).
```

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| R1 v3 middleware API drift in a minor release | Medium | Pin fastmcp>=3.4.2,<4; pin probe import to the module path |
| R2 Consumer switches v3<->v2 between shadow and cutover | Medium | Re-run probe each session; log probe result |
| R3 ContextVar set after the snapshot point is missed | Low | Document: set contextvars before emit_event (same contract as bathos) |
| R4 QueueListener thread dies silently | High | EC-3 mitigation in M1-SELF; consumer-side liveness (§7.2) detects within 2x interval |
| R5 JSON serialization of exotic field types crashes exporter | Medium | export() try/except; on error write a tombstone record with exc_type |
| R6 Shadow timing race | Low | Assert by counts+ordering, not exact timestamps; 5ms tolerance |
| EC-1 Queue unbounded growth under listener lag | Medium | Bounded queue + drop-on-full; status().drop_count observable |
| EC-2 atexit drain races with process kill | Low | shutdown() 2s timeout drain then force-stop |
| EC-3 QueueListener death | High | Consumer-side liveness (§7.2); mitigation in M1-SELF |
| UM-1 Wrong logger name in shadow capture | Low | Logger names verified: bathos="bathos", contemplex="contemplex" |
| UM-2 Multiple init() leave duplicate listeners | Low | Idempotent init (AC-CORE-5); teardown fixture shutdown() |

## 12. Assumptions

| ID | Assumption | Status |
|---|---|---|
| A1 | v3 middleware importable via `fastmcp.server.middleware.middleware` | Verified (source) |
| A2 | on_call_tool gets MiddlewareContext; context.message.name/.arguments(dict|None); fires only for tools/call | Verified (dispatch + mcp/types.py CallToolRequestParams) |
| A3 | bathos traced_tool never re-raises (returns shaped envelope) | Verified (bathos/mcp.py) |
| A4 | contemplex traced_tool is sync; returns err_envelope | Verified (contemplex/mcp_server.py) |
| A5 | xperiri tools return JSON strings | Verified (xperiri/mcp_server.py) |
| A6 | Python >=3.13 | pyproject |
| A7 | spawn required for per-pid naming; fork unsupported (C9) | Carried from bathos fork-prohibition |

## 13. Constraints

| ID | Constraint |
|---|---|
| C1 | Core must not import opentelemetry.sdk / semantic_conventions at module level (otlp extra only) |
| C2 | emit_event() must not block beyond enqueue latency (<1ms hot path) |
| C3 | JsonlExporter must be thread-safe (internal lock) |
| C4 | Exporter thread must never read ContextVars; values arrive via Record fields populated on the producer thread |
| C5 | span()/aspan() re-raise after recording status=ERROR (intentional) |
| C6 | MCP wrappers never re-raise tool exceptions to transport; return shaped envelopes |
| C7 | Envelope contents are consumer-specific via AdapterBase.shape_error (Bathos->dict, Xperiri->JSON str) |
| C8 | Event-name freeze: adapters emit only ALLOWED_NAMES; AST lint (compile-time) + runtime guard |
| C9 | Fork prohibition: QueueListener does not survive os.fork. fork unsupported; spawn/forkserver supported; per-pid JSONL naming (events.<host>.<pid>.jsonl) requires spawn. Documented in pipeline.py docstring. |

## 14. TBDs (open)

| ID | Item | Note |
|---|---|---|
| TBD-2 | Whether v3 call_next wraps result (ToolResult) before on_call_tool returns, affecting shape_ok unwrapping | Needs live integration test |
| TBD-3 | Heartbeat interval default (suggest 30s; may be too slow for interactive procs) | Tune via M1-SELF load test |
| TBD-5 | Whether CTXP_LOG_DIR becomes a public env-var API | Determines doc + stability promise |

(TBD-1 resolved: v3 middleware path verified. TBD-4 resolved: shadow logger names confirmed. TBD-6 resolved: pyproject blocks in §9.)
