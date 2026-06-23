"""Abstract capability verbs and vendor tool resolution (M3.1a spec L5)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Final

_MCP_PREFIX: Final = "mcp__"


class Capability(StrEnum):
    """Fourteen portable abstract capability verbs (praxia parity)."""

    READ = "read"
    SEARCH = "search"
    EDIT = "edit"
    WRITE = "write"
    EXECUTE = "execute"
    WEB = "web"
    WEB_SEARCH = "web_search"
    DELEGATE = "delegate"
    TRANSDUCTION_LOG = "transduction_log"
    TRANSDUCTION_QUERY = "transduction_query"
    LESSON = "lesson"
    KNOWLEDGE = "knowledge"
    RECON_WORKSPACE = "recon_workspace"
    CODE_INDEX_WORKSPACE = "code_index_workspace"

    @classmethod
    def parse(cls, token: str) -> Capability:
        try:
            return cls(token)
        except ValueError as exc:
            raise ValueError(f"unknown capability token: {token!r}") from exc


@dataclass(frozen=True, slots=True)
class VendorToolsConfig:
    capability_maps: dict[str, dict[str, str]]
    allowed_names: dict[str, frozenset[str]]
    model_hints: dict[str, dict[str, str]]


def _parse_vendor_tools(raw: dict[str, object]) -> VendorToolsConfig:
    capability_maps: dict[str, dict[str, str]] = {}
    allowed_names: dict[str, frozenset[str]] = {}
    model_hints: dict[str, dict[str, str]] = {}

    skip_keys = {"abstract", "export"}
    for key, value in raw.items():
        if key in skip_keys or not isinstance(value, dict):
            continue
        section = value
        cap_map = section.get("capability_map")
        if isinstance(cap_map, dict):
            capability_maps[key] = {str(k): str(v) for k, v in cap_map.items()}
        allowed = section.get("allowed_names")
        if isinstance(allowed, list):
            allowed_names[key] = frozenset(str(x) for x in allowed)

    export = raw.get("export")
    if isinstance(export, dict):
        models = export.get("models")
        if isinstance(models, dict):
            for surface, hints in models.items():
                if isinstance(hints, dict):
                    model_hints[str(surface)] = {str(k): str(v) for k, v in hints.items()}

    return VendorToolsConfig(
        capability_maps=capability_maps,
        allowed_names=allowed_names,
        model_hints=model_hints,
    )


@lru_cache(maxsize=1)
def load_vendor_tools(path: Path | None = None) -> VendorToolsConfig:
    """Load vendor tool maps from the packaged TOML (or an override path)."""
    if path is not None:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        return _parse_vendor_tools(raw)

    data = resources.files("cisterna.assets.data").joinpath("vendor_tools.toml")
    raw = tomllib.loads(data.read_text(encoding="utf-8"))
    return _parse_vendor_tools(raw)


def resolve_tools(
    tokens: tuple[str, ...],
    surface: str,
    *,
    config: VendorToolsConfig | None = None,
) -> tuple[str, ...]:
    """Map abstract capability tokens to concrete tool names for *surface*."""
    cfg = config or load_vendor_tools()
    vendor_map = cfg.capability_maps.get(surface)
    if vendor_map is None:
        raise ValueError(f"unknown surface: {surface!r}")

    allowed = cfg.allowed_names.get(surface, frozenset())
    resolved: list[str] = []

    for token in tokens:
        if token.startswith(_MCP_PREFIX):
            resolved.append(token)
            continue
        if token in allowed:
            resolved.append(token)
            continue
        try:
            cap = Capability.parse(token)
        except ValueError:
            raise ValueError(f"unknown capability token: {token!r}") from None

        concrete = vendor_map.get(cap.value)
        if concrete is None:
            raise ValueError(
                f"unbound capability {cap.value!r} on surface {surface!r}"
            )
        if not concrete:
            raise ValueError(
                f"unbound capability {cap.value!r} on surface {surface!r}"
            )
        resolved.append(concrete)

    if surface == "claude_code":
        if "Grep" in resolved and "Glob" not in resolved:
            resolved.append("Glob")

    return tuple(sorted(dict.fromkeys(resolved)))


def resolve_model_hint(
    hint: str,
    surface: str,
    *,
    config: VendorToolsConfig | None = None,
) -> str | None:
    """Resolve a model hint (fast/balanced/deep) for *surface*."""
    cfg = config or load_vendor_tools()
    return cfg.model_hints.get(surface, {}).get(hint)
