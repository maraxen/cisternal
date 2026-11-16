"""``cisternal telemetry where``: which layer decides each telemetry behaviour (spec 261116, FR-4).

Read-only. For one consumer it reports, per behaviour (``spans``, ``shadow``), the answer, the layer and
file that decided it, and a state; plus the records directory and the mode-state directory shadow needs.

States:

``on`` / ``off``
    the behaviour resolves on or off.
``on but inert (mode_state_dir unresolved)``
    shadow is on but there is no ladder to run: no mode-state directory resolves.
``on but inert (records dir not yet generated)``
    shadow is on and a ladder exists, but neither cisternal's ``log_dir`` nor the consumer's own
    ``[telemetry.<consumer>] records_dir`` resolves, so nothing can be written yet.
``off (unreadable plugin option)``
    the saved plugin option could not be read, so the behaviour fails closed.

Exit codes: 0 ok; 1 a saved plugin option could not be read (failed closed); 3 a cisternal configuration
file or behaviour variable is malformed (the same code ``cisternal.shadow.resolution`` uses).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cisternal.telemetry_setting import (
    BEHAVIOURS,
    Registration,
    TelemetryDecision,
    TelemetrySettingError,
    consumer_records_dir,
    discover_registration,
    telemetry_setting,
)

__all__ = ["build_where_report", "format_where_json", "format_where_report", "where_exit_code"]


def _dir_report(label: str, resolver: Any, **kwargs: Any) -> dict[str, Any]:
    """Resolve one cisternal directory setting without raising: ``{"path", "provenance"}`` or ``{"error"}``."""
    try:
        resolved = resolver(**kwargs)
    except Exception as exc:  # ResolutionError and subclasses; the message names every layer checked
        return {"path": None, "error": f"{label}: {str(exc).splitlines()[0]}"}
    return {"path": str(resolved.path), "provenance": resolved.provenance}


def build_where_report(
    consumer: str,
    *,
    registration: Registration | Mapping[str, Any] | None = None,
    registration_source: str | None = None,
    config_dir: Path | str | None = None,
    repo_root: Path | None = None,
    user_config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Collect the report as a JSON-serializable dict. Never raises; errors land under ``errors``."""
    from cisternal.shadow.resolution import resolve_log_dir, resolve_mode_state_dir

    if registration is None:
        registration = discover_registration(consumer)
        registration_source = "entry point cisternal.telemetry_consumers" if registration else None
    registered = registration is not None
    errors: list[str] = []
    kwargs: dict[str, Any] = {
        "registration": registration,
        "config_dir": config_dir,
        "repo_root": repo_root,
        "user_config_file": user_config_file,
        "environ": environ,
    }

    decisions: dict[str, TelemetryDecision | None] = {}
    for behaviour in BEHAVIOURS:
        try:
            decisions[behaviour] = telemetry_setting(consumer, behaviour, **kwargs)
        except TelemetrySettingError as exc:
            decisions[behaviour] = None
            errors.append(str(exc))

    resolver_kwargs = {"repo_root": repo_root, "user_config_file": user_config_file}
    mode_state = _dir_report("mode_state_dir", resolve_mode_state_dir, **resolver_kwargs)
    log_dir = _dir_report("log_dir", resolve_log_dir, **resolver_kwargs)
    own_records: dict[str, Any]
    try:
        found = consumer_records_dir(consumer, user_config_file=user_config_file, environ=environ)
    except TelemetrySettingError as exc:
        found = None
        errors.append(str(exc))
    own_records = {"path": str(found[0]), "source": str(found[1])} if found else {"path": None}
    records_resolved = log_dir["path"] is not None or own_records["path"] is not None

    behaviours: dict[str, Any] = {}
    for behaviour, decision in decisions.items():
        if decision is None:
            behaviours[behaviour] = {"state": "unknown (configuration error)"}
            continue
        if decision.error:
            errors.append(decision.error)
            state = "off (unreadable plugin option)"
        elif not decision.enabled:
            state = "off"
        elif behaviour == "shadow" and mode_state["path"] is None:
            state = "on but inert (mode_state_dir unresolved)"
        elif behaviour == "shadow" and not records_resolved:
            state = "on but inert (records dir not yet generated)"
        else:
            state = "on"
        behaviours[behaviour] = {
            "enabled": decision.enabled,
            "layer": decision.layer,
            "source": str(decision.source) if decision.source else None,
            "state": state,
            "error": decision.error,
        }

    return {
        "consumer": consumer,
        "registration": {
            "registered": registered,
            "source": (registration_source or "passed by the caller") if registered else "none in this environment",
        },
        "behaviours": behaviours,
        "records": {"cisternal_log_dir": log_dir, "consumer_records_dir": own_records},
        "mode_state": mode_state,
        "errors": errors,
        "malformed": any(d is None for d in decisions.values()) or any("malformed" in e for e in errors),
    }


def where_exit_code(report: Mapping[str, Any]) -> int:
    """0 ok, 1 a plugin option failed closed, 3 a cisternal configuration is malformed."""
    if report.get("malformed"):
        return 3
    return 1 if report.get("errors") else 0


def format_where_report(report: Mapping[str, Any]) -> str:
    """Human-readable text for ``cisternal telemetry where``."""
    lines = [f"telemetry for consumer {report['consumer']!r}"]
    reg = report["registration"]
    lines.append(f"  registered default: {reg['source']}")
    for behaviour in BEHAVIOURS:
        item = report["behaviours"][behaviour]
        if "layer" not in item:
            lines.append(f"  {behaviour}: {item['state']}")
            continue
        where = f" ({item['source']})" if item["source"] else ""
        lines.append(f"  {behaviour}: {item['state']}; decided by {item['layer']}{where}")
    records = report["records"]
    own = records["consumer_records_dir"]
    log = records["cisternal_log_dir"]
    lines.append(f"  records dir ([telemetry.{report['consumer']}] records_dir): {own['path'] or 'unset'}")
    lines.append(f"  records dir (cisternal log_dir): {log['path'] or log.get('error', 'unresolved')}")
    mode = report["mode_state"]
    lines.append(f"  mode-state dir: {mode['path'] or mode.get('error', 'unresolved')}")
    for error in report["errors"]:
        lines.append(f"  ERROR: {error}")
    return "\n".join(lines)


def format_where_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
