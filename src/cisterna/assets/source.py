"""Registry-sourced AssetSpec builder (spec §1, G1/M5).

registry_assets extracts AssetSpec instances from a named registry partition
via the deliberate, tested coupling to
``cisterna.registration.registry._snapshot``.  The coupling is intentional
and pinned by AC-M3-2: if ``_snapshot`` changes its contract, that acceptance
criterion fails loudly.  A public ``registration.snapshot()`` accessor is an
optional M3.1 cleanup.

Design invariants:
    - NEVER raises: empty/unknown registry → (); introspection failures → ()
      with WARNING.
    - Output is SORTED by name (M1) for canonical determinism regardless of
      registration or import order.
    - Description is the first paragraph of inspect.cleandoc(fn.__doc__) (M2):
      the full docstring is cleaned (dedented, trailing whitespace stripped)
      then split on the first blank line; only the first paragraph is kept.
    - params uses ``except Exception`` (M3) — not a narrow ValueError/TypeError
      — so that exotic callables (C extensions, __wrapped__, etc.) are handled
      safely.  ``()`` is an intentionally lossy sentinel; WARNING is the signal.
"""

from __future__ import annotations

import inspect
import logging

from cisterna.assets.spec import AssetSpec
from cisterna.assets.bundle import (
    AssetBundle,
    BundleMetadata,
    CommandAsset,
)

_log = logging.getLogger("cisterna.export")


def registry_assets(registry: str = "default") -> tuple[AssetSpec, ...]:
    """Return AssetSpec tuples for every tool in the named registry partition.

    Calls ``cisterna.registration.registry._snapshot(registry)`` (deliberate
    tested coupling per spec §1/M5).  Empty or unknown registries return ``()``
    without raising.  The result is sorted by name for canonical determinism.

    Args:
        registry: Registry partition name.  Defaults to ``"default"``.

    Returns:
        A tuple of :class:`AssetSpec` instances, sorted by ``name``.
        Empty if the registry is unknown or empty.  Never raises.
    """
    from cisterna.registration.registry import _REGISTRIES, _snapshot

    # Pre-check: avoid silently creating an empty partition as a side effect of
    # _snapshot() -> _registry() -> _REGISTRIES[name] = {}.  Unknown registry is
    # treated as empty (never-raise / pure-read semantics, spec section 1 / M5).
    if registry not in _REGISTRIES:
        return ()

    try:
        snapshot = _snapshot(registry)
    except Exception:
        _log.warning(
            "cisterna.export: _snapshot(%r) raised; returning empty tuple",
            registry,
        )
        return ()

    specs: list[AssetSpec] = []
    for entry in snapshot.values():
        description = _extract_description(entry.fn)
        params = _extract_params(entry.name, entry.fn)
        specs.append(
            AssetSpec(
                name=entry.name,
                kind="command",
                description=description,
                params=params,
                source=registry,
            )
        )

    return tuple(sorted(specs, key=lambda s: s.name))


def registry_bundle(
    registry: str = "default",
    *,
    metadata: BundleMetadata | None = None,
) -> AssetBundle:
    """Build an :class:`AssetBundle` from a registry partition (commands only).

    Agents, skills, hooks, and MCP entries are always empty — registry contributes
    commands only per M3.1a spec L13.  Never raises.
    """
    if metadata is None:
        metadata = BundleMetadata(name="cisterna", version="0.0.0", description="")

    specs = registry_assets(registry)
    commands = tuple(
        CommandAsset(
            name=spec.name,
            description=spec.description,
            body="",
        )
        for spec in specs
    )
    return AssetBundle(metadata=metadata, commands=commands)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_description(fn: object) -> str | None:
    """Return the first paragraph of the cleaned docstring, or None."""
    raw_doc = getattr(fn, "__doc__", None) or ""
    cleaned = inspect.cleandoc(raw_doc)
    if not cleaned:
        return None
    first_para = cleaned.split("\n\n", 1)[0].strip()
    return first_para or None


def _extract_params(tool_name: str, fn: object) -> tuple[str, ...]:
    """Return parameter names from inspect.signature, or () on any failure.

    Logs a WARNING naming the tool if introspection fails.  The ``()`` return
    is a lossy sentinel: both "no params" and "introspection failure" collapse
    here; the WARNING is the only distinguishing signal (PM-4).
    """
    try:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
        return tuple(sig.parameters)
    except Exception:
        _log.warning(
            "cisterna.export: could not introspect signature of tool %r; "
            "params set to ()",
            tool_name,
        )
        return ()
