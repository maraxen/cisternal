<!-- ref-crate-versions: rayon=1.12.0; checked=2026-08-13 -->

# Rayon: Data Parallelism in Rust — Technical Reference

*Covers: the parallel iterator API, `join`/`scope`, the work-stealing thread pool model, PyO3 integration (GIL release via `Python::allow_threads`/`detach`), thread pool sizing inside a Python-embedded process, and patterns for parallelizing a migrated hot path.*

---

## 1. What Rayon Is

Rayon is a lightweight, data-parallelism library for Rust. Its central promise, from the project README, is that **"if your code compiles, it typically does the same thing it did before"** — converting sequential code to parallel code is meant to be a small, local edit (`.iter()` → `.par_iter()`), and Rayon *guarantees data-race freedom* at compile time via Rust's `Send`/`Sync` bounds. It uses a dynamic work-stealing scheduler that only parallelizes work when idle CPU capacity is actually available, so well-written Rayon code degrades gracefully to sequential execution rather than thrashing on oversubscription.

Rayon is dual-licensed MIT/Apache-2.0, requires Rust ≥ 1.85.0 as of the current release line, and is published as [`rayon` on crates.io](https://crates.io/crates/rayon) with API docs on [docs.rs](https://docs.rs/rayon/latest/rayon/).

---

## 2. Core Parallel Iterator API

### 2.1 `par_iter` and the `ParallelIterator` trait

The most common entry point is turning a sequential iterator into a parallel one:

```rust
use rayon::prelude::*;

fn sum_of_squares(input: &[i32]) -> i32 {
    input.par_iter()
         .map(|&i| i * i)
         .sum()
}
```

This mirrors the standard `Iterator` API almost method-for-method: `map`, `filter`, `fold`, `for_each`, `find_any`, `try_fold`, `reduce`, and terminal consumers like `sum()`, `collect()`, and `count()` are all available on the `ParallelIterator` trait. Rayon's crate root mirrors the standard library's module structure with parallel counterparts — `rayon::iter` holds the core traits, and `rayon::collections`, `rayon::vec`, `rayon::slice`, `rayon::option`, `rayon::result`, and `rayon::range` provide parallel iteration over the corresponding standard types. `rayon::prelude::*` is the conventional single import that brings the relevant traits (`ParallelIterator`, `IndexedParallelIterator`, `IntoParallelIterator`, `IntoParallelRefIterator`, etc.) into scope.

Beyond the iterator adaptor chain, Rayon exposes a few purpose-built high-level operations:
- **`par_sort`** — parallel, in-place sorting of slices/`Vec`s.
- **`par_extend`** — efficient parallel population of a collection from a parallel producer.
- **`IndexedParallelIterator`** — a refinement of `ParallelIterator` for iterators with a known, exact length, unlocking operations like `par_chunks`, `zip`, and `enumerate` that need to reason about positions.

Error handling composes the same way it does with sequential iterators: collecting into `Result<Vec<T>, E>` (`.collect::<Result<Vec<_>, _>>()`) short-circuits on the first error encountered across the parallel workers, so a migrated hot path that used `?` in a loop can usually keep that error-propagation shape.

Source: [Rayon crate docs, docs.rs](https://docs.rs/rayon/latest/rayon/); [rayon-rs/rayon README](https://github.com/rayon-rs/rayon).

### 2.2 `join` — manual fork-join for two tasks

```rust
pub fn join<A, B, RA, RB>(oper_a: A, oper_b: B) -> (RA, RB)
where
    A: FnOnce() -> RA + Send,
    B: FnOnce() -> RB + Send,
    RA: Send,
    RB: Send,
```

`join` takes two closures and runs them, *potentially* in parallel, returning both results as a tuple. The classic example is a parallel quicksort:

```rust
rayon::join(|| quick_sort(lo),
            || quick_sort(hi));
```

Mechanically: when `join` is called on a Rayon worker thread, the current thread executes closure `A` immediately while making closure `B` available for another idle thread to steal. If nothing steals `B` before `A` finishes, the original thread just runs `B` itself — so in the worst case (no idle threads) `join` degrades to sequential execution with only the cost of the bookkeeping, not two separate scheduler round-trips. Called from *outside* the Rayon pool (e.g. the initial call from `main`), the calling thread blocks until both closures complete.

Two operational notes worth carrying into a migration:
- **CPU-bound only.** The docs are explicit that `join`'s closures are assumed to be CPU-bound; if a closure performs blocking I/O, the paired closure may not get scheduled promptly and overall latency suffers.
- **No cross-closure blocking.** Don't have closure `A` block on a channel waiting for closure `B` (or vice versa) — this risks deadlock, since Rayon does not guarantee `B` is actually running concurrently with `A`.
- **Panics propagate.** Both closures always run to completion regardless of panics; if only one panics, that panic is re-raised in the caller; if both panic, the first closure's panic wins.

Source: [`rayon::join` docs, docs.rs](https://docs.rs/rayon/latest/rayon/fn.join.html).

### 2.3 `scope` — structured concurrency for N tasks

```rust
pub fn scope<'scope, OP, R>(op: OP) -> R
where
    OP: FnOnce(&Scope<'scope>) -> R + Send,
    R: Send,
```

`scope` creates a fork-join context for an arbitrary (not just two) number of tasks. The closure receives a `&Scope` handle; calling `scope.spawn(...)` inside it queues additional closures, which may themselves spawn nested tasks or scopes. `scope()` does not return until **every** spawned task — including tasks spawned by other spawned tasks — has completed. This gives you structured concurrency: cleanup is deterministic, and stack data borrowed into spawned closures is guaranteed to outlive them because the scope can't exit while they're still running.

Guidance from the docs: **prefer `join` (or, better still, a parallel iterator) where possible** — `scope` requires heap-allocating its tasks, whereas `join`'s two-closure case can stay stack-allocated. Reach for `scope` when the task count is dynamic/unbounded or the recursion structure doesn't cleanly decompose into pairs. As with `join`, panics in the closure or in any spawned task propagate to the `scope()` caller once all tasks have finished.

Source: [`rayon::scope` docs, docs.rs](https://docs.rs/rayon/latest/rayon/fn.scope.html).

---

## 3. The Work-Stealing Thread Pool Model

Rayon's scheduler is a classic **work-stealing** design, tracing its lineage to the Cilk project (MIT, late 1990s) — the crate's name is a nod to that heritage.

**Mechanics:**
- Each worker thread owns a local double-ended queue (deque) of pending tasks.
- When a worker calls `join(a, b)` (or `Scope::spawn`, or a parallel-iterator split), task `b` is pushed onto that worker's own deque and task `a` starts executing immediately on the same thread.
- Other idle worker threads, when they run out of their own local work, search other threads' deques and **steal** tasks from them (typically from the far end of the deque, to minimize contention with the owning thread's own LIFO pop).
- When the original worker finishes `a`, it checks whether `b` was stolen. If not, it just runs `b` itself with no extra scheduling cost. If it was stolen, the worker goes hunting for other work.

This gives Rayon automatic load balancing without a central scheduler or explicit task assignment: parallelism only actually materializes when there's a genuinely idle thread to do the stealing, so cheap/fine-grained `join` calls on a fully-busy pool cost little more than a sequential call would.

**Sizing and configuration:**
- By default the *global* thread pool spawns one worker per logical CPU core.
- The count can be overridden with the `RAYON_NUM_THREADS` environment variable, or programmatically via `rayon::ThreadPoolBuilder::new().num_threads(n).build_global()`.
- `ThreadPoolBuilder::build()` returns a `Result<ThreadPool, ThreadPoolBuildError>` for constructing an independent, non-global pool (useful when you need more than one differently-sized pool in a process, or want isolation between subsystems).
- `build_global()` initializes the process-wide default pool; it can only succeed **once** — a second call errors. If you never call it explicitly, the global pool is lazily initialized with default settings on first use.
- `ThreadPoolBuilder` also exposes `stack_size()` for worker stack sizing, and the pool supports `broadcast()` (run a closure on every worker thread) alongside `spawn()`/`spawn_fifo()` for fire-and-forget, `'static`-lifetime tasks queued onto the global pool.
- `join_context()` is a variant of `join` that additionally tells each closure whether it is actually running on a separate thread — useful for closures that want to adapt their own internal chunking based on whether real parallelism materialized.

Source: [`rayon::ThreadPoolBuilder` docs, docs.rs](https://docs.rs/rayon/latest/rayon/struct.ThreadPoolBuilder.html); [rayon-rs/rayon FAQ](https://github.com/rayon-rs/rayon/blob/main/FAQ.md); [rayon-rs/rayon README](https://github.com/rayon-rs/rayon).

---

## 4. Rayon Inside PyO3: GIL Release and Thread Pool Sizing

This is the section that matters most when Rayon is powering a Python-extension hot path rather than a pure-Rust binary.

### 4.1 Why the GIL matters here at all

CPython's Global Interpreter Lock (GIL) allows only one thread to execute Python bytecode at a time. Spawning OS threads from Python normally buys you nothing for CPU-bound work, because they all still serialize on the GIL. PyO3's escape hatch is `Python::allow_threads` (the method has been **renamed `Python::detach`** in current/`main`-branch PyO3, with `Python::with_gil`'s counterpart correspondingly named `Python::attach`; check your pinned PyO3 version's docs for which name applies — `allow_threads`/`with_gil` for ≤0.23.x, `detach`/`attach` from the renaming onward).

`Python::allow_threads` (or `detach`) temporarily releases the GIL for the duration of a closure, letting other Python threads (and, critically, Rayon's own worker threads) actually run concurrently on multiple cores.

### 4.2 Pattern A — pure-Rust parallelism, no Python objects touched

If the parallel work never touches a `Py<T>`/`PyObject`/`&PyAny`, no GIL management is needed inside the parallel section at all — Rayon just runs as it would in a pure-Rust program. PyO3's own `word-count` example does exactly this:

```rust
use pyo3::prelude::*;
use rayon::str::ParallelString;
use rayon::iter::ParallelIterator;

fn count_line(line: &str, needle: &str) -> usize {
    line.split(' ').filter(|&w| w == needle).count()
}

#[pyfunction]
fn search(contents: &str, needle: &str) -> usize {
    contents
        .par_lines()
        .map(|line| count_line(line, needle))
        .sum()
}
```

Here `contents: &str` was already extracted from the Python string argument by PyO3's function-call machinery before the closure runs, so the `par_lines()` parallel section is plain Rust over owned/borrowed Rust data — nothing GIL-related to manage.

### 4.3 Pattern B — releasing the GIL around a long sequential (or Rayon) call

If you have an existing Rust function you want callable in parallel *from Python* (e.g. via a `ThreadPoolExecutor`), wrap it in `allow_threads`/`detach`:

```rust
#[pyfunction]
fn search_sequential_allow_threads(py: Python<'_>, contents: &str, needle: &str) -> usize {
    py.allow_threads(|| search_sequential(contents, needle))
}
```

```python
from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=2)
f1 = executor.submit(search_sequential_allow_threads, contents, needle)
f2 = executor.submit(search_sequential_allow_threads, contents, needle)
r1, r2 = f1.result(), f2.result()
```

Without the `allow_threads`/`detach` wrapper, the Rust call would hold the GIL for its entire duration and the two Python-level `ThreadPoolExecutor` workers would simply serialize on it — no wall-clock benefit despite "looking" multithreaded from Python. PyO3's own benchmark of this pattern (word-count example, `pytest-benchmark`) shows the GIL-released sequential version running roughly 2× faster under two Python threads than a single-threaded run, and the pure-Rayon parallel version outperforming both by a wider margin still.

### 4.4 Pattern C — Rayon workers that themselves need to touch Python objects

This is the trickiest and most deadlock-prone case: spawning Rayon tasks that operate on `Py<T>` instances.

```rust
use pyo3::prelude::*;
use rayon::iter::{IntoParallelRefIterator, ParallelIterator};

#[pyclass]
struct UserID { id: i64 }

let allowed_ids: Vec<bool> = Python::with_gil(|outer_py| {
    let instances: Vec<Py<UserID>> =
        (0..10).map(|x| Py::new(outer_py, UserID { id: x }).unwrap()).collect();

    outer_py.allow_threads(|| {
        instances.par_iter().map(|instance| {
            Python::with_gil(|inner_py| {
                instance.borrow(inner_py).id > 5
            })
        }).collect()
    })
});
```

Two rules fall out of this example, and both are load-bearing:

1. **GIL tokens are not `Send`.** You cannot capture the outer `py: Python<'_>` token into a Rayon closure that runs on another thread. Each worker thread must independently call `Python::with_gil` (or `Python::attach` in renamed versions) to obtain its *own* token before touching any Python object.
2. **Always wrap the thread-spawning call in `allow_threads`/`detach`.** If the *outer* thread (the one that owns the GIL and is waiting for Rayon's `par_iter()`/`join`/`scope` call to return) does not release the GIL first, you get a classic deadlock: a Rayon worker blocks trying to acquire the GIL inside `Python::with_gil`, while the outer thread — which currently holds the GIL — spins forever waiting for that worker's result. `allow_threads`/`detach` breaks the cycle by having the outer thread give up the GIL *before* the workers need it.

Also worth flagging explicitly (PyO3's guide underlines this): if the spawned worker threads acquire the GIL and then **hold** it for their entire execution (rather than releasing it again once they're done touching Python state), you will not see real multi-core speedup from Rayon at all — you've just re-serialized the "parallel" work behind the GIL, one thread at a time. The exceptions are (a) workloads where the per-worker Python-touching portion is a small fraction of the total work, so most time is spent GIL-free, or (b) running under **free-threaded Python** (no-GIL builds, officially supported starting Python 3.14 per the PyO3 guide), where this constraint disappears.

### 4.5 Thread pool sizing considerations in a Python-embedded process

A few considerations specific to running Rayon *inside* a Python extension module rather than a standalone binary:

- **The global pool initializes lazily and once.** The first `par_iter()`/`join`/`scope` call anywhere in the process spins up Rayon's global pool sized to the logical core count (or `RAYON_NUM_THREADS`). If your extension is loaded into a long-lived Python process (a notebook kernel, a web worker, a service), that sizing decision is made once for the process's lifetime — a later `ThreadPoolBuilder::build_global()` call to change it will simply error if anything already used the default pool first. If you need non-default sizing, call `build_global()` proactively during module init, before any parallel call.
- **Don't let Python-level and Rayon-level parallelism multiply.** If your Python caller *also* fans work out across multiple OS threads or processes (e.g. a `ThreadPoolExecutor` with `max_workers=8`, or multiprocessing workers) and each of those calls into a Rayon hot path that itself claims a full core-count-sized pool, you can oversubscribe the machine — `N` Python-level workers × `M`-core Rayon pool each. In that topology, either size Rayon's pool down (`num_threads` scaled by expected concurrent callers) or keep parallelism at exactly one layer: let Python drive the fan-out and keep the Rust side sequential-per-call (Pattern B), or let Rayon drive the fan-out and keep the Python side single-threaded per call (Pattern A/C).
- **Leaving Python's own thread a core.** In a service that must stay responsive to other Python threads (e.g. handling other requests) while a Rayon hot path runs, consider sizing the pool to `available_cores - 1` (or an explicit fixed count via `RAYON_NUM_THREADS`) rather than defaulting to "all cores," so the GIL-holding thread isn't starved of scheduling time by Rayon workers.
- **Prefer a scoped, non-global pool for isolation** when the extension is a library embedded into unpredictable host processes (rather than a standalone application) — a private `ThreadPool` built via `ThreadPoolBuilder::build()` avoids fighting other in-process users of Rayon's global pool over `build_global()`'s single-initialization constraint, at the cost of managing that pool's lifetime yourself.

Source: [PyO3 Parallelism guide, v0.23.4](https://pyo3.rs/v0.23.4/parallelism.html); [PyO3 Parallelism guide, main/dev branch — `detach`/`attach` naming](https://github.com/PyO3/pyo3/blob/main/guide/src/parallelism.md); [`pyo3::Python` marker docs](https://docs.rs/pyo3/latest/pyo3/marker/struct.Python.html).

---

## 5. Common Patterns for Parallelizing a Migrated Hot Path

These are the shapes that come up repeatedly when a Python (or sequential-Rust) hot path is rewritten as a PyO3-exposed Rust function:

1. **Extract-then-parallelize.** Pull the needed data out of Python objects (via PyO3's automatic argument extraction, e.g. `contents: &str`, `data: Vec<f64>`, `arr: PyReadonlyArray1<f64>` for NumPy) *before* entering the parallel section, so the `par_iter()`/`join` body operates on plain owned/borrowed Rust data with no GIL involvement (Pattern A, §4.2). This is almost always the fastest and simplest option, and should be the default target shape for a migration.

2. **Wrap the whole call in `allow_threads`/`detach` even for single-call parallelism.** Even when a `#[pyfunction]` body is *itself* the thing calling `par_iter()`, wrap the parallel section in `py.allow_threads(|| { ... })` — releasing the GIL costs nothing when nothing needs it, but it means the calling Python thread doesn't block other Python threads while your Rust code (and its Rayon workers) run. This is cheap insurance and should be close to a default in any migrated hot path, not just the "run the same function from two Python threads" scenario the docs demonstrate.

3. **Chunk before you parallelize, not inside the inner loop.** For a migrated loop over a large collection, prefer `par_chunks`/`with_min_len`/`with_max_len` (from `IndexedParallelIterator`) over raw per-element `par_iter().map()` when per-element work is very cheap — this amortizes the work-stealing/task-dispatch overhead across a batch instead of paying it per element. Measure before tuning; Rayon's default splitting heuristics are usually good enough for a first pass.

4. **`join` for recursive divide-and-conquer, `scope` for dynamic fan-out, iterators for everything else.** If the migrated code was a recursive algorithm (sort, tree walk, matrix decomposition), reach for `join` first — it's the cheapest primitive and maps directly onto the classic "split, recurse in parallel, combine" shape. Reach for `scope` only when the task count isn't known up front or doesn't decompose into pairs. Default to a parallel iterator adaptor chain whenever the migrated code was already a `for`/`map`/`filter`/`fold` loop over a collection — it's both the simplest to write and the easiest to review against the original sequential version.

5. **Keep errors flowing through `collect::<Result<_, _>>()`.** If the original sequential hot path used `?` inside a loop and returned early on the first error, preserve that behavior with `.collect::<Result<Vec<_>, E>>()` over a parallel iterator that yields `Result<T, E>` per item — Rayon short-circuits collection on the first `Err` it observes, closely mirroring (though not identically ordering) the sequential early-return.

6. **Never smuggle a `Python<'_>` token into a spawned closure.** If the migrated hot path's parallel workers need to read/write Python objects (Pattern C, §4.4), each closure must call `Python::with_gil`/`Python::attach` itself. This is the single most common source of "works in testing, deadlocks under load" bugs when porting Python-object-touching code into Rayon.

7. **Benchmark against the sequential-Rust baseline, not just the Python baseline.** A migration's real payoff has two independent components — Rust vs. Python (often the larger factor), and sequential-Rust vs. parallel-Rust (Rayon's contribution). Keep both a `#[pyfunction]` sequential Rust version and the Rayon-parallel version benchmarked side by side (as PyO3's own `word-count` example's `pytest-benchmark` suite does) so a regression in parallel speedup doesn't get misattributed to "the Rust rewrite wasn't worth it."

8. **Size the pool once, near module import, if you're overriding defaults.** If the target deployment environment (container CPU limits, a shared multi-tenant host) makes the default core-count sizing wrong, call `ThreadPoolBuilder::num_threads(n).build_global()` during your extension module's Python-visible init function (or lazily on first real use, guarded so it only ever runs once) rather than leaving it to Rayon's lazy default — see the oversubscription note in §4.5.

Sources: [Rayon crate docs](https://docs.rs/rayon/latest/rayon/); [`rayon::join`](https://docs.rs/rayon/latest/rayon/fn.join.html); [`rayon::scope`](https://docs.rs/rayon/latest/rayon/fn.scope.html); [PyO3 Parallelism guide](https://pyo3.rs/v0.23.4/parallelism.html); [PyO3 word-count example](https://github.com/PyO3/pyo3/blob/main/examples/word-count/src/lib.rs).

---

## 6. Quick Reference

| Need | Reach for |
|---|---|
| Turn a `for`/`.iter()` loop over a collection into parallel work | `par_iter()` + `ParallelIterator` adaptors (`map`, `filter`, `fold`, `sum`, `collect`) |
| Sort a large slice/`Vec` in parallel | `par_sort()` |
| Two independent recursive subproblems (divide & conquer) | `rayon::join(a, b)` |
| Unknown/dynamic number of parallel subtasks | `rayon::scope(|s| { s.spawn(...); ... })` |
| Fire-and-forget task with `'static` lifetime, no need to wait | `rayon::spawn()` / `spawn_fifo()` |
| Run something on every worker thread | `ThreadPool::broadcast()` |
| Control global pool size | `RAYON_NUM_THREADS` env var, or `ThreadPoolBuilder::num_threads(n).build_global()` (once, at startup) |
| Independent, isolated pool (library embedded in another host) | `ThreadPoolBuilder::new().build()` (non-global) |
| Release the GIL around Rust work called from Python | `Python::allow_threads(...)` (renamed `Python::detach(...)` in newer PyO3) |
| Re-acquire the GIL inside a Rayon worker to touch Python objects | `Python::with_gil(...)` (renamed `Python::attach(...)` in newer PyO3) |

---

## Sources

- [Rayon — crate-level documentation, docs.rs](https://docs.rs/rayon/latest/rayon/)
- [`rayon::join` function documentation, docs.rs](https://docs.rs/rayon/latest/rayon/fn.join.html)
- [`rayon::scope` function documentation, docs.rs](https://docs.rs/rayon/latest/rayon/fn.scope.html)
- [`rayon::ThreadPoolBuilder` documentation, docs.rs](https://docs.rs/rayon/latest/rayon/struct.ThreadPoolBuilder.html)
- [rayon-rs/rayon — README (GitHub)](https://github.com/rayon-rs/rayon)
- [rayon-rs/rayon — FAQ.md (GitHub)](https://github.com/rayon-rs/rayon/blob/main/FAQ.md)
- [rayon — crates.io](https://crates.io/crates/rayon)
- [PyO3 user guide — Parallelism (v0.23.4)](https://pyo3.rs/v0.23.4/parallelism.html)
- [PyO3 guide/src/parallelism.md (main branch — `detach`/`attach` naming)](https://github.com/PyO3/pyo3/blob/main/guide/src/parallelism.md)
- [`pyo3::marker::Python` documentation, docs.rs](https://docs.rs/pyo3/latest/pyo3/marker/struct.Python.html)
- [PyO3 examples — word-count (GitHub)](https://github.com/PyO3/pyo3/blob/main/examples/word-count/src/lib.rs)
