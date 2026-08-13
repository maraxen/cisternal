<!-- ref-crate-versions: pyo3=0.29.2; maturin=1.14.1; checked=2026-08-13 -->

# PyO3 Technical Reference: Building Rust-Backed Python Extensions

*Compiled from the official PyO3 guide (targeting the `main`/`latest` docs, current release `pyo3` 0.29.2) and the official maturin guide (current release `maturin` 1.13.3), August 2026.*

---

## 1. What PyO3 Is

PyO3 is a Rust crate providing bindings between Rust and the CPython C API. It supports two directions:

1. **Wrapping Rust code for use from Python** — compiling a Rust crate into a native extension module (`.so`/`.pyd`/`.dylib`) importable from Python, via `#[pymodule]`, `#[pyfunction]`, and `#[pyclass]`.
2. **Embedding Python in Rust** — calling Python code and objects from a Rust binary or library.

This document focuses on direction (1): replacing or augmenting a pure-Python module with a pyo3-backed native extension.

---

## 2. Typical Project Layout

A pyo3 extension is normally built with **maturin**, the PEP 517/518/621-compliant build backend purpose-built for pyo3/cffi/uniffi bindings. Maturin's documented default "mixed" layout — Rust source alongside a Python package — looks like:

```
my-rust-and-python-project/
├── Cargo.toml
├── pyproject.toml
├── python/
│   └── my_project/
│       ├── __init__.py
│       └── bar.py            # pure-Python code lives here
└── src/
    └── lib.rs                 # #[pymodule] entry point
```

Key `pyproject.toml` knobs (maturin-specific `[tool.maturin]` table):

- **`python-source`** — points at the pure-Python package root (e.g. `python-source = "python"`); without it maturin assumes a "pure Rust" layout with no separate Python package.
- **`module-name`** — lets the compiled extension be nested as a private submodule, e.g. `module-name = "my_project._my_project"`, so the public `__init__.py` can do `from my_project._my_project import *` and re-export a clean Python-facing API. Maturin does **not** auto-modify `__init__.py`; you write the re-export by hand.

`Cargo.toml` requires the extension crate type:

```toml
[lib]
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.29.2", features = ["extension-module"] }
```

This is the standard shape for "give a pure-Python module a pyo3-backed replacement": the Python-facing package name and public API stay stable while the implementation module underneath becomes compiled Rust.

*Source: maturin project layout guide.*

---

## 3. Core Macros

### 3.1 `#[pymodule]`

`#[pymodule]` is the proc-macro that "takes care of creating the initialization function of your module and exposing it to Python." Modern (post-0.22) syntax decorates a Rust `mod` block and uses `#[pymodule_export]` to re-export items defined elsewhere:

```rust
#[pymodule]
mod my_project {
    use pyo3::prelude::*;

    #[pymodule_export]
    use super::{sum_as_string, MyClass};

    #[pyfunction]
    fn inline_helper() -> i32 { 42 }
}
```

Notes:
- The compiled `.so`/`.pyd` filename must match the module name or Python import fails.
- Nested `#[pymodule]` blocks can express submodules, but this does **not** create an importable Python package — `from parent_module import child_module` will not work without additional `sys.modules` registration; it's purely a namespacing convenience inside the compiled extension.
- The module's Rust doc comment becomes the Python module docstring.

*Source: PyO3 guide, "Python modules."*

### 3.2 `#[pyfunction]`

Converts a Rust function into a Python-callable. Notable attributes:

- `#[pyo3(signature = (...))]` — explicitly controls the Python-visible signature (positional/keyword defaults, `*args`, `**kwargs`); required since 0.22 for any trailing `Option<T>` argument that should default to `None` (this was previously implicit and is now deprecated-then-removed).
- `#[pyo3(text_signature = "...")]` — overrides what `inspect.signature()`/help() shows.
- `#[pyo3(name = "...")]` — renames the Python-visible function.
- `#[pyo3(from_py_with = ...)]` — custom per-argument extraction, signature `fn(&Bound<'_, PyAny>) -> PyResult<T>`.
- `#[pyo3(pass_module)]` — injects the containing module object as the first parameter.

Return type is almost always `PyResult<T>` (see §6).

*Source: PyO3 guide, "Python functions."*

### 3.3 `#[pyclass]` / `#[pymethods]`

Exposes a Rust `struct` or `enum` as a Python type:

```rust
#[pyclass]
struct MyClass { inner: i32 }

#[pymethods]
impl MyClass {
    #[new]
    fn new(value: i32) -> Self { MyClass { inner: value } }

    #[getter]
    fn value(&self) -> i32 { self.inner }

    #[staticmethod]
    fn zero() -> Self { MyClass { inner: 0 } }
}
```

Constraints and features:
- No lifetime or generic parameters on the struct (Python's object model and refcounting are incompatible with Rust borrow-checked lifetimes).
- `#[new]` may return `Self`, `PyResult<Self>` (fallible construction), or `PyClassInitializer<Self>` (for inheritance chains).
- `#[pyo3(get, set)]` on a field auto-generates a property; `#[getter]`/`#[setter]` methods handle computed properties.
- **Inheritance**: `#[pyclass(extends = BaseClass)]`, with `self_.as_super()` to reach the parent in methods.
- **Interior mutability**: PyO3 enforces a `RefCell`-like runtime borrow check for `&mut self` access on shared `Py<T>`/`Bound<'py, T>` references — a second concurrent mutable borrow raises `PyBorrowMutError` (or panics) rather than being a Rust compile error, since Python holds these objects behind reference-counted, not uniquely-owned, pointers.
- `#[pyclass(frozen)]` opts a class out of that runtime-borrow machinery entirely when no interior mutability is needed; combined with `Sync` interior types (e.g. `std::sync::Mutex`) this also avoids requiring a GIL token for access — relevant for free-threaded builds (§5).
- Simple (unit-only) enums map to Python class-attribute-style enums; complex enums with struct/tuple variants support Python 3.10+ structural pattern matching.

*Source: PyO3 guide, "Python classes."*

---

## 4. Type Conversion Between Rust and Python

Two traits mediate every argument and return value at the FFI boundary:

- **`FromPyObject`** — converts a Python object *into* a Rust value; the ergonomic entry point is `.extract::<T>()`. Derivable for structs (via `getattr`/`get_item`, `#[pyo3(attribute)]`/`#[pyo3(item)]`), tuple structs (positional), and enums (tries each variant in order — a natural way to express Python "union" arguments).
- **`IntoPyObject`** (current, since 0.23) — converts a Rust value *into* a Python object via `.into_pyobject(py)`, returning `Result<Bound<'py, Target>, Error>`. This **replaced** the older `IntoPy`/`ToPyObject` traits; `#[derive(IntoPyObject)]` / `#[derive(IntoPyObjectRef)]` are available for custom types.

A migration note worth flagging in any codebase touching older pyo3 examples: since 0.23, `Vec<u8>` / `[u8; N]` / `SmallVec<[u8; N]>` convert to `PyBytes` by default (previously `PyList`) — this is a silent behavior change if upgrading, not just a rename.

*Source: PyO3 guide, "Conversion traits"; PyO3 migration guide (0.23 entry).*

---

## 5. GIL Interaction and Free-Threaded (No-GIL) Python

### 5.1 The `Python<'py>` token model

All calls into the CPython C API require proof that the calling thread is safely attached to the interpreter. PyO3 expresses this as a **token**, `Python<'py>`, obtained via `Python::attach(|py| { ... })` (the current name — see naming history below). The token:

- Grants access to interpreter-global APIs (`py.eval()`, `py.import()`, etc.).
- Is threaded through as the lifetime parameter on `Bound<'py, T>`, PyO3's standard GIL-bound smart pointer — a `Bound<'py, T>` carries its own `Python<'py>` token internally, so functions holding one already have interpreter access without re-acquiring anything.
- On a traditional (GIL-enabled) build, holding the token *is* holding the GIL: only one thread can hold it at a time. On a **free-threaded** build, holding the token means only "this thread is attached to the interpreter" — other threads may be attached and executing concurrently.

For long-running or blocking Rust work, release interpreter attachment with `Python::detach(py, || { ... })` so other Python threads can run — this is the direct equivalent of releasing the GIL in the C API (`Py_BEGIN_ALLOW_THREADS`).

**Naming history** (relevant when reading older examples or blog posts): as of **pyo3 0.26**, `Python::with_gil` → `Python::attach`, `Python::allow_threads` → `Python::detach`, and `pyo3::prepare_freethreaded_python` → `Python::initialize` — all renamed specifically to stop implying GIL semantics that no longer universally hold. Old names are deprecated aliases, not removed outright, but new code should use the current names.

*Source: PyO3 guide, "Python from Rust"; PyO3 migration guide (0.26 entry).*

### 5.2 Free-threaded Python (CPython 3.13+/3.14 no-GIL builds)

As of **pyo3 0.28**, extension modules **default to declaring free-threading support** — the module sets CPython's `Py_MOD_GIL` slot to `Py_MOD_GIL_NOT_USED` automatically. If your `unsafe` code assumes single-threaded execution (a common latent bug when porting an older extension), opt back out explicitly:

```rust
#[pymodule(gil_used = true)]
mod my_project { /* ... */ }
```

Consequences for extension authors targeting free-threaded builds:

- **Interior mutability failures become live concerns, not rare races.** The `RefCell`-like runtime borrow check on `#[pyclass]` fields (§3.3) can now be tripped by genuinely concurrent threads, not just re-entrant single-threaded call graphs.
- **`GILProtected` is removed.** It relied on GIL exclusivity for its safety argument, which free-threaded builds don't provide. Replace it with `std::sync::Mutex` (or an atomic type), using PyO3's `MutexExt::lock_py_attached` when the locked section may itself call back into Python (to avoid deadlocking against the interpreter's own synchronization).
- **One-time initialization**: use `PyOnceLock` (replacing the deprecated `GILOnceCell`) — it correctly avoids deadlock in scenarios where free-threaded interleaving means the initializing thread isn't unconditionally serialized against readers.
- **Detach during long/blocking work**: `Python::detach()` should be called before long-running non-Python work even more deliberately under free-threading, since global synchronization events (stop-the-world GC passes, thread startup, profiler attachment) need every attached thread to eventually detach or reach a safe point — an extension that never detaches can stall those events for the whole process.
- **`abi3` is not available for free-threaded builds.** Free-threaded CPython uses a new, still-evolving ABI with no limited-API equivalent yet, so an extension distributed for free-threaded interpreters must ship one build per exact Python version rather than a single `abi3` wheel (§7.1). PyO3 exposes an `abi3t` feature that governs which ABI mode is targeted depending on the Python version being built against.
- Since **pyo3 0.23**, `#[pyclass]` types are required to be `Sync` — a compile-time consequence of supporting free-threaded access, not an opt-in.

*Source: PyO3 guide, "Free-threaded Python"; PyO3 guide, "Building and distribution"; PyO3 migration guide (0.28, 0.23 entries).*

---

## 6. Error Translation: Rust `Result` → Python Exceptions

PyO3 represents a Python exception as `PyErr`, and defines `PyResult<T>` as `Result<T, PyErr>`. The rule that ties Rust error handling to Python's is simple and mechanical:

> When a `PyResult` containing an `Err` crosses from Rust back to Python, PyO3 raises the exception it contains.

Practical patterns:

**Raising a built-in exception directly:**
```rust
use pyo3::exceptions::PyValueError;

#[pyfunction]
fn check_positive(x: i32) -> PyResult<()> {
    if x < 0 {
        Err(PyValueError::new_err("x is negative"))
    } else {
        Ok(())
    }
}
```
Every standard Python exception type (`PyValueError`, `PyTypeError`, `PyIndexError`, `PyRuntimeError`, …) lives in `pyo3::exceptions` with a `::new_err(...)` constructor.

**Automatic conversion from third-party/std error types:** if `E: Into<PyErr>` (equivalently, `PyErr: From<E>`), then `?` on a `Result<T, E>` inside a `PyResult<T>`-returning function converts automatically — no manual `.map_err()` needed. Standard library errors like `ParseIntError` already have this impl. For your own error enum, implement `From<MyError> for PyErr` (typically via a newtype wrapper) once, and every fallible function gets the ergonomic `?` conversion for free.

**Defining custom Python exception types**, so Python code can `except MyModuleError:` a domain-specific error:
```rust
use pyo3::create_exception;
use pyo3::exceptions::PyException;

create_exception!(my_project, CustomError, PyException);
```
`create_exception!` takes the module, the new exception name, and its Python base class. Export it from the module like any other item:
```rust
#[pymodule]
mod my_project {
    #[pymodule_export]
    use super::CustomError;
}
```

**Manual interpreter error-state manipulation** (rare, mostly for embedding/advanced FFI work): `PyErr::restore(py)`, `PyErr::occurred(py)`, `PyErr::fetch(py)` — direct analogs of the C API's error-indicator functions.

For exceptions carrying custom Rust-side data/behavior beyond a message, a `#[pyclass(extends = PyException)]` subclass is the richer alternative to `create_exception!`.

*Source: PyO3 guide, "Python exceptions"; PyO3 guide, "Error handling."*

---

## 7. Packaging and Publishing (maturin + uv)

### 7.1 ABI stability: `abi3`

The single biggest lever for a manageable wheel matrix is CPython's **limited API / stable ABI**. Building against `abi3` produces *one* wheel that loads on every CPython minor version at or above a chosen floor — instead of one wheel per (platform × Python minor version).

`Cargo.toml`:
```toml
[dependencies.pyo3]
version = "0.29.2"
features = ["abi3-py38"]   # floor: Python 3.8; wheel also loads on 3.9, 3.10, ...
```

Version-pinned feature flags (`abi3-py38`, `abi3-py39`, `abi3-py310`, …) set the floor. A hard constraint: **you cannot target an `abi3` floor above your build-host Python's version** — building with a 3.8 host interpreter while requesting `abi3-py39` fails to compile, because PyO3 needs the host's headers/symbols to be at least as new as the floor it's declaring compatibility down to.

`abi3t` (paired with `abi3`) governs the free-threaded case: PyO3 auto-selects between emitting a classic `abi3` extension or an `abi3t` (free-threaded-compatible) one depending on the targeted Python version — but note from §5.2 that **no stable-ABI equivalent exists yet for free-threaded builds on older free-threaded Python versions**, so this is a moving target across CPython releases, not a settled guarantee.

maturin and setuptools-rust both auto-set `PYO3_BUILD_EXTENSION_MODULE` on your behalf (disabling the direct `libpython` link that a plain `cdylib` would otherwise want), which is required for both `abi3` builds and Linux manylinux compliance.

*Source: PyO3 guide, "Building and distribution."*

### 7.2 The maturin build backend in a `uv` workflow

Minimal `pyproject.toml`:
```toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[project]
name = "my-project"
requires-python = ">=3.8"
```

Maturin follows **PEP 621** for project metadata and merges `Cargo.toml` + `pyproject.toml` configuration, with `pyproject.toml` taking precedence on overlapping fields — Python-facing metadata (classifiers, dependencies, console-script entry points) belongs in `pyproject.toml` even though the crate itself is described in `Cargo.toml`.

Day-to-day commands, and where `uv` slots in:

| Command | Purpose |
|---|---|
| `uv tool install maturin` | Install maturin itself as an isolated tool (or `uv add --dev maturin` inside the project) |
| `maturin new -b pyo3 <name>` | Scaffold a new pyo3-backed project |
| `maturin develop` | Compile the extension and install it directly into the active environment (skips wheel packaging) — the fast inner-loop command, analogous to `pip install -e .` for pure-Python packages |
| `maturin build [--release]` | Produce a real `.whl` with correct platform/Python/ABI tags |
| `uv publish` (or `twine upload`) | Upload built wheels to PyPI/TestPyPI |

Because the build backend is declared in `[build-system]`, a plain `uv sync` / `uv pip install .` (or `pip install .`) also works end-to-end without invoking `maturin` directly — `uv`/`pip` invoke the backend hooks (`build_wheel`, `build_sdist`) that maturin implements, exactly like any other PEP 517 backend. `maturin develop` is specifically the fast local-iteration shortcut layered on top of that.

*Source: maturin guide, "Tutorial"; maturin guide, "Distribution."*

### 7.3 Publishing a mixed Python+Rust package to PyPI

Distribution-time concerns that are specific to compiled extensions (absent for pure-Python packages):

- **manylinux/musllinux compliance (Linux).** A Linux wheel may only dynamically link an approved, versioned set of system libraries/symbols ("manylinux"/"musllinux" standards) to be broadly installable. Maturin reimplements `auditwheel`-style checking and auto-tags wheels appropriately; if your build glibc is too new for the requested manylinux tag, maturin falls back to a plain (non-portable) `linux` tag rather than silently mis-tagging. Recommended baseline: `--manylinux 2014` or newer — the Rust toolchain itself has required glibc ≥ 2.17 since rustc 1.64, which already exceeds `manylinux2010`. Building inside the official `manylinux` Docker images, or using **Zig** as the linker/compiler (`--zig` flag) as a Docker-free alternative, are the two supported paths to compliant Linux wheels. Non-vendorable shared-library dependencies can sometimes be bundled directly into the wheel (via `patchelf`), or manylinux checking can be disabled outright with `--manylinux off` for internal-only distribution.
- **Cross-compilation.** Maturin supports cross-compiling pyo3/binary-binding wheels via `--target`, with `--zig` again usable as a cross-linking C toolchain substitute, and `cargo-xwin` integration for producing Windows/MSVC wheels (auto-fetching the needed CRT/SDK files) from non-Windows hosts.
- **Full platform × Python-version matrix.** `maturin generate-ci github` emits a ready-made GitHub Actions workflow that builds the standard cross-product (Linux/macOS/Windows × supported CPython versions, optionally × free-threaded builds separately since `abi3` doesn't cover them) — this is maturin's answer to what `cibuildwheel` provides for setuptools-based C-extension packages.
- **Trusted publishing.** `trusted-publishing = true` in `pyproject.toml`'s maturin config lets CI publish via OIDC-based PyPI trusted publishing, avoiding long-lived API tokens in CI secrets.
- **`--compatibility pypi`** restricts a build to tags PyPI will actually accept, catching an overly permissive or malformed platform tag before upload rather than at `twine upload` time.

*Source: maturin guide, "Distribution."*

---

## 8. Common Pitfalls

1. **Assuming an old-style abi3 wheel covers free-threaded Python.** It doesn't (§5.2, §7.1) — a package that wants to support both GIL and free-threaded CPython needs a real decision point in its release matrix, not just a wider `abi3-pyXY` floor.
2. **Silent `unsafe` breakage from the 0.28 free-threading default.** Any extension carrying pre-0.28 `unsafe` code that assumed GIL-serialized access is now, by default, advertising itself as free-thread-safe (`Py_MOD_GIL_NOT_USED`) the moment it's rebuilt against pyo3 ≥ 0.28 — even if nobody runs it under a free-threaded interpreter yet, the module-level slot has changed. Audit for this explicitly rather than trusting "it compiled" as a safety signal; `#[pymodule(gil_used = true)]` is the deliberate opt-out.
3. **`abi3` floor above the build host's Python.** Requesting `abi3-py311` while building with a 3.10 interpreter fails at compile time (§7.1) — CI matrices need a build host at least as new as the declared floor, which is a different (and usually *older*) constraint than "install the newest Python for CI."
4. **Trusting a `linux`-tagged wheel as portable.** If local glibc exceeds the target manylinux tag's ceiling, maturin silently downgrades the tag to plain `linux` rather than failing loudly — that wheel will not install on most users' machines despite building and uploading successfully. Always build manylinux/musllinux wheels inside the sanctioned Docker images or via `--zig`, not on an arbitrary dev machine.
5. **Confusing `maturin develop` iteration speed with `maturin build` correctness.** `develop` installs directly into the active environment and skips wheel tagging/packaging — it is not a substitute for at least one real `maturin build` + install-from-wheel smoke test before a release, since tagging/ABI/manylinux problems only surface in the `build` path.
6. **Treating `#[pyclass]` fields as freely, safely mutable the way a plain Rust struct is.** The runtime `RefCell`-like borrow check (§3.3) converts what would be a compile error in ordinary Rust into a *runtime* `PyBorrowMutError` (or panic) reachable only when Python code re-enters or aliases the object — these bugs surface late, typically only under concurrent/free-threaded use or unusual call graphs (e.g. a Python `__del__` re-entering the same object), not during normal single-path testing.
7. **Losing the mapping between a custom Rust error type and a Python exception.** Forgetting `impl From<MyError> for PyErr` means `?` won't compile inside a `PyResult`-returning function, or (worse, if a blanket/partial conversion exists) errors silently downgrade to a generic exception, discarding the specific error information Python callers need to `except` on.
8. **Nested `#[pymodule]`s look like Python subpackages but aren't.** `from parent import child` does not work for a pyo3-declared submodule without extra `sys.modules` registration (§3.1) — this differs from a real Python package's import semantics and is easy to assume works when porting a package's directory structure literally into Rust module nesting.
9. **Reading old examples that still use `with_gil`/`allow_threads`/`prepare_freethreaded_python`/`GILProtected`/`GILOnceCell`/`IntoPy`.** All are renamed or replaced as of pyo3 0.23–0.28 (§4, §5.1); code following a tutorial pinned to an older pyo3 minor version can silently compile against deprecated-but-still-present aliases and miss the semantic shift (especially the `IntoPy`→`IntoPyObject` byte-collection target-type change in §4).

---

## References

- PyO3 User Guide — Introduction: https://pyo3.rs/latest/
- PyO3 User Guide — Python classes (`#[pyclass]`): https://pyo3.rs/latest/class.html
- PyO3 User Guide — Python functions (`#[pyfunction]`): https://pyo3.rs/latest/function.html
- PyO3 User Guide — Python modules (`#[pymodule]`): https://pyo3.rs/latest/module.html
- PyO3 User Guide — Python from Rust (GIL / `Python<'py>` token): https://pyo3.rs/latest/python-from-rust.html
- PyO3 User Guide — Free-threaded Python: https://pyo3.rs/latest/free-threading.html
- PyO3 User Guide — Error handling: https://pyo3.rs/latest/function/error-handling.html
- PyO3 User Guide — Python exceptions: https://pyo3.rs/latest/exception.html
- PyO3 User Guide — Conversion traits (`FromPyObject`/`IntoPyObject`): https://pyo3.rs/latest/conversions/traits.html
- PyO3 User Guide — Building and distribution (abi3, manylinux, cross-compilation): https://pyo3.rs/latest/building-and-distribution.html
- PyO3 Migration Guide: https://pyo3.rs/latest/migration.html
- pyo3 crate on crates.io (version history via sparse index, current 0.29.2): https://crates.io/crates/pyo3
- Maturin User Guide — Home: https://www.maturin.rs/
- Maturin User Guide — Tutorial: https://www.maturin.rs/tutorial.html
- Maturin User Guide — Project layout: https://www.maturin.rs/project_layout.html
- Maturin User Guide — Distribution (manylinux, cross-compilation, publishing, CI): https://www.maturin.rs/distribution.html
- maturin crate on crates.io (current 1.13.3): https://crates.io/crates/maturin
