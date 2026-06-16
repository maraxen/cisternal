---
session_id: 9aed993d
topic: Design the cisterna M2 registration surface: a unified @cisterna.tool decorator that registers a plain Python function as both a FastMCP MCP tool and a Cyclopts CLI command with automatic telemetry, handling per-consumer shape adaptation
task_type: architectural
winner: B+G2-steelman hybrid: @cisterna.tool is a pure metadata marker (no wrapping at decoration time); named registries (B1); cisterna.wire(server, app, adapter, registry) generates transport-specific callables at wire time via an internal compose-then-register pipeline; E1 async/sync shim; F1 dual error contract (middleware for MCP, decorator for CLI); H1 __signature__ injection on generated callables; mandatory post-wire validation (fail-fast on import-order misses); wire() is a thin public API over internal compose()+register_mcp()+register_cli() steps
created_at: 2026-06-16T21:44:37.249413+00:00
---

# Brainstorm: Design the cisterna M2 registration surface: a unified @cisterna.tool decorator that registers a plain Python function as both a FastMCP MCP tool and a Cyclopts CLI command with automatic telemetry, handling per-consumer shape adaptation

## Problem Frame
Fixed constraints:
1. FastMCP v3 (bathos) uses server-level middleware — ALL tools on a server share one adapter; individual function decoration is additive, not the primary wiring point
2. Shape divergence is transport-required: Bathos must get {ok, error_code, error, resolution_hint}; Contemplex gets passthrough; Xperiri gets JSON string — the decorator cannot unify these into one return type
3. Cyclopts async caveat: inside FastMCP's running event loop, asyncio.run() fails — CLI invocation and MCP invocation have different execution contexts
4. Consumer identity is not known at function decoration time — it's known at server/app initialization time (which server is the function registered on?)
5. Python type annotations must be preserved for FastMCP schema generation and Cyclopts argument parsing

Negotiable:
- Whether registration is one decorator (@cisterna.tool) or a cisterna-owned server/app object that functions register into
- Whether shape adaptation happens at decoration time (separate wrapper per consumer) or at dispatch time (runtime adapter selection)
- Whether CLI and MCP registration happen via the same call or separate (but both part of cisterna's API)
- Whether M2 scope includes Cyclopts or just fixes the MCP registration surface first

## Idea Pool
- [user] Four competing approaches:
- [user] A. CisternaServer composite object — cisterna owns a FastMCP+Cyclopts composite; you do `server = cisterna.Server(); @server.tool` and cisterna internally holds both the FastMCP server and the Cyclopts App. The consumer calls `server.run_mcp()` or `server.run_cli()`.
- [user] B. Lazy registry + init-time wiring — `@cisterna.tool` marks functions in a global registry; a later `cisterna.wire(mcp_server, cli_app, adapter=BathosAdapter())` call wires all registered functions into the caller-supplied server and app at startup.
- [user] C. Consumer-namespaced decorators — `@cisterna.bathos.tool`, `@cisterna.contemplex.tool`; shape is resolved at decoration time per consumer; no runtime adapter selection needed.
- [user] D. Transparent wrapper protocol — `@cisterna.tool` wraps the function with telemetry only (no registration); the wrapped callable is then passed to the consumer's own `@mcp.tool` and `@app.command`; cisterna stays out of registration entirely.
- [user] Beginning Phase 2 probing. I will work through all four approaches using assumption-reversal, SCAMPER, and competing-faction techniques. Probing only — no evaluation.
- [user] Probing Approach A (CisternaServer composite): The assumption is that cisterna owns the server lifetime. What if the tool author's codebase already has a FastMCP server they don't control — e.g., they're adding tools to a third-party server, or server construction happens in a framework they're embedded in? A forced cisterna.Server() wrapper would be incompatible. Sub-question: does CisternaServer need to own the event loop, or can it delegate run() to an external runner?
- [ai] A1 (A variant): CisternaServer wraps an externally-supplied FastMCP server rather than constructing its own — `cisterna.Server(mcp_server=existing_server)` — so tool authors embedded in third-party frameworks can still use the composite pattern without ceding server ownership.
- [user] Still on Approach A: It assumes CLI and MCP registration always happen together on the same object. What about a tool that should be CLI-only (admin command, no network exposure) or MCP-only (long-running stream, no CLI interface)? Does `@server.tool` need per-call opt-in/opt-out flags like `mcp=True, cli=False`? And if a function is CLI-only, the Cyclopts app still needs to exist — does CisternaServer spin one up even for MCP-only deployments?
- [ai] A2 (A variant): `@server.tool` accepts per-registration transport flags — `@server.tool(mcp=True, cli=False)` — allowing selective registration into only one of the two subsystems. CisternaServer only instantiates the Cyclopts App lazily when at least one CLI-enabled tool is registered.
- [user] Probing Approach B (lazy registry + init-time wiring): The assumption is a single global registry is safe. What if the same Python process hosts multiple MCP servers targeting different consumers — e.g., a bathos server AND a contemplex server running in the same process? A global registry with one `cisterna.wire()` call cannot distinguish which tools belong to which server. Sub-question: does B require the registry to be per-module, per-package, or per-namespace to avoid cross-contamination?
- [ai] B1 (B variant): Replace the single global registry with named registries — `@cisterna.tool(registry="bathos")` — so `cisterna.wire(mcp_server, registry="bathos")` only pulls tools from that named group. Multiple servers in the same process each wire from their own registry partition.
- [user] Still on Approach B: The assumption is that `cisterna.wire()` is called after all `@cisterna.tool` decorations have run — i.e., module import order is under the caller's control. What if tools are defined in lazily-imported modules, plugins, or entry points that haven't loaded at wire() time? Does B need a deferred-wire mechanism that re-wires when new tools appear, or a plugin hook that triggers wire() on each new import?
- [ai] B2 (B variant): `cisterna.wire()` returns a live registry proxy rather than a snapshot — any tool decorated after wire() is called is automatically added to the already-wired server/app via a post-registration hook. Supports plugin systems where tools arrive after startup.
- [user] Probing Approach C (consumer-namespaced decorators): This approach assumes the tool author knows at decoration time which consumers will use the function. But constraint 4 says consumer identity is not known at decoration time. How does `@cisterna.bathos.tool` know which FastMCP server to register with? If the bathos server is constructed later, C needs either (a) a global singleton bathos server in cisterna, or (b) decoration that is still lazy — which makes it equivalent to B with a consumer-specific registry.
- [ai] C1 (C variant): Consumer-namespaced decorators are syntactic sugar over named registries (B1) — `@cisterna.bathos.tool` is `@cisterna.tool(registry="bathos", shape=BathosShape)` — so the shape is locked at decoration time but registration into the actual server still happens lazily at wire() time. The namespace is an annotation, not an eager registration.
- [user] Still on C: The premise is that shape can be resolved at decoration time because the consumer namespace is known. But what about a function that needs to appear under BOTH `@cisterna.bathos.tool` AND `@cisterna.contemplex.tool`? The same function definition can only be decorated once in normal Python unless the tool author calls it twice or uses decorator stacking. What does C do when a tool legitimately serves two consumers with different shapes? Does double-decoration create two separate wrapped functions from the same original?
- [ai] C2 (C variant): For multi-consumer tools, C allows stacked decorators — `@cisterna.bathos.tool` applied over `@cisterna.contemplex.tool` — where each decorator wraps the previous wrapper. The outermost callable is registered into its consumer; inner wrappers are stored as attributes (e.g., `fn.__cisterna_variants__`). Shape adaptation is per-wrapper, applied at call time based on which variant is invoked.
- [user] Probing Approach D (transparent wrapper): The assumption is that the consumer's registration decorators (`@mcp.tool`, `@app.command`) will coexist peacefully with cisterna's telemetry wrapper. But FastMCP reads type annotations from the function it decorates. If `@cisterna.tool` wraps the function and `functools.wraps` is used, do FastMCP's introspection hooks see the original annotations or the wrapper's? What if FastMCP uses inspect.signature() with follow_wrapped=False?
- [ai] D1 (D variant): Instead of a closure wrapper, `@cisterna.tool` injects telemetry by mutating the function in-place — attaching a `__wrapped_call__` hook via a descriptor or `__call__` replacement on the function object — so the original function object (with its original `__annotations__` and `__signature__`) is passed directly to `@mcp.tool` and `@app.command` without wrapping. Avoids all introspection breakage.
- [user] Still on D: D assumes the tool author is responsible for calling both `@mcp.tool` and `@app.command` — two registration calls instead of one. The framing says the primary user (tool author) should not need to know which consumer they're targeting. D puts full consumer-awareness burden on the author. What if D is inverted: cisterna.tool() returns a wrapped callable that, when passed to *any* MCP/CLI registration function, auto-detects the caller context and applies the right shape adapter? Is that detection even possible from within Python's call stack?
- [ai] D2 (D variant): `@cisterna.tool` returns a RegistrationProxy object that implements `__get__` as a descriptor. When passed to `@mcp.tool`, the proxy detects the FastMCP registration context (via caller inspection or by implementing the FastMCP tool protocol interface) and applies the correct shape adapter before completing registration. The author writes one decorator; shape selection is automatic at registration time.
- [user] Cross-approach probe — async execution context (constraint 3): All four approaches must handle the case where an async tool function is called from CLI (no running loop, so asyncio.run() is safe) vs. from MCP (loop already running, asyncio.run() raises RuntimeError). The question is: where does each approach detect and adapt the execution context? Does it happen in the wrapper, in the registration surface, or in a shared utility the wrapper calls? What if a tool is defined as sync but the MCP transport expects a coroutine?
- [ai] E1 (cross-cutting): A transport-aware call shim — a shared utility `cisterna._call(fn, *args, **kwargs)` — that detects running event loop via `asyncio.get_running_loop()` and either `await`s directly (MCP path) or calls `asyncio.run()` (CLI path). Every approach's wrapper delegates actual invocation to this shim, so async context detection is a single implementation point rather than per-approach logic.
- [ai] E2 (cross-cutting): The registration surface produces TWO callables from one function — an async variant (for MCP) and a sync variant (for CLI) — materialized at wire/registration time. FastMCP gets the async version; Cyclopts gets the sync version. The async/sync split is explicit in the registration artifact rather than detected at runtime.
- [user] Cross-approach probe — error shape adaptation (constraint 2): When a tool raises an exception, Bathos expects `{ok: false, error_code, error, resolution_hint}`, Contemplex expects the exception to propagate (passthrough), and Xperiri expects a JSON string. All four approaches must intercept exceptions somewhere. The question: does exception-to-shape translation happen (a) in the per-function wrapper, (b) in server-level middleware (per constraint 1, FastMCP v3 already uses server-level middleware), or (c) in a separate error adapter layer? If FastMCP already handles this via middleware, does the function-level wrapper need to do it at all for MCP — or only for CLI?
- [ai] F1 (cross-cutting): Error shape for MCP is handled entirely by FastMCP server-level middleware (already the case per constraint 1) — the function-level decorator does NOT intercept exceptions for MCP. For CLI only, the decorator wraps exceptions into exit codes + stderr messages via a separate CLI error handler. This means the decorator has a dual error contract: no-op for MCP errors, active handler for CLI errors.
- [ai] F2 (cross-cutting): The decorator wraps exceptions into a `CisternaResult` union type (Ok[T] | Err[CisternaError]) at the function boundary for both transports. FastMCP middleware unpacks CisternaResult into the consumer-specific wire shape. Cyclopts CLI handler unpacks it into exit code + output. The function itself never raises — the decorator converts all exceptions to Err variants before they reach any consumer.
- [user] SCAMPER — Eliminate: What if there is no decorator at all? What if cisterna's registration surface is purely imperative — `cisterna.register(fn, name="my_tool", telemetry=True)` called in a setup block — rather than decorator-based? The function stays a plain callable at module scope, annotations untouched, no import-time side effects. Registration is explicit and auditable. What does this lose compared to decorator syntax, and does it lose anything that isn't just cosmetic?
- [ai] G1 (Eliminate variant): No decorator — purely imperative registration via `cisterna.register(fn, transports=["mcp", "cli"], shape="bathos")` in a setup block. Function stays a plain callable; no import-time side effects; annotations untouched. Telemetry is applied as a non-mutating wrapper only at registration time, not at definition time. Explicit, testable, no magic.
- [user] SCAMPER — Reverse: All four approaches assume cisterna adapts functions TO consumers. What if the relationship is reversed — consumers declare what shape they need, and cisterna's registry fulfills that contract at wire time by selecting the right adapter? I.e., the Bathos MCP server advertises "I need BathosShape" to cisterna, and cisterna's wire step selects and applies the adapter without the tool author or the decorator specifying it. The shape contract lives entirely in the consumer's server configuration, not in the function's decoration.
- [ai] G2 (Reverse variant): Shape is declared on the consumer server, not on the function. `cisterna.wire(mcp_server, shape=BathosShape())` — the shape adapter is a property of the wire call, not of the tool decorator. `@cisterna.tool` is shape-agnostic. Any function registered with cisterna can be wired to any consumer with any shape at wire time, without re-decorating. The tool author writes zero consumer-specific code.
- [user] Constraint probe — annotation preservation (constraint 5): FastMCP uses `inspect.signature()` and `__annotations__` for schema generation. Cyclopts uses the same for argument parsing. Any approach that returns a wrapper function must ensure the wrapper's signature is identical to the original at the `inspect` level — not just via `functools.wraps`. What happens with Annotated[] types (e.g., `Annotated[str, Doc("desc")]`)? Does `functools.wraps` copy `__annotations__` faithfully, or does it copy the dict reference? If the wrapper modifies the return type annotation (e.g., to wrap in CisternaResult), does that break FastMCP schema generation?
- [ai] H1 (cross-cutting): The wrapper uses `inspect.signature()` to extract the original signature, then constructs the wrapper with `__signature__` explicitly set to the original signature object (not just `functools.wraps`). Return annotation is left untouched on the callable passed to FastMCP; a separate internal attribute carries the CisternaResult contract for the CLI path only.
- [ai] H2 (cross-cutting): Approach that produces transport-specific function objects at wire time — the original function is never wrapped at decoration time. At `wire()` or `server.tool()` registration, cisterna generates a fresh function object for each transport with the correct return annotation for that transport (original for MCP passthrough, CisternaResult for CLI). Each generated function has its `__wrapped__` pointing to the original for traceability.
- [user] Competing-faction probe — shared assumption across all approaches: All four approaches assume a single function should serve both MCP and CLI. But what if the right design is a cisterna tool is a class (not a function) with two methods — `async def mcp_call(self, ...)` and `def cli_call(self, ...)` — where the class is the registration unit? The class holds shared state (telemetry context, name, description, schema), and each method has the right sync/async signature for its transport without any wrapping or shim. How does this change what the decorator attaches to?
- [ai] I1 (class-based variant): A `CisternaTool` class is the registration unit rather than a function. `@cisterna.tool` converts a function into a CisternaTool instance with `.mcp_fn` (async, passthrough return type) and `.cli_fn` (sync, exit-code-aware) as attributes. Registration APIs accept CisternaTool objects. The class holds name, description, telemetry config, and schema once — no duplication between transports.
- [ai] I2 (class-based variant): `@cisterna.tool` is a class decorator that makes the decorated function callable as both sync and async via `__call__` and `__await__`. When FastMCP awaits it, the async path runs. When Cyclopts calls it synchronously, the sync path runs. A single object, a single registration call per consumer, no separate MCP/CLI method split required from the author.
- [user] DIVERGENCE COMPLETE
- [user] Divergence complete. 39 ideas surfaced. Critic has already run lens-based challenge across all approaches with the following verdicts: FATAL on C, C2, D, D2, F2, I2. ACCEPTED: B (lazy registry + init-time wire), B1 (named registries), G2-steelman (pure-metadata marker + wire-time generation), E1 (transport-aware call shim), F1 (dual error contract), H1 (signature injection). The leading candidate for convergence is the B + G2-steelman hybrid. Ready to enter convergence.

## Decision Log
- [DEFER] G2 (Shape declared on wire call): [CRITIC] idea=G2 lens=feasibility finding=The global registry assumption collides with multi-server processes — constraint 4 says consumer identity is unknown at decoration time, but G2's single `cisterna.wire()` call cannot route tools to two servers with different shapes without named partitions (which is B1, a distinct variant); bare G2 is underspecified for multi-tenant processes. severity=MAJOR
- [ACCEPT] G2 (Shape declared on wire call): [CRITIC] idea=G2 lens=user-impact finding=Tool author writes zero consumer-specific code — the shape contract is entirely on the server configuration side, which aligns exactly with constraint 6 (primary user is tool author who should not need to know which consumer they're targeting); this is the correct separation of concerns. severity=INFO
- [DEFER] G2 (Shape declared on wire call): [CRITIC] idea=G2 lens=edge-case finding=If `wire()` is never called (common in test environments, notebooks, or scripts that import the tool module without a server), the decorated function is a dead stub — calling it directly returns nothing or raises, with no telemetry and no shape; the authoring-time vs. wire-time gap creates a class of silent test failures. severity=MAJOR
- [DEFER] G2 (Shape declared on wire call): [CRITIC] idea=G2 lens=implementation-cost finding=A live-proxy wire() (B2 variant) that handles post-import plugins adds a non-trivial observer mechanism to the global registry; combined with async execution context detection (E1/E2), the wire shim accumulates three orthogonal responsibilities — shape selection, async/sync split, and plugin backfill — making it the new complexity hotspot instead of the decorator. severity=MAJOR
- [REJECT] A (CisternaServer composite): [CRITIC] idea=A lens=feasibility finding=Constraint 1 states FastMCP v3 uses server-level middleware for ALL tools — a CisternaServer that wraps an externally-supplied FastMCP server cannot inject its own middleware layer without either patching the external server's middleware chain or requiring the tool author to use a cisterna-owned server exclusively; A1 mitigates but doesn't eliminate: wrapping an existing server still needs middleware injection which may conflict with the external server's own middleware stack. severity=MAJOR
- [REJECT] A (CisternaServer composite): [CRITIC] idea=A lens=reversibility finding=Committing to CisternaServer as the primary API surface means any future cisterna version that changes server lifecycle (e.g., hot-reload, multi-process worker) requires a breaking change to the composite object's interface; adopters cannot migrate away without restructuring their entire server initialization code. severity=MAJOR
- [REJECT] C (Consumer-namespaced decorators): [CRITIC] idea=C lens=user-impact finding=Constraint 4 is a hard blocker — consumer identity is NOT known at decoration time; `@cisterna.bathos.tool` forces the tool author to encode consumer knowledge at function definition, violating the primary design goal that tool authors should not need to know which consumer they're targeting; C1 acknowledges this by making the namespace lazy (equivalent to B1), which means C as a distinct approach dissolves into B. severity=FATAL
- [REJECT] C2 (stacked decorators for multi-consumer): [CRITIC] idea=C2 lens=edge-case finding=Stacked consumer decorators applied to the same function create two separate wrapper objects sharing one underlying callable; constraint 5 (annotation preservation) breaks when the outer decorator's `__signature__` has been modified by the inner decorator — the annotation chain is non-commutative and order-dependent, making schema generation for FastMCP and argument parsing for Cyclopts fragile and untestable without exhaustive ordering matrix tests. severity=FATAL
- [REJECT] D (Transparent wrapper protocol): [CRITIC] idea=D lens=user-impact finding=D puts full consumer-awareness burden on the tool author — they must call both `@mcp.tool` and `@app.command` after `@cisterna.tool`; this directly contradicts the primary user goal stated in the framing and constraint 6; the tool author must know both registration APIs of both consumers to use cisterna at all. severity=FATAL
- [REJECT] D2 (RegistrationProxy with context detection): [CRITIC] idea=D2 lens=feasibility finding=Detecting FastMCP registration context via caller inspection (`inspect.stack()`) at `@mcp.tool` decoration time is unreliable — FastMCP's decorator may be applied programmatically, inside metaclasses, or via `server.tool(fn)` imperative call; there is no stable Python ABI signal that distinguishes "being registered into FastMCP" from "being called from any other context"; the descriptor `__get__` approach only fires for attribute access, not for function-call registration. severity=FATAL
- [ACCEPT] G1 (Imperative register, no decorator): [CRITIC] idea=G1 lens=feasibility finding=A plain `cisterna.register(fn, transports=["mcp","cli"], shape="bathos")` call in a setup block is the most annotation-safe path — the original function object is passed untouched to FastMCP and Cyclopts; no `__signature__` surgery needed; telemetry wrapper is created at registration time from the original, not from a double-wrapped closure. severity=INFO
- [DEFER] G1 (Imperative register, no decorator): [CRITIC] idea=G1 lens=user-impact finding=Eliminating the decorator entirely loses the ergonomic benefit of co-location — the tool's name, description, and schema are defined far from the function body, creating a maintenance gap where renaming or docstring changes require updating a separate registration call; discoverability for new tool authors drops significantly compared to decorator syntax. severity=MINOR
- [ACCEPT] E1 (Transport-aware call shim): [CRITIC] idea=E1 lens=implementation-cost finding=A single `cisterna._call(fn, *args, **kwargs)` shim centralizing `asyncio.get_running_loop()` detection eliminates per-approach async duplication; the cost is one utility function with one testable invariant — lower cost than E2 (two materialized callables) which doubles the registration artifact count and creates divergence in FastMCP schema vs. Cyclopts schema if the generated functions drift. severity=INFO
- [REJECT] E2 (Two materialized callables at wire time): [CRITIC] idea=E2 lens=edge-case finding=Generating two separate function objects at wire time (async MCP version, sync CLI version) means annotation changes to the original function are not automatically reflected in already-materialized callables — re-wiring after a hot-module-reload would require explicit teardown and re-registration; the two callables can also diverge in behavior if they carry independent telemetry state. severity=MAJOR
- [ACCEPT] F1 (Dual error contract: no-op for MCP, active for CLI): [CRITIC] idea=F1 lens=feasibility finding=FastMCP v3 server-level middleware already handles MCP error shape (constraint 1); having the decorator intercept exceptions for MCP would double-handle them and produce incorrect results when middleware also catches — F1 correctly assigns MCP errors to middleware and CLI errors to the decorator, giving each consumer a single interception point. severity=INFO
- [REJECT] F2 (CisternaResult union type): [CRITIC] idea=F2 lens=implementation-cost finding=Wrapping all return values in `CisternaResult[T]` changes the return annotation of every tool function — FastMCP schema generation reads `__annotations__["return"]` and would generate `CisternaResult` as the tool's output schema instead of the actual return type T; constraint 5 forbids annotation mutation that breaks FastMCP schema generation; this approach requires FastMCP middleware to unwrap CisternaResult before schema emission, adding coupling to FastMCP internals. severity=FATAL
- [ACCEPT] H1 (Explicit __signature__ injection): [CRITIC] idea=H1 lens=feasibility finding=Setting `wrapper.__signature__ = inspect.signature(original)` is the correct Python idiom used by FastMCP itself for dynamic tool generation; `functools.wraps` copies `__annotations__` as a dict reference (which is safe) but does NOT set `__signature__`, so FastMCP's `inspect.signature(follow_wrapped=False)` would see the wrapper's own (empty) signature without explicit injection; H1 is a required correctness property, not an optimization. severity=INFO
- [DEFER] H2 (Transport-specific function objects at wire time): [CRITIC] idea=H2 lens=reversibility finding=Generating fresh function objects per transport at wire() time solves annotation preservation cleanly (each object has the exact original annotations), but introduces the same divergence risk as E2 — the two objects must stay synchronized, and traceability via `__wrapped__` is a convention not a guarantee; this approach is sound but requires more infrastructure than H1 which achieves the same annotation fidelity with less object proliferation. severity=MINOR
- [DEFER] I1 (CisternaTool class as registration unit): [CRITIC] idea=I1 lens=user-impact finding=A CisternaTool class with `.mcp_fn` and `.cli_fn` attributes is a sound encapsulation, but shifts the authoring mental model from "I decorated a function" to "I created an object" — this is a bigger conceptual footprint for tool authors and breaks the expectation that `@cisterna.tool` produces something that can be called directly in tests without knowing which transport to invoke; testability requires deciding which variant to call. severity=MINOR
- [REJECT] I2 (Single object callable as sync and async): [CRITIC] idea=I2 lens=feasibility finding=A single object implementing both `__call__` (sync) and `__await__` (async) requires that `__await__` returns an iterator — this is only possible if the object's `__call__` constructs a coroutine object internally; FastMCP does NOT use `__await__` for tool dispatch — it inspects `asyncio.iscoroutinefunction()` and calls the function directly; an I2 object would fail `iscoroutinefunction()` checks and be treated as sync by FastMCP, losing the async execution path entirely. severity=FATAL
- [ACCEPT] B (Lazy registry + init-time wire): [CRITIC] idea=B lens=feasibility finding=B is the approach most compatible with the fixed constraints: `@cisterna.tool` at decoration time preserves the original callable (with H1 signature injection), the global registry is populated at import time, and `cisterna.wire(mcp_server, cli_app, adapter=BathosAdapter())` at startup selects shape per-server — this satisfies constraint 4 (consumer identity known at wire time) and constraint 6 (tool author writes no consumer-specific code). B1 named partitions resolve the multi-server concern. severity=INFO
- [DEFER] B (Lazy registry + init-time wire): [CRITIC] idea=B lens=edge-case finding=The testability gap is real but not fatal: a tool decorated with `@cisterna.tool` that is called directly in tests bypasses the wire step, meaning telemetry and shape adaptation are not applied; however, the original function behavior IS preserved (unlike G2 where the decorated callable is inert) because `@cisterna.tool` can return a transparent wrapper that calls through — tests get correct business logic, just without telemetry, which is an acceptable test-environment tradeoff. severity=MINOR
- [ACCEPT] B1 (Named registries for multi-server isolation): [CRITIC] idea=B1 lens=implementation-cost finding=Named registry partitions (`@cisterna.tool(registry="bathos")`) add one optional keyword argument to the decorator and a dict-of-lists to the global registry — implementation cost is trivial relative to the value of supporting multi-server processes; the default registry (no argument) covers the common single-server case with zero authoring overhead. severity=INFO
- [ACCEPT] G2 (Shape declared on wire call) — steelman: [CRITIC] idea=G2 lens=feasibility finding=In its steelmanned form, G2 generates transport-specific function objects at wire() time from pure-metadata decorated functions — no wrapping at decoration time, so annotation preservation (H1/H2) is a non-issue, and the decorated function remains a genuine plain callable; this resolves G2's MAJOR feasibility concern; the remaining gap is the test utility requirement (`cisterna.materialize`) which is a documentation and API addition, not a blocker. severity=INFO
- [DEFER] B/G2 hybrid — pre-mortem finding: [CRITIC] idea=B/G2-hybrid lens=edge-case finding=Import-order dependency between `@cisterna.tool` decoration and `cisterna.wire()` is an invisible failure mode — tools in lazily-loaded plugin modules silently miss registration with no error; mitigation requires either (a) a mandatory post-wire validation step that enumerates expected tools vs. wired tools and raises, or (b) the B2 live-proxy pattern with explicit warnings on late arrivals; the spec must mandate one of these. severity=MAJOR
- [DEFER] B/G2 hybrid — pre-mortem finding: [CRITIC] idea=B/G2-hybrid lens=implementation-cost finding=The `cisterna.wire()` function accumulates three separate responsibilities in both B and G2: (1) shape adapter selection, (2) async/sync callable generation (E1 shim invocation), (3) FastMCP server registration + Cyclopts app registration — this is a violation of single responsibility and makes wire() the hardest function to test and maintain; the spec must split wire() into compose-then-register steps internally even if the public API is a single call. severity=MINOR
- [DEFER] premortem skipped — synthesizer blocked: Session task_type is "architectural" (non-routine). brainstorm_status reports premortem_done=false. Per synthesizer protocol, premortem is required before set_winner for non-routine types. Synthesizer cannot proceed to convergence without premortem completion.

## Assumptions

| ID | Assumption | Status |
|---|---|---|
| A-M2-1 | `@cisterna.tool` can be a pure metadata marker (stores fn reference, returns fn unchanged) without breaking any FastMCP or Cyclopts introspection that runs at import time | Unverified — verify against FastMCP source before implementation |
| A-M2-2 | FastMCP's `inspect.signature()` call uses `follow_wrapped=True` (or equivalent) so `__signature__` injection on the generated callable is sufficient for correct schema generation | Partially verified — H1 is used by FastMCP itself for dynamic tool generation |
| A-M2-3 | Cyclopts 4.18.0+ `asyncio.iscoroutinefunction()` check on the registered command determines async/sync dispatch path — a plain `async def` wired via `register_cli()` will be dispatched with `asyncio.run()` correctly | Verified — cyclopts `_run_maybe_async_command` uses `inspect.iscoroutinefunction` |
| A-M2-4 | FastMCP v3 middleware (`CisternaMiddleware`) already handles MCP error shaping (F1 dual contract) — the generated MCP callable does NOT need to catch exceptions | Verified from M1 implementation |
| A-M2-5 | A global module-level registry dict (keyed by registry name) is safe in CPython because the GIL protects dict insertions at import time; multiprocessing spawn is supported; fork is prohibited (C9 from M1) | Inherited from M1 C9 constraint |

## TBDs

| ID | Item | Note |
|---|---|---|
| TBD-M2-1 | Whether `cisterna.wire()` supports explicit `mcp_version` override (v2/v3) or always auto-detects via `capability_probe.surface_for()` | Auto-detect is cleaner; override useful for testing against v2 while deployed on v3 |
| TBD-M2-2 | Whether the Cyclopts App is always caller-supplied or optionally owned by cisterna (convenience for `cisterna.run_cli()`) | Caller-supplied is safer and more composable; ownership creates coupling |
| TBD-M2-3 | Whether `validate=False` is permitted as a production escape hatch or prohibited entirely; pre-mortem recommends at minimum a loud `warnings.warn(stacklevel=2)` on disable | Pre-mortem failure #1: teams disable validation in staging and never re-enable |
| TBD-M2-4 | M2 scope boundary: does M2 include Cyclopts CLI registration (`register_cli`) or only FastMCP MCP registration? Current ecosystem is Typer-only; Cyclopts is a declared dependency but unused | If M2 is MCP-only, CLI registration moves to M3; avoids premature Cyclopts adoption |
| TBD-M2-5 | Whether `cisterna._registry(name)` is part of the public API (test/introspection use) or internal only | Tests need it; if internal, test fixtures use the same private API as production introspection |

## Pre-mortem Record
**User:** Three failure scenarios, ranked by probability:

1. (Most likely) The post-wire validation raised CisternaWireError in staging, so teams disabled it with `validate=False` and never re-enabled it. Six months in, three tool modules are lazily imported and never wired to production servers. The telemetry gap is noticed during an incident when mcp.call_start records don't appear for those tools. Mitigation: validation must be on-by-default and the disable path must log a loud warning; the spec should prohibit `validate=False` in production configs.

2. (Likely) FastMCP changed its internal `inspect.signature()` call to use `follow_wrapped=True` in a minor version, bypassing the `__signature__` injection. All wired tools started generating incorrect JSON schemas (the wrapper's empty signature instead of the original). This went undetected for two releases because the JSON schema was valid but wrong — arguments were still accepted because FastMCP fell back to `**kwargs`. The spec must include an AC that validates the generated schema matches the original function's type annotations for at least two representative cases.

3. (Possible) The compose-then-register pipeline's internal state (WiredRegistry) accumulated across test runs because tests imported the cisterna module but never cleared the global registry between tests. Each test added tools to the global default registry, so by test 50, wiring a fresh server also picked up tools from previous tests. The spec needs a `cisterna.clear_registry(registry=None)` API and all tests must call it in teardown.
**AI:** _not recorded_

## Acceptance Criteria

### AC-TOOL: @cisterna.tool marker

**AC-TOOL-1 — Pure metadata, no wrapping**
Given a function `fn` decorated with `@cisterna.tool`;
When the original function object is inspected via `type(fn)`, `inspect.signature(fn)`, and `fn.__annotations__`;
Then all three are identical to the undecorated function; `fn()` is callable and returns its result directly without telemetry or shape adaptation.

**AC-TOOL-2 — Default registry population**
Given `@cisterna.tool` applied to functions A, B, C in module scope;
When `cisterna._registry("default")` is inspected before any `wire()` call;
Then all three function names appear in the registry; no wrapping of the originals has occurred.

**AC-TOOL-3 — Named registry isolation**
Given `@cisterna.tool(registry="bathos")` on function A and `@cisterna.tool(registry="contemplex")` on function B;
When `cisterna._registry("bathos")` and `cisterna._registry("contemplex")` are each inspected;
Then A appears only in "bathos"; B appears only in "contemplex"; neither registry contains the other's tools.

### AC-WIRE: cisterna.wire()

**AC-WIRE-1 — Wire to FastMCP**
Given a FastMCP server instance and `cisterna.wire(server, adapter=BathosAdapter())` called after all tool modules are imported;
When the server's registered tool list is inspected;
Then each function from the default registry appears as a FastMCP tool with its original name and type annotations visible via `inspect.signature`.

**AC-WIRE-2 — Wire to Cyclopts**
Given a `cyclopts.App` instance and `cisterna.wire(app=cli_app)` called;
When the app's command list is inspected;
Then each function from the default registry appears as a Cyclopts command with its original parameter names and types.

**AC-WIRE-3 — Dual wire (MCP + CLI)**
Given both `server` and `cli_app` supplied to `cisterna.wire(server, app=cli_app, adapter=BathosAdapter())`;
When both server and app are inspected;
Then the same tools appear in both; no tool appears in one but not the other.

**AC-WIRE-4 — Named registry scoping**
Given tools in "bathos" registry and tools in "contemplex" registry;
When `cisterna.wire(bathos_server, adapter=BathosAdapter(), registry="bathos")` is called;
Then only "bathos" tools are registered on `bathos_server`; "contemplex" tools are unaffected.

### AC-TELEM: Telemetry

**AC-TELEM-1 — MCP telemetry emission**
Given a function wired via `wire(server, adapter=BathosAdapter())` with a `ShadowExporter` registered;
When the tool is called via the FastMCP server;
Then `mcp.call_start` and `mcp.call_end` records appear in `ShadowExporter.records` with correct `tool` field.

**AC-TELEM-2 — CLI telemetry emission**
Given a function wired via `wire(app=cli_app)` with a `ShadowExporter` registered;
When the CLI command executes;
Then `cli.cmd_start` and `cli.cmd_end` records appear in `ShadowExporter.records`.

### AC-ERROR: Error contracts (F1 dual contract)

**AC-ERROR-1 — MCP error: envelope returned, no re-raise**
Given a wired FastMCP tool that raises `RuntimeError("boom")`;
When called via the FastMCP server;
Then the exception is NOT re-raised to the transport; `adapter.shape_error()` result is returned (`ok=False`); `mcp.tool_error` is emitted.

**AC-ERROR-2 — CLI error: exception re-raised**
Given a wired Cyclopts command that raises `RuntimeError("boom")`;
When called via `cli_app()`;
Then the exception IS propagated (CLI owns exit code); `cli.cmd_end` with `ok=False` is emitted before re-raise.

### AC-SIG: Annotation preservation (H1)

**AC-SIG-1 — __signature__ preserved on generated MCP callable**
Given a function with `(query: str, limit: int = 10) -> list[dict]` signature;
When `cisterna.wire(server, ...)` registers it and the registered FastMCP callable is retrieved;
Then `inspect.signature(registered_callable)` shows `query: str`, `limit: int = 10`, return `list[dict]` — identical to original.

**AC-SIG-2 — Annotated[] types preserved**
Given a function with `Annotated[str, "description"]` parameter;
When registered via `wire()`;
Then the `Annotated` wrapper survives and is visible to FastMCP schema generation.

**AC-SIG-3 — FastMCP JSON schema correctness**
Given a wired tool with `(query: str, limit: int = 10) -> list[dict]`;
When FastMCP generates the JSON schema for that tool;
Then schema has `query` as required string, `limit` as optional integer with default 10.

### AC-ASYNC: Async/sync handling (E1 shim)

**AC-ASYNC-1 — async def via MCP**
Given an `async def` tool function wired to FastMCP;
When called via FastMCP async dispatch (inside running event loop);
Then the coroutine executes correctly; `asyncio.run()` is NOT called (would raise); result is returned.

**AC-ASYNC-2 — async def via CLI (no running loop)**
Given the same `async def` tool function wired to Cyclopts;
When called via `cli_app()` from a context with no running event loop;
Then Cyclopts calls `asyncio.run()` transparently; the result is returned; no `RuntimeError` raised.

### AC-VALIDATE: Post-wire validation

**AC-VALIDATE-1 — validate() passes when all tools wired**
Given all tool modules imported before `wire()` and `wire()` called successfully;
When `cisterna.validate()` is called;
Then no exception is raised.

**AC-VALIDATE-2 — validate() fails on import-order miss**
Given a tool name "missing_tool" that is in the registry but was NOT wired (due to import order issue);
When `cisterna.validate(registry="default", expected=["missing_tool"])` is called;
Then `CisternaWireError` is raised listing "missing_tool".

**AC-VALIDATE-3 — validation on-by-default**
Given `cisterna.wire()` is called without explicit `validate=False`;
When a tool module was never imported before wire();
Then `CisternaWireError` is raised immediately after wire() completes (fail-fast, not warn).

### AC-CLEAR: Registry management

**AC-CLEAR-1 — clear_registry() empties default**
Given tools in the default registry;
When `cisterna.clear_registry()` is called;
Then the default registry is empty; subsequent `wire()` registers zero tools.

**AC-CLEAR-2 — clear_registry(name) is scoped**
Given tools in "bathos" and "contemplex" registries;
When `cisterna.clear_registry("bathos")` is called;
Then only "bathos" is cleared; "contemplex" is unchanged.

---

## Implementation Spec

### Module layout

```
cisterna/
  registration/
    __init__.py      # exports: tool, wire, validate, clear_registry, CisternaWireError
    decorator.py     # @cisterna.tool — pure metadata marker; populates registry
    registry.py      # ToolRegistry: dict[str, list[ToolEntry]]; named partitions
    compose.py       # compose(registry_name, adapter) -> WiredRegistry
    wired.py         # WiredRegistry: .register_mcp(server), .register_cli(app)
    shim.py          # E1: _call_shim(fn, *args, **kwargs) — async/sync detection
    errors.py        # CisternaWireError
```

### Public API

```python
# Registration marker (pure metadata, no wrapping)
def tool(fn=None, *, registry: str = "default", name: str | None = None,
         description: str | None = None):
    """Mark fn as a cisterna tool. Returns fn UNCHANGED."""

# Wire all tools in a registry to FastMCP server and/or Cyclopts app
def wire(
    server=None,                    # FastMCP server instance (optional)
    *,
    app=None,                       # cyclopts.App instance (optional)
    adapter: AdapterBase | None = None,  # shape adapter for MCP (required if server supplied)
    registry: str = "default",
    validate: bool = True,          # raise CisternaWireError on import-order misses
) -> "WiredRegistry": ...

# Inspect registry contents (primarily for tests)
def _registry(name: str = "default") -> list["ToolEntry"]: ...

# Post-wire validation (also called internally by wire() when validate=True)
def validate(
    registry: str = "default",
    expected: list[str] | None = None,  # if None, validates all registered tools are wired
) -> None: ...  # raises CisternaWireError on failure

# Clear registry (required in test teardown)
def clear_registry(name: str | None = None) -> None: ...
    # name=None clears all registries; name="bathos" clears only that partition

class CisternaWireError(RuntimeError):
    missing: list[str]  # tool names that could not be wired
```

### Internal architecture

```
@cisterna.tool
    → ToolEntry(fn, name, registry) stored in _REGISTRY[registry]
    → fn returned unchanged

cisterna.wire(server, adapter=BathosAdapter(), registry="bathos")
    → compose("bathos", BathosAdapter()) → WiredRegistry
    → WiredRegistry.register_mcp(server):
        for entry in registry:
            mcp_callable = _make_mcp_callable(entry.fn, adapter)
            # mcp_callable.__signature__ = inspect.signature(entry.fn)  [H1]
            # mcp_callable is async (wraps entry.fn via E1 shim)
            server.tool(name=entry.name)(mcp_callable)
    → WiredRegistry.register_cli(app) [if app supplied]:
        for entry in registry:
            cli_callable = _make_cli_callable(entry.fn)
            # cli_callable is sync; wraps entry.fn with asyncio.run() if needed [E1]
            # cli_callable re-raises exceptions [F1]
            app.command(name=entry.name)(cli_callable)
    → validate() if validate=True [raises CisternaWireError on miss]

E1 shim (_call_shim):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)  # MCP path
    elif inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(*args, **kwargs))  # CLI path
    else:
        return fn(*args, **kwargs)  # sync path
```

### Backlog DAG

```
M2-PKG    Update pyproject: add cisterna.registration to packages. Gate: import works.
    |
    v
M2-REGISTRY   decorator.py + registry.py: @cisterna.tool marker; ToolEntry; named registries;
              clear_registry(); _registry(). Gate: AC-TOOL-1..3, AC-CLEAR-1..2.
    |
    v
M2-COMPOSE    compose.py + wired.py + shim.py + errors.py: compose(); WiredRegistry;
              _make_mcp_callable (H1 __signature__); _make_cli_callable (E1 shim);
              CisternaWireError. Gate: AC-SIG-1..3, AC-ASYNC-1..2.
    |
    v
M2-WIRE       wire() public API; validate(); post-wire validation (fail-fast).
              Gate: AC-WIRE-1..4, AC-VALIDATE-1..3.
    |
    v
M2-TELEM      Wire telemetry: connect compose step to M1 emit_start/end/error via adapter;
              dual error contract F1. Gate: AC-TELEM-1..2, AC-ERROR-1..2.
    |
    v
M2-INIT       Export tool, wire, validate, clear_registry from cisterna/__init__.py.
              Update capability_probe to handle M2 surface. Gate: full import smoke test.

--- M2.5 ---
M2.5-XPERIRI  Wire XpeririAdapter (JSON-str returns) via M2 compose step. depends M2-WIRE.
M2.5-MYXCEL   Wire MyxcelAdapter via M2 compose step. depends M2-WIRE.
```

### Pre-mortem mitigations (required in spec, not optional)

1. **Validation disable path must warn loudly**: If `validate=False` is passed to `wire()`, emit `warnings.warn("cisterna.wire() called with validate=False — silent registration misses will not be detected", CisternaValidationDisabledWarning, stacklevel=2)`.
2. **AC-SIG-3 guards against FastMCP signature drift**: A test that calls FastMCP's own schema generation on a wired tool and asserts the output JSON schema matches the original function's annotations must be in the suite.
3. **clear_registry() must be called in test fixtures**: All tests that call `wire()` must call `clear_registry()` in teardown; a pytest autouse fixture should be provided in `tests/conftest.py`.
