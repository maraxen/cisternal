<!-- ref-crate-versions: orx-parallel=3.4.0; checked=2026-08-13 -->

# orx-parallel: Technical Reference

**Crate:** `orx-parallel` (part of the `orxfun/orx-*` ecosystem)
**Current version (crates.io, checked 2026-08-13):** 3.4.0
**License:** MIT OR Apache-2.0
**Repo:** https://github.com/orxfun/orx-parallel

## 1. What problem it solves

`orx-parallel` is a "high performance, configurable and expressive" parallel computation library for Rust. It targets the same job as rayon — turning a sequential iterator-style computation into a parallel one — but positions itself around three specific gaps it claims rayon leaves open:

- **Performance on non-trivial iterator chains.** The crate's own benchmarks (in its README/docs) show it winning by a wide margin on chained operations (`.map().filter().reduce()`, `.flat_map().collect()`) and especially on **early-exit** operations (`find`, `any`, `all`), where rayon's task-splitting model does more wasted work before it can stop. Example figures quoted in the docs: `.filter().collect()` ~0.66x sequential time (orx-parallel) vs ~4.43x (rayon-relative slowdown in one benchmark framing); `.flat_map().find()` 27.66 µs vs rayon's 127.37 µs.
- **Configurability.** Thread count, chunk size, iteration order, and the underlying thread pool are all first-class, per-call configuration knobs (`num_threads()`, `chunk_size()`, `iteration_order()`, `with_pool()`/`with_runner()`) rather than global/one-size-fits-all settings.
- **Portability beyond std/rayon's threading assumptions.** It works in `no_std` contexts (falling back to a `SequentialPool`) and abstracts over the underlying thread pool via a `ParThreadPool` trait, so it can run on native OS threads, rayon-core's pool, or third-party pools (`scoped_threadpool`, `scoped-pool`, `yastl`, `pond`, `poolite`) without changing call-site code.

It also extends the iterator-parallelism idea to cases rayon doesn't cover directly: fallible iterators that short-circuit on `Err`/`None` (`ParIterResult`, `ParIterOption`), per-thread mutable state without unsafe (`using()`/`using_clone()`), and parallel traversal of non-linear/recursive structures like trees and graphs (`IntoParIterRec`).

## 2. API comparison to rayon

The surface API is deliberately rayon-shaped — same "sprinkle a method call on your iterator" ergonomics:

| rayon | orx-parallel |
|---|---|
| `.par_iter()` | `.par()` |
| `.into_par_iter()` | `.into_par()` |
| `ParallelIterator` trait | `ParIter` trait |
| `IntoParallelIterator` trait | `IntoParIter` trait |
| `map`, `filter`, `filter_map`, `flat_map`, `reduce`, `sum`, `min_by_key`, `find`, `any`, `all`, `for_each`, `collect` | same names, same chaining style |

Differences from rayon's surface:

- **`iter_into_par()`** — any ordinary sequential `Iterator` (not just rayon-aware collections) can be turned into a parallel one, at some performance cost for trivial per-element work.
- **`Parallelizable`** trait — lets a source spawn multiple parallel iterators without being consumed.
- **`using()` / `using_clone()`** — supply a per-thread mutable value (e.g., a seeded RNG) that the closure receives explicitly, rather than requiring `Send + Sync` shared state or unsafe cells. Example:
  ```rust
  input
      .into_par()
      .using(|t_idx| ChaCha20Rng::seed_from_u64(42 * t_idx as u64))
      .map(|rng, i| fibonacci((i % 50) + 1) % 10)
      .sum()
  ```
- **`into_fallible_result()` / `into_fallible_option()`** — convert `ParIter<Item = Result<T, E>>` / `ParIter<Item = Option<T>>` into iterators that short-circuit on first `Err`/`None`, giving `?`-like early exit in a parallel context (rayon requires more manual handling for this).
- **`ParCollectInto`** — pluggable collection targets beyond `Vec` (e.g. `SplitVec`, `FixedVec`).
- **Configuration is chained per-call** rather than pool-global: `.num_threads(n)`, `.chunk_size(c)`, `.iteration_order(...)`, `.with_pool(&pool)` / `.with_runner(...)` — all composable on the same iterator chain, e.g.:
  ```rust
  let sum = inputs.par().with_pool(&rayon_pool).num_threads(8).sum();
  ```
- **`IntoParIterRec`** has no rayon equivalent — parallel iteration over recursive/tree/graph structures via an explicit "extend" closure describing how to discover more work from each node.

## 3. Parallel execution model

**Not a classic work-stealing deque scheduler like rayon's (which uses per-thread Chase-Lev deques and task splitting/joining).** Instead, orx-parallel uses a **pull-based, chunked, lock-free concurrent-iterator model**:

1. A single closure (the whole computation, not a per-task unit) is handed to every worker thread up front — there's no per-element or per-split task-spawn overhead.
2. Each worker repeatedly **pulls a chunk of elements** from a shared, lock-free concurrent iterator over the input.
3. Idle threads naturally pull more chunks as they finish, which yields work-stealing-*like* load balancing (fast threads end up doing more of the work) without an actual steal protocol between thread-local queues. (Docs.rs's page for the executor trait does describe this as "implementing work-stealing," but the mechanism described everywhere else — dynamic chunk-pulling from a shared iterator — is architecturally a pull/chunking model, not deque-based stealing; treat "work-stealing" here as a result/effect, not the mechanism.)
4. **Chunk size** is the main lever balancing per-chunk overhead against load-imbalance from heterogeneous task cost, controlled via the `ChunkSize` enum:
   - `Auto` — dynamic heuristic (default)
   - `Exact(c)` — fixed chunk size
   - `Min(c)` — at least `c` elements per pulled chunk (executor may pull more)
5. **Iteration order** is configurable independently of the chunking: `Ordered` (default, preserves input order in output) vs `Arbitrary` (may allow faster execution by not reassembling order).
6. **Thread count**: `NumThreads::Auto` or `NumThreads::Max(n)`; `Max(1)` degenerates to sequential execution in-process (useful for testing/debugging without branching code).

### Thread pool abstraction

Execution is decoupled from *where* the threads come from via the `ParThreadPool` trait:
- `StdDefaultPool` — native OS threads (default under the `std` feature)
- `SequentialPool` — single-threaded, for `no_std`
- Optional adapters for `rayon-core`, `scoped_threadpool`, `scoped-pool`, `yastl`, `pond`, `poolite`

Swapping pools (e.g. to reuse an app's existing rayon-core pool) is a `.with_pool(&pool)` call, not a rewrite.

### Global vs per-call limits

`ORX_PARALLEL_MAX_NUM_THREADS` environment variable caps threads globally across all computations in the process; `.num_threads(n)` caps a specific call (bounded by the global cap if set).

## 4. When to prefer orx-parallel over rayon

Prefer orx-parallel when:
- The computation is a **longer chained pipeline** (`map`/`filter`/`flat_map`/`reduce` combinations) rather than a single trivial parallel op — the benchmarked gap over rayon widens with chain complexity.
- The workload does **early-exit** searches (`find`, `any`, `all`) — pull-based chunking wastes less work past the exit point than rayon's split/join task tree in the crate's own benchmarks.
- You need **fine control** over chunk size, iteration order, or thread count per call site, or want to **reuse an existing thread pool** (including rayon's own `rayon-core::ThreadPool`, via the pool abstraction) instead of standing up a second global pool.
- You need **`no_std`** support, or portability to non-rayon thread-pool ecosystems already in use in a project (`scoped_threadpool`, `yastl`, etc.).
- You want built-in **fallible short-circuiting** (`Result`/`Option` early exit) or **safe per-thread mutable state** without hand-rolled `thread_local!`/unsafe.
- You need to parallelize over **recursive/non-linear structures** (trees, graphs) directly.

Rayon (or plain sequential code) may still be preferable when:
- The per-element computation is trivial — parallelization overhead (of either library) can lose to sequential execution; measure before parallelizing either way.
- The codebase already has deep rayon integration (e.g., using `rayon::join`/`scope` primitives beyond iterator adapters, or libraries whose parallel APIs are rayon-native) where introducing a second parallel-execution abstraction adds complexity without a proven bottleneck.
- You want the most battle-tested, widest-ecosystem option — rayon is far more widely used/audited and has broader third-party integration (numpy-rust bridges, etc.).

## 5. Using it in a pyo3-exposed Rust function

The integration pattern is the same one used for rayon in PyO3 extensions: **release the GIL before entering the parallel region**, do the CPU-bound work without touching Python objects while parallel, and only re-acquire the GIL (per-thread, via `Python::with_gil`) if a worker genuinely needs to touch Python objects.

```rust
use pyo3::prelude::*;
use orx_parallel::*;

/// Parallel sum of squares over a Rust-owned Vec<i64>, exposed to Python.
#[pyfunction]
fn sum_of_squares(py: Python<'_>, values: Vec<i64>) -> i64 {
    // Release the GIL for the duration of the parallel computation —
    // no Python objects are touched inside the closure, so this is safe
    // and lets other Python threads run concurrently.
    py.allow_threads(|| {
        values
            .into_par()               // orx-parallel: into_par(), not rayon's into_par_iter()
            .map(|x| x * x)
            .sum()
    })
}

/// Parallel filter+map with explicit chunk/thread configuration.
#[pyfunction]
fn filtered_transform(py: Python<'_>, values: Vec<f64>, threshold: f64) -> Vec<f64> {
    py.allow_threads(|| {
        values
            .into_par()
            .num_threads(4)
            .chunk_size(ChunkSize::Min(256))
            .filter(|x| *x > threshold)
            .map(|x| x.sqrt())
            .collect()
    })
}

#[pymodule]
fn my_extension(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sum_of_squares, m)?)?;
    m.add_function(wrap_pyfunction!(filtered_transform, m)?)?;
    Ok(())
}
```

Key points for the pyo3 boundary:

- **Convert Python inputs to owned Rust data (or extract what you need) before entering the parallel closure.** `Vec<i64>`/`Vec<f64>` above are already owned, GIL-independent data by the time `allow_threads` runs — this is what makes the release safe. If you must operate on `Py<T>`/`PyObject` handles inside the parallel region, each worker must re-acquire the GIL locally via `Python::with_gil(|inner_py| { ... })` for just that access — never hold the outer `py: Python<'_>` token across the `allow_threads` boundary into worker closures, and never let a worker block waiting for the GIL while the calling thread also waits on the worker (that's the classic deadlock this pattern exists to avoid).
- **`py.allow_threads(...)`** is the pyo3 API (renamed `Python::detach` in pyo3 ≥ 0.26, reflecting free-threaded-Python support) — wrap the *entire* orx-parallel call chain in it, mirroring exactly how the pyo3 guide recommends wrapping rayon calls.
- **`Cargo.toml`**: add both `pyo3` and `orx-parallel` as dependencies; no special feature flags are needed on the orx-parallel side for this pattern (the default `std` feature pulls in `StdDefaultPool`, which is what you want inside a normal CPython extension). If you want to reuse an existing rayon-core pool inside a mixed rayon/orx-parallel codebase, pass it explicitly with `.with_pool(&pool)`.
- **GIL caveat applies identically to orx-parallel as to rayon**: if the closure passed to `into_par()`/`.map()`/etc. calls back into Python without releasing/reacquiring the GIL correctly, you get no real parallelism (all worker threads serialize on the GIL) — or a deadlock if a worker blocks on the GIL while the outer thread is also blocked. Free-threaded CPython (3.14+, no GIL) removes this constraint entirely.

## Citations

- **docs.rs** — API reference (traits `ParIter`, `IntoParIter`, `ParIterResult`, `ParIterOption`, `ParIterUsing`, `IntoParIterRec`, `ParThreadPool`, `ParallelExecutor`, `ChunkSize`, `NumThreads`, `IterationOrder`): https://docs.rs/orx-parallel/latest/orx_parallel/
- **crates.io** — package metadata, version 3.4.0, description, license: https://crates.io/crates/orx-parallel
- **GitHub repo / README** — problem statement, benchmark tables, usage examples, thread-pool integrations: https://github.com/orxfun/orx-parallel
- **PyO3 parallelism guide** — GIL-release pattern (`allow_threads`, `Python::with_gil`, rayon example this doc's pattern mirrors): https://pyo3.rs/v0.23.4/parallelism.html / canonical source: https://github.com/PyO3/pyo3/blob/main/guide/src/parallelism.md
