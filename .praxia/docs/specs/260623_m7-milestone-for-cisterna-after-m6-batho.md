---
session_id: c8661c8a
topic: M7 milestone for cisterna after M6 bathos cutover — primary candidate OTLP egress (CISTERNA_OTLP_ENDPOINT), alternatives: external adapter epics (#2145/#2146), export hardening II, telemetry operator runbook. What should M7 optimize for?
task_type: constrained-technical
winner: M7-AB OTLP gRPC egress bundle: OtlpExporter (ExporterBase) + CISTERNA_OTLP_ENDPOINT gate in init_pipeline; map mcp.call_start/end pairs to spans with tool/request_id attributes; in-memory SpanExporter tests; JSONL fan-out unchanged; HTTP OTLP deferred
created_at: 2026-06-23T21:58:31.547373+00:00
---

# Brainstorm: M7 milestone for cisterna after M6 bathos cutover — primary candidate OTLP egress (CISTERNA_OTLP_ENDPOINT), alternatives: external adapter epics (#2145/#2146), export hardening II, telemetry operator runbook. What should M7 optimize for?

## Problem Frame
Frame (PEGS): Problem — operators cannot visualize cisterna telemetry in standard backends (Grafana/Tempo/Jaeger) without bespoke JSONL ingestion. Goal — wire optional OTLP exporter from existing Record pipeline when CISTERNA_OTLP_ENDPOINT set; JSONL fan-out unchanged. Environment — cisterna library only; [otlp] extra already in pyproject; ShadowExporter pattern for tests. Solution space — OTLP gRPC first (extra dep already grpc), Record→Span bridge, init_pipeline hook, advisory CI with otel-collector container or in-memory exporter test.

## Idea Pool
- [ai] M7-A OTLP gRPC exporter: OtlpExporter class implementing ExporterBase; maps Record→ReadableSpan; enabled when CISTERNA_OTLP_ENDPOINT set at init; JSONL + OTLP fan-out
- [ai] M7-B In-memory OTLP test exporter: use opentelemetry-sdk test span exporter in pytest; no docker; AC-M7 shadow asserts span name + tool attribute
- [ai] M7-C HTTP/protobuf OTLP alternate: second endpoint env CISTERNA_OTLP_PROTOCOL=http; defer if grpc sufficient
- [ai] M7-D External adapter sprint: #2145 Xperiri + #2146 Myxcel in cisterna shadow only — no OTLP
- [ai] M7-E Export hardening II: multi-emitter golden matrix — deferred again
- [ai] M7-F Operator runbook only: docs for JSONL→duckdb queries + cutover playbook; zero code
- [ai] M7-G Dual-export advisory CI: export-dogfood job with otel-collector sidecar; continue-on-error
- [user] PEGS decomposition: Processes — emit_event → Record → QueueListener → fan-out exporters. Events — mcp.call_start/end/error, span.start/end, heartbeat. Goals — never-raise, <1ms enqueue, dual JSONL+OTLP when configured. States — pipeline uninitialized / JSONL-only / JSONL+OTLP. Constraints — otel-sdk only in [otlp] extra; import cisterna without otlp extra must not load sdk. Assumption: Record.fields map cleanly to span attributes (tool, request_id, duration_ms).
- [user] Additional components: init_pipeline reads CISTERNA_OTLP_ENDPOINT; OtlpExporter.export(record) builds SpanData; semantic conventions for service.name=cisterna; batch span processor async like JSONL listener isolation. Risk: OTLP export blocking — must stay off hot path (batch processor thread). Neglected alternative: logs bridge (OTLP logs) — out of scope, traces only for M7.
- [user] M7-H Minimal M7: OtlpExporter + env gate + 3 unit tests + pyproject docstring; no CI collector — ship fast
- [user] Divergence complete — ready to converge. Favor M7-A + M7-B bundle (exporter + in-memory test gate).

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Critic response: mitigate span-pair risk by exporting only mcp.call_start/end + span.*.end as OTLP spans; heartbeats as span events or drop. Accept M7-H steelman for scope — advisory collector CI is M7.1 not M7.0. External adapters #2145/#2146 remain M8+.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Frame (PEGS): Problem — operators cannot visualize cisterna telemetry in standard backends (Grafana/Tempo/Jaeger) without bespoke JSONL ingestion. Goal — wire optional OTLP exporter from existing Record pipeline when CISTERNA_OTLP_ENDPOINT set; JSONL fan-out unchanged. Environment — cisterna library only; [otlp] extra already in pyproject; ShadowExporter pattern for tests. Solution space — OTLP gRPC first (extra dep already grpc), Record→Span bridge, init_pipeline hook, advisory CI with otel-collector container or in-memory exporter test.
**When** implementing M7-AB OTLP gRPC egress bundle: OtlpExporter (ExporterBase) + CISTERNA_OTLP_ENDPOINT gate in init_pipeline; map mcp.call_start/end pairs to spans with tool/request_id attributes; in-memory SpanExporter tests; JSONL fan-out unchanged; HTTP OTLP deferred
**Then**
  - [ ] _add specific measurable criteria_
