"""AssetSpec — single-tool asset metadata IR (spec §1).

AssetSpec is a frozen, slotted dataclass capturing the metadata extracted from
a registered tool.  It is the canonical intermediate representation (IR) between
the registry source and the Emitter layer.

Fields:
    name:        Tool name as stored in the registry.
    kind:        Asset kind.  Always ``"command"`` in M3; ``"mcp"`` is reserved.
    description: First paragraph of the tool docstring (inspect.cleandoc),
                 or ``None`` if the docstring is absent or empty.
    params:      Positional and keyword parameter names from inspect.signature.
                 ``()`` is a lossy sentinel: both "no params" and
                 "signature introspection failed" collapse here.  The caller
                 must check the WARNING log (cisterna.export) on failure.
    source:      Registry partition name the tool was drawn from.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssetSpec:
    """Frozen IR for a single tool's asset metadata."""

    name: str
    kind: str
    description: str | None
    params: tuple[str, ...]
    source: str
