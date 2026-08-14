---
name: customizing-tools
description: This skill should be used whenever a project needs functionality that already exists somewhere else and has to decide how to acquire it — accept it as a dependency, vendor its source, cherry-pick a piece of it, re-implement it from scratch, derive design inspiration from it without copying code, or derive process lessons from a postmortem about it. Trigger on phrases like "should we add this as a dependency", "should we vendor this", "should we fork this library", "is this safe to depend on", "NIH" / "not invented here", "should we just write our own", or any request to evaluate a specific package/crate/library before adopting it. Also trigger for the specific, high-stakes case of migrating a stable Python module to Rust — "migrate this to Rust", "rewrite this in Rust", "add a pyo3 extension", "speed this up with Rust", "should this be a Rust extension" — since that migration is itself a re-implement decision with its own automation workflow (pyo3 scaffolding, rayon/orx-parallel parallelism choice, wasm/webgpu compilation targets). Use this proactively before adding any new dependency or starting any rewrite, not just when the user names the skill.
---

# Customizing tools

Six ways exist to acquire functionality that already lives somewhere else: accept a dependency,
vendor it, cherry-pick from it, re-implement it, derive inspiration from it, or derive lessons
from it. Treating "just add the dependency" or "let's just write our own" as a reflex — rather
than a choice among six real options with real, cited tradeoffs — is exactly the failure mode
this skill exists to prevent. It covers two workflows: adjudicating that six-way decision, and
(one specific, high-stakes instance of "re-implement") automating a Rust migration behind a pyo3
interface.

## Workflow 1: the customization decision

### Fast path — most decisions

Name the specific external functionality needed precisely (a package name and version, or the
exact behavior/algorithm) — a vague need ("something like lodash") can't be adjudicated. Then
read `references/decision-matrix.md` for that option's `Recommend when` / `Avoid when` bullets.
This document already reflects independent research (grounded, cited arguments for and against
each option) adjudicated by three jurors reasoning through different lenses — security/
maintenance, delivery speed, license/IP. For a routine decision, matching the situation against
those bullets *is* the workflow; don't re-litigate a decision this document already settled.

### Fresh jury — novel or high-stakes decisions

Run a fresh jury instead of the fast path when the situation doesn't cleanly match any bullet in
the reference doc, or when the choice will be expensive to reverse (a core dependency, a
security-boundary component, a rewrite that will consume weeks). Dispatch three independent
judgments of the *specific* situation, each through one of the three lenses the reference doc
uses (security/maintenance burden, delivery speed, license/IP), each grounded in the situation's
actual specifics rather than the pre-computed examples. Aggregate by looking for where the three
lenses agree — that's a high-confidence verdict — and by reading where they disagree, since
disagreement usually marks a genuine tradeoff rather than noise to average away.

If a praxia workspace is available (an MCP tool resolving to `rig_run` with `flow="jury"`, or the
`write_jury_verdict` tool), prefer it for the fresh-jury step — it is praxia's existing n:1 jury
primitive with deterministic aggregation, purpose-built for exactly this "multiple independent
verdicts reduced by an aggregate" shape. Fall back to three independent subagent dispatches
(the `Agent` tool, or equivalent) when praxia isn't present — this skill must work standalone,
since cisternal is consumed by projects that don't all have praxia installed.

### Record the decision

Once a decision is made — fast path or fresh jury — record it:

```bash
uv run python scripts/record_decision.py decision \
    --option accept_dependency --target "httpx for the outbound HTTP client" \
    --confidence 0.8 --note "actively maintained, MIT, small transitive closure"
```

This emits a real event into cisternal's own telemetry pipeline (`cisternal.telemetry`) — the
same substrate every cisternal-family tool already streams through — not a bespoke log file for
this skill alone. That is what makes these decisions queryable and auditable later: a year from
now, "why did we vendor X instead of depending on it" has an answer in the same place as every
other cisternal-family telemetry event, not a comment someone has to remember to go find. Keep
the recorded rationale's citations attached to wherever the decision itself gets written down
(a commit message, a design doc, a code comment near the integration point) — a decision like
"we vendored this" is much more useful to a future reader with "because left-pad" attached than
without it.

## Workflow 2: Rust migration automation

Re-implementing a stable Python module in Rust behind a pyo3 interface is itself a `reimplement`
decision — start by consulting the decision matrix's `reimplement` entry for the specific module
in question before treating a migration as a foregone conclusion. Once the decision is made,
this workflow scaffolds and instruments the migration.

### 1. Prioritize by stability, not by hotness

Prefer migrating a **stable** surface: one with low recent churn, an already-narrow public API
boundary, and existing test coverage a Rust reimplementation can be graded against. A Python
module still under active design iteration is a poor migration candidate regardless of how much
it would benefit from Rust's performance — the migration cost compounds every time the Python
API it's shadowing changes underneath it. Grade parity against the existing Python test suite
before cutover, the same discipline `jax-port`-style migrations already use elsewhere in this
tool family: a graded parity test that fails on a real behavioral difference, not a rewrite that
merely "looks right."

### 2. Scaffold with pyo3 + maturin

Read `references/pyo3.md` for the mixed Python/Rust project layout, the `#[pymodule]`/
`#[pyfunction]`/`#[pyclass]` macros, GIL/free-threading interaction (`Python::attach`/
`Python::detach`), Rust `Result` → Python exception translation, and the `abi3` stable-ABI
decision that determines whether one wheel covers every supported Python version or the CI
matrix needs one build per version. Choose the `abi3` floor *before* scaffolding — raising it
later means rebuilding the whole CI matrix, not editing one file.

### 3. Choose the parallelism strategy

For CPU-bound hot paths, read `references/rayon.md` (the default choice — the most
battle-tested, widest-audited option, with a well-documented `Python::allow_threads`/
`Python::detach` GIL-release pattern) and `references/orx-parallel.md` (prefer this specifically
for longer chained iterator pipelines or early-exit-heavy searches, where its pull-based
chunking measurably outperforms rayon's split/join model in its own published benchmarks — not
as a default, as a targeted choice for that workload shape). Both integrate with pyo3 the same
way: convert Python inputs to owned Rust data, release the GIL for the parallel region, never
hold a `Python<'_>` token across the release boundary into worker closures.

### 4. Consider GPU offload and dual compilation targets

For compute-heavy kernels beyond what CPU parallelism reaches, read `references/webgpu.md` —
`wgpu` gives one compute-shader API surface that runs natively (Vulkan/Metal/DX12) and compiles
to WASM, so the same kernel can serve a native pyo3 build and a browser/sandboxed-plugin build
without a second implementation. If browser or sandboxed-plugin distribution matters at all for
this surface, read `references/wasm.md` before finalizing the crate structure — a crate that
needs to build for both `abi3` (native, pyo3) and `wasm32-unknown-unknown` has real structural
constraints (feature-gating, no arbitrary filesystem/threads in the WASM sandbox) that are much
cheaper to design in from the start than to retrofit after the pyo3-only version ships.

### 5. Instrument every stage

Record each migration stage as it happens, the same way as a decision:

```bash
uv run python scripts/record_decision.py migration-stage \
    --stage scaffold --target "cisternal.export.write" \
    --note "maturin mixed layout, abi3-py313 floor"
```

Valid stages: `assess`, `scaffold`, `build`, `parity_test`, `cutover`. This is what makes the
migration itself a telemetered pipeline rather than a rewrite whose progress lives only in
someone's memory — dogfooding cisternal's own stated purpose as the shared telemetry substrate
for the tool family on the tool family's own migration work.

## Keeping the references current

The five Rust-topic reference docs (`pyo3.md`, `orx-parallel.md`, `rayon.md`, `wasm.md`,
`webgpu.md`) each open with a machine-parseable version stamp:
`<!-- ref-crate-versions: name=version; checked=YYYY-MM-DD -->`. Run the staleness checker
before trusting a reference doc's specifics on anything version-sensitive (an API that was
renamed, a feature that shipped since):

```bash
uv run python scripts/update_references.py --check
```

This does **not** regenerate stale content — that requires real research (the same kind that
produced these docs originally: WebSearch/WebFetch against each crate's actual current docs), not
something a deterministic script can responsibly fake. It tells you *which* reference has
drifted so a fresh research pass can be scoped to just that one topic instead of guessing or
redoing all five. `decision-matrix.md` is not version-stamped — it isn't tied to a crate release,
only to real incidents and case law, and stays current until a materially new incident or ruling
changes the picture.

## Additional resources

- **`references/decision-matrix.md`** — the full six-option matrix: jury-adjudicated
  recommend/avoid guidance plus every supporting citation.
- **`references/pyo3.md`** — pyo3 + maturin: project layout, macros, GIL/free-threading,
  error translation, packaging.
- **`references/rayon.md`** — CPU data-parallelism, the default choice.
- **`references/orx-parallel.md`** — CPU parallelism for chained/early-exit-heavy workloads.
- **`references/wasm.md`** — Rust → WebAssembly as a dual/alternate compilation target.
- **`references/webgpu.md`** — `wgpu` as a compute-shader target alongside CPU parallelism.
- **`scripts/record_decision.py`** — emit a decision or migration-stage event into cisternal's
  real telemetry pipeline.
- **`scripts/update_references.py`** — detect (not fix) stale crate-version stamps.
