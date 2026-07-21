"""Emitter ABC — pure-emit contract for agent-asset export (spec §2).

An Emitter converts an AssetBundle into a dict mapping forward-slash relative
paths to file contents.  Concrete subclasses render for a specific consumer
surface (e.g. ClaudeEmitter for the Claude plugin format).

CONTRACT — implementations MUST satisfy all of the following:

    PURE:
        Zero I/O — no filesystem reads, no filesystem writes, no network calls.
        The method receives a bundle; it returns a dict.  Any I/O is the
        caller's responsibility (see write_bundle in export/write.py).

    DETERMINISTIC:
        Identical bundle → identical dict on every call.  This is a hard
        requirement for provenance sha256 correctness and for the Rust-seam
        property (a praxia-Rust backend must be able to slot in as a concrete
        subclass and produce byte-identical output).

    FORWARD-SLASH PATHS:
        All keys in the returned dict must use forward slashes (``/``) as the
        path separator regardless of the host OS.

    NEVER-RAISE:
        emit() must not raise.  Degenerate input (empty bundle, missing fields)
        must produce a valid (possibly empty) dict, not an exception.

Design mirrors cisternal.adapters.base.AdapterBase:
    - ABC with a single @abstractmethod (emit vs. shape_ok/shape_error).
    - Docstring states the purity contract so subclasses cannot miss it.
    - No concrete methods — the ABC is purely structural.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from cisternal.assets.bundle import AssetBundle


class Emitter(ABC):
    """Abstract base for pure asset emitters.

    Each concrete subclass renders an AssetBundle for a specific consumer
    surface.  See module docstring for the full PURE/DETERMINISTIC/NEVER-RAISE
    contract.
    """

    @abstractmethod
    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        """Render *bundle* to a file dict.

        PURE: zero I/O, zero filesystem access, no side effects.
        DETERMINISTIC: identical bundle → identical dict on every call.
        FORWARD-SLASH PATHS: all keys use ``/`` as separator.
        NEVER-RAISE: degenerate input yields a valid (possibly empty) dict.

        Args:
            bundle: The AssetBundle to render.

        Returns:
            A dict mapping forward-slash relative paths to file contents.
            Keys are stable and sorted; values are UTF-8 text.
            Rust-seam: a praxia-Rust backend may slot in as a concrete subclass.
        """
