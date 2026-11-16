"""Telemetry consumer enablement, answered by the resolver (M5.1b; spec 261116_telemetry-config-layers).

``consumer_telemetry_enabled`` used to read ``CISTERNAL_TELEMETRY`` and nothing else. It now asks
:func:`cisternal.telemetry_setting.telemetry_setting` for the consumer's span-timing behaviour, so the
environment, ``pyproject.toml``, a saved Claude Code plugin option, the machine config file and the
consumer's registered default all take part, in that order of precedence.

Behaviour that is the same as before: unset means disabled for a consumer that registered no default;
``all``/``1``/``true``/``yes`` or the consumer's own name enables it.

Behaviour that changed (stated in the changelog): an empty ``CISTERNAL_TELEMETRY``, or one naming another
consumer, used to mean "disabled" and now means "no opinion", so lower layers decide; for a consumer with
no registered default and no configuration that is still disabled. ``off``/``none``/``0``/``false`` now
disables explicitly, overriding every file layer.
"""

from __future__ import annotations

from cisternal.telemetry_setting import TelemetrySettingError, telemetry_setting


def consumer_telemetry_enabled(consumer: str) -> bool:
    """Return whether span-timing telemetry is enabled for *consumer*.

    A malformed cisternal configuration file or behaviour variable counts as disabled here, so a
    diagnostic that calls this never raises; ``cisternal telemetry where`` reports such an error loudly.
    """
    try:
        return telemetry_setting(consumer, "spans").enabled
    except TelemetrySettingError:
        return False
