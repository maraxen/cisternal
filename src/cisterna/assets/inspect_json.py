"""JSON serialization for inspect output (M3.1a)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from cisterna.assets.bundle import AssetBundle, LoadReport
from cisterna.assets.capability import resolve_tools


def _serialize_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize_value(v) for k, v in asdict(value).items()}
    if isinstance(value, tuple):
        return [_serialize_value(v) for v in value]
    return value


def report_to_dict(
    report: LoadReport,
    *,
    resolve_tools_flag: bool = False,
    surface: str | None = None,
) -> dict[str, Any]:
    """Convert a load report to a JSON-serializable dict."""
    data: dict[str, Any] = {
        "bundle": _serialize_bundle(report.bundle),
        "warnings": list(report.warnings),
        "conflicts": list(report.conflicts),
    }
    if resolve_tools_flag:
        if not surface:
            raise ValueError("surface is required when resolve_tools is enabled")
        data["resolved_tools"] = _resolved_tools_for_bundle(report.bundle, surface)
    return data


def _serialize_bundle(bundle: AssetBundle) -> dict[str, Any]:
    return _serialize_value(bundle)  # type: ignore[return-value]


def _resolved_tools_for_bundle(bundle: AssetBundle, surface: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for agent in bundle.agents:
        if not agent.tools:
            continue
        out[agent.name] = list(resolve_tools(agent.tools, surface))
    return out
