<!-- ref-crate-versions: wasm-bindgen=0.2.127; checked=2026-08-13 -->

# Rust → WebAssembly as a Migration Deployment Target

**Technical reference — compiled 2026-08-13**

Scope: evaluates compiling Rust to WebAssembly (WASM) as a deployment target for a Rust migration, covering tooling (`wasm-pack`, `wasm-bindgen`), the two primary compilation targets, the WASM sandbox's capability model, two concrete distribution scenarios (in-browser, sandboxed plugin runtime), and the specific constraints this imposes on a crate that must *also* build natively for PyO3.

---

## 1. Toolchain landscape

### 1.1 `wasm-bindgen`

`wasm-bindgen` is a Rust library + CLI tool that generates high-level, typed interop bindings between a compiled `.wasm` module and JavaScript, so you're not limited to passing raw integers/floats across the boundary. It handles importing JS APIs into Rust (DOM, `console`, Web APIs) and exporting Rust functions/structs to JS as classes and functions, with strings, closures, and complex types, and can auto-generate `.d.ts` TypeScript bindings.[^bindgen-intro]

Basic shape:

```rust
use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub fn greet(name: &str) -> String {
    format!("Hello, {name}!")
}
```

```bash
cargo build --target wasm32-unknown-unknown --release
wasm-bindgen target/wasm32-unknown-unknown/release/mycrate.wasm --out-dir pkg --target web
```

### 1.2 `wasm-pack`

`wasm-pack` is the higher-level workflow tool built on top of `wasm-bindgen`: it invokes `cargo` with the correct flags, runs the `wasm-bindgen` CLI to generate bindings, runs `wasm-opt` for size/perf optimization, and packages the result as an npm-publishable package.[^bindgen-intro] It's described as "a one-stop shop for building and working with rust-generated WebAssembly that you would like to interop with JavaScript, in the browser or with Node.js."[^pack-drager]

```bash
wasm-pack build --target web       # or --target bundler / --target nodejs
wasm-pack test --headless --chrome
wasm-pack publish
```

### 1.3 Maintenance status — important for a migration decision

The original `rustwasm` GitHub org (which hosted the canonical "Rust and WebAssembly" book, and both tools) went essentially dormant after 2019 and was formally sunset by the Rust project in 2025.[^sunset] As of this writing:

- The canonical book at `rustwasm.github.io/docs/book/` still exists but is marked **"no longer maintained"** and points to a sunset notice.[^book]
- `wasm-bindgen` and `wasm-pack` were transferred to a **new `wasm-bindgen` GitHub org** with new maintainers; docs moved to `wasm-bindgen.github.io/wasm-pack` (the old `rustwasm.github.io/docs/wasm-pack` and interim `drager.github.io/wasm-pack` are both redirect stubs pointing forward).[^pack-drager]

**Implication for the migration:** the tools themselves are alive and actively used (this is a governance/hosting move, not an abandonment of the toolchain), but any internal documentation or onboarding material you write should point at `github.com/wasm-bindgen/wasm-bindgen` and `github.com/wasm-bindgen/wasm-pack` going forward, not the legacy `rustwasm.github.io` URLs, which will bit-rot.

---

## 2. `wasm32-unknown-unknown` vs `wasm32-wasip1`

These are the two Tier-2 targets you'll choose between; they answer different questions ("does this run in a browser with a JS host?" vs "does this run in a WASI-capable sandboxed runtime with syscalls?").

| | `wasm32-unknown-unknown` | `wasm32-wasip1` |
|---|---|---|
| **Host model assumed** | None — "unknown" OS, bring your own host bindings (typically `wasm-bindgen`) | WASI Preview 1 "syscalls" (`wasi_snapshot_preview1` imports) |
| **Toolchain requirement** | None beyond in-tree Rust/LLD; no C/C++ equivalent | Self-contained sysroot shipped by rustup (precompiled `wasi-libc`); no external compiler needed for normal use |
| **`std::fs`** | Always errors — no filesystem | Works, via WASI-defined file APIs (subject to the host's capability grants) |
| **`std::thread::spawn`** | Panics | Always errors (use `wasm32-wasip1-threads` for threads) |
| **Process spawning** | N/A / errors | Always errors |
| **`println!` / stdio** | No-ops (nothing to print to) | Works via WASI stdio |
| **`std::time`** | `Instant::now()`/`SystemTime::now()` panic without a shim | Works natively |
| **Randomness** | No entropy source without extra plumbing (see §6) | Works via WASI |
| **Default allocator** | `dlmalloc` | dlmalloc equivalent via wasi-libc |
| **Typical consumer** | Browsers / JS runtimes, via `wasm-bindgen` | Standalone WASM runtimes: Wasmtime, Wasmer, WASI-capable plugin hosts |
| **cfg gate** | `#[cfg(all(target_family = "wasm", target_os = "unknown"))]` | `#[cfg(all(target_os = "wasi", target_env = "p1"))]` (env cfg needs Rust ≥1.80) |
| **CI-tested upstream** | Not tested in rust-lang/rust CI | Tested in rust-lang/rust CI |

Sources: rustc platform-support docs for [`wasm32-unknown-unknown`][t-unknown] and [`wasm32-wasip1`][t-wasip1].

A third option, **`wasm32-wasip2`**, targets the WASI Preview 2 / Component Model interface (interface types, typed component composition instead of raw byte-buffer imports/exports) and is now itself Tier 2, shipped with every Rust release and CI-tested.[^wasip2] `wasm32-wasip1` is kept for historical/legacy-runtime compatibility; new WASI-targeting work should default to `wasip2` unless a specific host only speaks Preview 1.

**Rule of thumb for the migration:**
- Targeting a **browser or a JS-hosted embed** (Electron-style plugin, browser extension, in-page compute) → `wasm32-unknown-unknown` + `wasm-bindgen`/`wasm-pack`.
- Targeting a **standalone sandboxed runtime** (Wasmtime/Wasmer-hosted plugin system, server-side WASM execution, a CLI tool's plugin API) → `wasm32-wasip1` or `wasm32-wasip2`, no `wasm-bindgen` involved at all.

---

## 3. What does and doesn't work inside the WASM sandbox

The unifying fact: a WASM module starts with **zero ambient authority**. No filesystem, no network, no clock, no environment variables, no threads — unless the host explicitly grants each capability. This is a genuine capability-based sandbox, not merely a slower calling convention, and it is the reason WASM is attractive as a plugin isolation boundary in the first place.

### Works out of the box (both targets)
- Pure computation: arithmetic, string/byte processing, `core`/`alloc`-only algorithms, most `no_std`-compatible or `std`-light logic.
- Deterministic data structures (`Vec`, `HashMap` — note: **not randomized** the way native `HashMap` is, since there's no entropy source by default).
- Anything expressible without syscalls: parsers, codecs, math kernels, state machines, most business logic.

### Requires host cooperation / an explicit shim

| Capability | `wasm32-unknown-unknown` (browser) | `wasm32-wasip1`/`wasip2` (WASI host) |
|---|---|---|
| Filesystem | Not available; must be faked via JS (e.g. an in-memory FS, OPFS, IndexedDB behind a custom binding) | Available, gated by the host's WASI preopen/capability grants — a plugin only sees the directories the *host* explicitly hands it |
| Threads | Not available on stable without extra work — requires nightly + `-C target-feature=+atomics,+bulk-memory` + `build-std`, `SharedArrayBuffer`, and the page served with `Cross-Origin-Opener-Policy: same-origin` / `Cross-Origin-Embedder-Policy: require-corp` headers (this is what `wasm-bindgen-rayon` automates)[^rayon] | `wasm32-wasip1-threads` is a separate target; plain `wasip1`/`wasip2` spawn calls error |
| Network | None; must be proxied through JS `fetch`/WebSocket bindings you write | Depends on host-provided WASI sockets support (not universal) |
| Time | `Instant`/`SystemTime` panic; use the `web-time` crate (drop-in replacement backed by `Performance.now()`/`Date.now()`) or a custom import[^webtime] | Native, works directly |
| Randomness | `getrandom`'s default backend has no entropy source on raw `wasm32-unknown-unknown`; enable `getrandom`'s `js` feature, which assumes a `wasm-bindgen`-produced module and calls into `crypto.getRandomValues` — this is *why* the feature is off by default, since it silently doesn't work outside a wasm-bindgen host[^getrandom] | Native via WASI random syscalls |
| Process spawn / exec | Not applicable | Always errors under `wasip1` |

**Practical consequence:** any dependency in your migrated crate graph that reaches for real filesystem I/O, real threads, real system time, or OS randomness on the `unknown-unknown` target will fail to compile or panic at runtime unless it has wasm-aware feature flags (`getrandom/js`, `chrono`'s `wasmbind`, `web-time`, etc.). Audit the dependency tree for these before committing to the browser target — this is usually the largest source of migration friction, not the Rust code itself.

---

## 4. Deployment scenario A — in-browser (or JS-hosted) distribution

Pipeline: `cargo build --target wasm32-unknown-unknown` → `wasm-bindgen` (or the `wasm-pack` wrapper around it) → an npm package with a `.wasm` binary, generated JS glue, and `.d.ts` types → consumed like any other JS module (`import init, { my_fn } from "./pkg/mycrate.js"`).

This suits:
- A CLI/library tool getting a browser-based playground, docs-site demo, or in-page compute path (no server round-trip for the hot logic).
- Embedding the migrated logic inside an Electron or VS Code extension host (both are effectively "a browser").
- Publishing a JS-consumable NPM package so non-Rust downstream consumers get the same core logic without an FFI/native-binary distribution problem.

Constraints to plan for: bundle size (Rust's std brings weight; `wasm-opt`, `wee_alloc`/no custom allocator, and `--release` + LTO matter a lot here), the async/threading limitations above, and that every host interaction (files the user picks via `<input type=file>`, network calls, storage) has to be explicitly wired through `wasm-bindgen`'s JS-import mechanism — there's no ambient `std::fs`/`std::net` fallback to lean on.

## 5. Deployment scenario B — sandboxed plugin runtime

Pipeline: `cargo build --target wasm32-wasip1` (or `wasip2`) → a `.wasm` module with WASI imports → loaded by a host runtime (Wasmtime, Wasmer, or a framework like **Extism**, which wraps Wasmtime to give plugin authors in any language a unified guest/host API)[^extism] → the host grants exactly the filesystem/network/env capabilities it chooses via preopens/config, nothing more.

This suits distributing the migrated tool **as an embeddable plugin inside another application** — e.g. a host program defines a plugin interface, and the migrated Rust tool becomes one implementation compiled to a `.wasm` blob that the host loads and sandboxes, with no `wasm-bindgen`/JS layer involved at all. The Component Model (targeted by `wasm32-wasip2`) is the forward-looking version of this: typed, composable interfaces instead of raw byte-buffer ABI, and Wasmtime-class runtimes support it for exactly this out-of-browser use case.[^wasi2026] WASI 0.3 (early 2026) adds native async I/O (futures/streams) to components, closing a longstanding gap for I/O-heavy plugin workloads.[^wasi2026]

Key advantage over scenario A: your dependency tree doesn't need `wasm-bindgen`-flavored feature flags — `std::fs`, `std::time`, and (subject to the runtime) sockets work close to natively, because WASI *is* a syscall layer, just a capability-gated one. The tradeoff is you're now depending on the *host application* choosing to embed a WASI runtime and expose the capabilities your plugin needs — you don't control the host.

---

## 6. Known limitations for a crate that must also build natively for PyO3

This is the sharpest constraint in the migration: a crate that is both (a) a PyO3 native extension module and (b) a WASM target needs a **dual-target crate structure**, because the two build modes have genuinely incompatible requirements at the `Cargo.toml` level, not just different `#[cfg]` branches.

### 6.1 The core conflict

- PyO3's `extension-module` feature builds a `cdylib` that dynamically links against (or, with `abi3`, is ABI-compatible with) a **64-bit CPython interpreter** on the host OS.
- `wasm32-unknown-unknown`/`wasip1` is a **32-bit** target with no CPython present at all.

Attempting to compile a crate with `pyo3` as an unconditional dependency for `wasm32-unknown-unknown` fails outright — reported failures include architecture-mismatch errors ("your Rust target architecture (32-bit) does not match your python interpreter (64-bit)") and missing-CPython linker errors.[^pyo3-wasm] PyO3 has no supported story for embedding CPython inside a WASM sandbox; the interpreter itself would need porting (some ecosystem work exists around Pyodide, which recompiles *CPython itself* to WASM rather than making PyO3-linked extensions work standalone[^pyodide], but that's a different, much heavier proposition than "my library also targets WASM").

### 6.2 The structural fix: `crate-type = ["cdylib", "rlib"]` + feature-gated `pyo3`

The standard PyO3 pattern for making one crate usable both as a Python extension and a plain Rust library is:

```toml
[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = { version = "0.2x", optional = true }

[features]
extension-module = ["pyo3/extension-module"]
default = []
```

`rlib` lets downstream Rust code (`cargo test`, other crates, `wasm-bindgen` consumers) `use` the crate normally; `cdylib` is what maturin/setuptools-rust picks up to produce the `.so`/`.pyd`/`.dylib` Python extension. Critically, PyO3 itself must be **optional and feature-gated**, not an unconditional dependency — otherwise every `cargo build --target wasm32-unknown-unknown` invocation drags in PyO3's CPython-linking build-script logic regardless of whether you asked for it.[^pyo3-dual]

### 6.3 Recommended crate layout for this migration

```
mycrate/
├── Cargo.toml            # crate-type = ["cdylib", "rlib"]; pyo3 optional
├── src/
│   ├── lib.rs             # core logic, no pyo3/#[wasm_bindgen] here
│   ├── py_bindings.rs      # #[cfg(feature = "python")] — pyo3 #[pymodule]
│   └── wasm_bindings.rs    # #[cfg(target_family = "wasm")] — #[wasm_bindgen] exports
```

- Core algorithmic logic lives in plain, dependency-light Rust (`core`/`alloc`-friendly where feasible) so it's buildable under all three configurations.
- `pyo3` bindings are behind a `python` (or `extension-module`) Cargo feature, built with `maturin`/`setuptools-rust`, targeting the host triple (native `x86_64`/`aarch64`), never `wasm32-*`.
- `wasm-bindgen` bindings are gated on `target_family = "wasm"` (or a dedicated `browser`/`wasm` feature) and built with `wasm-pack`/`cargo build --target wasm32-unknown-unknown`, with `pyo3` compiled out entirely.
- Never enable both `extension-module` and a `wasm32-*` target in the same build invocation — they are mutually exclusive build *profiles* of the same source tree, not composable features. CI should run them as separate matrix legs (`cargo build --features python` on native, `wasm-pack build` / `cargo build --target wasm32-wasip1` with `--no-default-features`).

### 6.4 Secondary friction points to budget for

- **Cross-compiling PyO3's build script**: even for *native* cross builds (e.g. building the Python extension on CI for a different host triple than the runner), PyO3's `build.rs` needs `CARGO_CFG_TARGET_FAMILY` and related env vars set correctly; this is unrelated to WASM but commonly discovered at the same time a dual-target CI matrix is being set up, so budget review time for it.[^pyo3-wasm]
- **Time/date/UUID/random dependencies** used by the shared core logic need wasm-aware feature flags on *both* non-PyO3 build legs (`chrono`'s `wasmbind` feature, `uuid`'s `js` feature, `getrandom`'s `js` feature) — these are irrelevant to the PyO3 native build but mandatory for the `wasm32-unknown-unknown` leg, and forgetting them is a common source of "works natively, panics/fails to link in the browser" bugs. This is a `Cargo.toml` per-target-dependency / feature-unification problem, not a code problem — plan it in the same PR that sets up the crate-type split.

---

## 7. Summary decision table

| Goal | Target | Toolchain | `pyo3` in this build? |
|---|---|---|---|
| Ship a native Python extension | host triple | `maturin` / `setuptools-rust`, `pyo3/extension-module` | Yes |
| In-browser / npm-distributed compute | `wasm32-unknown-unknown` | `wasm-pack` + `wasm-bindgen` | No — feature-gated out |
| Plain Rust library consumer | host triple | `cargo build` (rlib) | No (optional dep, feature off) |
| Sandboxed plugin host (Wasmtime/Extism-style) | `wasm32-wasip1` or `wasm32-wasip2` | `cargo build --target wasm32-wasip{1,2}` | No — feature-gated out |

The single highest-leverage decision for a migration plan: **structure the crate now with `pyo3` as an optional, feature-gated dependency and `crate-type = ["cdylib", "rlib"]`**, so that adding a WASM build target later is a CI-matrix change, not a source-tree rewrite.

---

## Citations

[^bindgen-intro]: [Introduction — The `wasm-bindgen` Guide](https://rustwasm.github.io/docs/wasm-bindgen/introduction.html)
[^pack-drager]: [wasm-pack docs (redirect to new home)](https://drager.github.io/wasm-pack/) → current home at `wasm-bindgen.github.io/wasm-pack`
[^book]: [The Rust and WebAssembly Book](https://rustwasm.github.io/docs/book/)
[^sunset]: [Sunsetting the rustwasm GitHub org — Inside Rust Blog](https://blog.rust-lang.org/inside-rust/2025/07/21/sunsetting-the-rustwasm-github-org)
[t-unknown]: [`wasm32-unknown-unknown` — The rustc book](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html)
[t-wasip1]: [`wasm32-wasip1` — The rustc book](https://doc.rust-lang.org/rustc/platform-support/wasm32-wasip1.html)
[^wasip2]: [`wasm32-wasip2` — The rustc book](https://doc.rust-lang.org/nightly/rustc/platform-support/wasm32-wasip2.html)
[^rayon]: [wasm-bindgen-rayon (GitHub)](https://github.com/RReverser/wasm-bindgen-rayon)
[^webtime]: [`web-time` crate — drop-in `std::time` replacement for wasm32-unknown-unknown](https://crates.io/crates/web-time)
[^getrandom]: [`getrandom` issue #268 — runtime crash on wasm32-unknown-unknown even with `js` feature](https://github.com/rust-random/getrandom/issues/268)
[^extism]: [Extism — cross-language WASM plugin framework built on Wasmtime](https://github.com/topics/wasmtime)
[^wasi2026]: [Rust Project Goals 2026 — Wasm Components](https://rust-lang.github.io/rust-project-goals/2026/wasm-components.html); [WASI and the WebAssembly Component Model: Current Status](https://eunomia.dev/blog/2025/02/16/wasi-and-the-webassembly-component-model-current-status/)
[^pyo3-wasm]: [PyO3 issue #3261 — error compiling to wasm32-unknown-unknown / wasm32-unknown-emscripten](https://github.com/PyO3/pyo3/issues/3261); [PyO3 issue #1221 — cross-compiling wasm32-unknown-unknown](https://github.com/PyO3/pyo3/issues/1221)
[^pyo3-dual]: [PyO3 discussion #2271 — a single library crate for Rust and Python](https://github.com/PyO3/pyo3/discussions/2271); [PyO3 Building and Distribution guide](https://pyo3.rs/v0.13.2/building_and_distribution.html)
[^pyodide]: [Rust/PyO3 Support in Pyodide — Pyodide blog](https://blog.pyodide.org/posts/rust-pyo3-support-in-pyodide/)
