"""One resolver for "is this consumer's telemetry behaviour on?" (spec 261116_telemetry-config-layers).

Two behaviours, two answers per consumer:

``spans``
    span timing: MCP middleware and ledger spans.
``shadow``
    shadow-ladder verdict and label records.

Resolution order, the same in every process, first hit wins:

1. the ``explicit`` argument;
2. the behaviour's own variable, ``CISTERNAL_TELEMETRY_SPANS`` or ``CISTERNAL_TELEMETRY_SHADOW``;
3. the whole-consumer variable ``CISTERNAL_TELEMETRY``;
4. ``[tool.cisternal.telemetry]`` then ``[tool.cisternal.telemetry.<consumer>]`` in the repository's
   ``pyproject.toml`` (the repository root is found the way :mod:`cisternal.shadow.resolution` finds it);
5. the user's saved Claude Code plugin option, read from the user's ``settings.json`` ``pluginConfigs``
   (read-only; ``enabledPlugins`` only chooses between several marketplaces' entries for one plugin);
6. ``[telemetry]`` then ``[telemetry.<consumer>]`` in ``${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml``;
7. the consumer's registered default;
8. off.

Contract:

- Report which layer decided (``TelemetryDecision.layer``) and the file that supplied it.
- An unset or empty variable is "no opinion", unlike path settings where empty disables a path: an on/off
  switch has nothing useful to say with an empty value, and an unsaved plugin option can render empty.
- A malformed cisternal configuration file or an invalid behaviour variable raises
  :class:`TelemetrySettingError`.
- ``settings.json`` belongs to another tool and may hold the user's opt-out, so anything that leaves the
  user's intent unknowable resolves to **off** with ``TelemetryDecision.error`` set (fail closed) instead of
  raising or being ignored.
- No default path lives here and nothing here writes outside the machine file.

This module imports only the standard library at module level. Importing it still runs the
``cisternal`` package ``__init__``; what matters is that nothing here pulls in :mod:`cisternal.telemetry` or
the :mod:`cisternal.shadow` package, which import this module's neighbours lazily (see
``cisternal.shadow.resolution``).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BEHAVIOURS",
    "CONSUMERS_ENTRY_POINT_GROUP",
    "PLUGIN_OPTION_VALUES",
    "Registration",
    "SetResult",
    "TelemetryDecision",
    "TelemetrySettingError",
    "behaviour_env_var",
    "claude_settings_path",
    "consumer_records_dir",
    "discover_registration",
    "set_machine_value",
    "set_telemetry_setting",
    "telemetry_setting",
    "user_config_path",
]

BEHAVIOURS: tuple[str, ...] = ("spans", "shadow")
CONSUMER_ENV_VAR = "CISTERNAL_TELEMETRY"
CONSUMERS_ENTRY_POINT_GROUP = "cisternal.telemetry_consumers"
PLUGIN_OPTION_VALUES: tuple[str, ...] = ("inherit", "on", "off")

_ON_TOKENS = frozenset({"all", "1", "true", "yes", "on"})
_OFF_TOKENS = frozenset({"off", "none", "0", "false", "no"})
_BOOL_ON = frozenset({"true", "on", "1", "yes"})
_BOOL_OFF = frozenset({"false", "off", "0", "no"})


class TelemetrySettingError(ValueError):
    """A cisternal-owned setting is malformed (invalid variable value or configuration file)."""


@dataclass(frozen=True, slots=True)
class Registration:
    """What a consumer tells the resolver about itself (plain data; see ``from_mapping``)."""

    plugin: str
    spans_option: str
    shadow_option: str
    defaults: tuple[tuple[str, bool], ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Registration:
        """Validate ``{plugin, spans_option, shadow_option, defaults: {spans, shadow}}``."""
        try:
            plugin = _non_empty_str(data["plugin"], "plugin")
            spans_option = _non_empty_str(data["spans_option"], "spans_option")
            shadow_option = _non_empty_str(data["shadow_option"], "shadow_option")
            raw_defaults = data["defaults"]
        except KeyError as exc:
            msg = f"telemetry registration is missing {exc.args[0]!r}"
            raise TelemetrySettingError(msg) from exc
        if not isinstance(raw_defaults, Mapping):
            msg = "telemetry registration 'defaults' must be a mapping"
            raise TelemetrySettingError(msg)
        defaults: list[tuple[str, bool]] = []
        for behaviour in BEHAVIOURS:
            value = raw_defaults.get(behaviour, False)
            if not isinstance(value, bool):
                msg = f"telemetry registration defaults.{behaviour} must be a bool, got {value!r}"
                raise TelemetrySettingError(msg)
            defaults.append((behaviour, value))
        return cls(plugin, spans_option, shadow_option, tuple(defaults))

    def default_for(self, behaviour: str) -> bool:
        return dict(self.defaults).get(behaviour, False)

    def option_for(self, behaviour: str) -> str:
        return self.spans_option if behaviour == "spans" else self.shadow_option


@dataclass(frozen=True, slots=True)
class TelemetryDecision:
    """The answer for one consumer and behaviour, with provenance."""

    consumer: str
    behaviour: str
    enabled: bool
    layer: str
    source: Path | None = None
    error: str | None = None
    registered: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


def _non_empty_str(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"telemetry registration '{key}' must be a non-empty string, got {value!r}"
        raise TelemetrySettingError(msg)
    return value.strip()


def behaviour_env_var(behaviour: str) -> str:
    """The behaviour's own variable: ``CISTERNAL_TELEMETRY_SPANS`` or ``CISTERNAL_TELEMETRY_SHADOW``."""
    _check_behaviour(behaviour)
    return f"{CONSUMER_ENV_VAR}_{behaviour.upper()}"


def _check_behaviour(behaviour: str) -> None:
    if behaviour not in BEHAVIOURS:
        msg = f"unknown telemetry behaviour {behaviour!r}; expected one of {BEHAVIOURS}"
        raise TelemetrySettingError(msg)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def user_config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "cisternal" / "config.toml"


def claude_settings_path(config_dir: Path | str | None = None, environ: Mapping[str, str] | None = None) -> Path:
    """``<claude config dir>/settings.json``: the argument, else ``CLAUDE_CONFIG_DIR``, else ``~/.claude``."""
    env = os.environ if environ is None else environ
    base = config_dir if config_dir is not None else (env.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    return Path(base).expanduser() / "settings.json"


def _find_repo_root(start: Path | None = None) -> Path | None:
    """Nearest directory holding ``.git`` or ``pyproject.toml`` (same rule as ``shadow.resolution``)."""
    current = (start or Path.cwd()).resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return None


# ---------------------------------------------------------------------------
# Notices (once per process)
# ---------------------------------------------------------------------------

_NOTICED: set[str] = set()


def _notice(message: str) -> None:
    if message in _NOTICED:
        return
    _NOTICED.add(message)
    print(f"cisternal telemetry: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------


def _parse_switch(raw: str, where: str) -> bool | None:
    """Parse a behaviour variable: ``None`` for unset/empty, a bool, or raise naming ``where``."""
    token = raw.strip().lower()
    if not token:
        return None
    if token in _BOOL_ON:
        return True
    if token in _BOOL_OFF:
        return False
    msg = f"{where}: invalid value {raw!r}; expected true/false/on/off/1/0 (or leave it empty for no opinion)"
    raise TelemetrySettingError(msg)


def _consumer_switch(raw: str, consumer: str) -> bool | None:
    """Parse ``CISTERNAL_TELEMETRY``: a comma list of tokens; another consumer's name is no opinion."""
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    if not tokens:
        return None
    mine = consumer.strip().lower()
    if any(t == mine or t in _ON_TOKENS for t in tokens):
        return True
    if any(t in _OFF_TOKENS for t in tokens):
        return False
    return None


def _load_toml(path: Path, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        msg = f"malformed {label} at {path}: {exc}"
        raise TelemetrySettingError(msg) from exc


def _table(container: Mapping[str, Any], key: str, source: Path) -> Mapping[str, Any]:
    value = container.get(key, {})
    if not isinstance(value, dict):
        msg = f"malformed config {source}: '{key}' must be a table, got {type(value).__name__}"
        raise TelemetrySettingError(msg)
    return value


def _bool_key(table: Mapping[str, Any], behaviour: str, source: Path, label: str) -> bool | None:
    if behaviour not in table:
        return None
    value = table[behaviour]
    if not isinstance(value, bool):
        msg = f"malformed config {source}: {label}.{behaviour} must be true or false, got {value!r}"
        raise TelemetrySettingError(msg)
    return value


def _telemetry_layers(
    telemetry: Mapping[str, Any], consumer: str, behaviour: str, source: Path, prefix: str
) -> tuple[bool, str] | None:
    """Consumer subtable beats the generic table inside one file.

    Every behaviour key in both tables is validated on each read, not only the one asked for, so a bad
    value fails loudly whichever behaviour a caller happens to resolve first.
    """
    sub = telemetry.get(consumer)
    if sub is not None and not isinstance(sub, dict):
        msg = f"malformed config {source}: '{prefix}.{consumer}' must be a table, got {type(sub).__name__}"
        raise TelemetrySettingError(msg)
    for name in BEHAVIOURS:
        _bool_key(telemetry, name, source, prefix)
        if sub is not None:
            _bool_key(sub, name, source, f"{prefix}.{consumer}")
    if sub is not None:
        value = _bool_key(sub, behaviour, source, f"{prefix}.{consumer}")
        if value is not None:
            return value, f"{prefix}.{consumer}"
    value = _bool_key(telemetry, behaviour, source, prefix)
    if value is not None:
        return value, prefix
    return None


# ---------------------------------------------------------------------------
# Saved plugin option (settings.json, read-only, fails closed)
# ---------------------------------------------------------------------------

_SETTINGS_CACHE: dict[tuple[str, int, int], tuple[dict[str, Any] | None, str | None]] = {}


def _read_settings(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """``(parsed, error)`` for ``settings.json``; cached per process by (path, mtime, size)."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"cannot stat {path}: {exc}"
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _SETTINGS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result: tuple[dict[str, Any] | None, str | None] = (None, f"cannot read {path} as JSON: {exc}")
    else:
        if isinstance(parsed, dict):
            result = (parsed, None)
        else:
            result = (None, f"{path} is not a JSON object")
    _SETTINGS_CACHE[key] = result
    return result


def _plugin_option(
    registration: Registration, behaviour: str, settings_path: Path
) -> tuple[bool | None, str | None]:
    """``(value, error)``: ``value`` is None for no opinion; ``error`` means fail closed."""
    data, error = _read_settings(settings_path)
    if error is not None:
        return None, error
    if data is None:
        return None, None
    plugin_configs = data.get("pluginConfigs", {})
    if not isinstance(plugin_configs, dict):
        return None, f"{settings_path}: 'pluginConfigs' is not an object"
    # Match pluginConfigs keys directly. Claude Code installs have scopes (user, project, local) and records
    # `enabledPlugins` in the matching settings file, so a project-scope install has no user-level
    # `enabledPlugins` entry although its saved options live in the user's `pluginConfigs`. `enabledPlugins`
    # is therefore used only to choose between several marketplaces' entries for the same plugin.
    prefix = f"{registration.plugin}@"
    candidates = sorted(k for k in plugin_configs if isinstance(k, str) and k.startswith(prefix))
    if not candidates:
        return None, None
    if len(candidates) == 1:
        key = candidates[0]
    else:
        enabled_plugins = data.get("enabledPlugins", {})
        if not isinstance(enabled_plugins, dict):
            return None, (
                f"{settings_path}: pluginConfigs has entries for {candidates} and 'enabledPlugins' "
                "is not an object, so the enabled one cannot be chosen"
            )
        enabled = [k for k in candidates if enabled_plugins.get(k) is True]
        if len(enabled) != 1:
            return None, (
                f"{settings_path}: pluginConfigs has entries for {candidates} and {len(enabled)} of them "
                "are enabled, so the one to read is ambiguous"
            )
        key = enabled[0]
    entry = plugin_configs[key]
    if entry is None:
        return None, None
    if not isinstance(entry, dict):
        return None, f"{settings_path}: pluginConfigs[{key!r}] is not an object"
    options = entry.get("options")
    if options is None:
        return None, None
    if not isinstance(options, dict):
        return None, f"{settings_path}: pluginConfigs[{key!r}].options is not an object"
    option_key = registration.option_for(behaviour)
    if option_key not in options:
        return None, None
    raw = options[option_key]
    if not isinstance(raw, str) or raw not in PLUGIN_OPTION_VALUES:
        return None, (
            f"{settings_path}: pluginConfigs[{key!r}].options.{option_key} is {raw!r}; "
            f"expected one of {PLUGIN_OPTION_VALUES}"
        )
    if raw == "inherit":
        return None, None
    return raw == "on", None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def discover_registration(consumer: str) -> Registration | None:
    """The registration an installed package declared for ``consumer`` through the entry-point group.

    Entry points are written when a package is installed, so an editable install does not see one added
    later until it is reinstalled; callers that know their own registration pass it as ``registration=``.
    """
    from importlib.metadata import entry_points

    for entry in entry_points(group=CONSUMERS_ENTRY_POINT_GROUP):
        if entry.name != consumer:
            continue
        try:
            loaded = entry.load()
            if isinstance(loaded, Registration):
                return loaded
            if isinstance(loaded, Mapping):
                return Registration.from_mapping(loaded)
            _notice(f"entry point {entry.name!r} in {CONSUMERS_ENTRY_POINT_GROUP} is not a mapping; ignored")
        except Exception as exc:
            _notice(f"entry point {entry.name!r} in {CONSUMERS_ENTRY_POINT_GROUP} failed to load ({exc}); ignored")
        return None
    return None


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


def telemetry_setting(
    consumer: str,
    behaviour: str,
    *,
    explicit: bool | None = None,
    registration: Registration | Mapping[str, Any] | None = None,
    config_dir: Path | str | None = None,
    repo_root: Path | None = None,
    user_config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> TelemetryDecision:
    """Resolve ``behaviour`` ("spans" or "shadow") for ``consumer``. See the module docstring for the order.

    Raises:
        TelemetrySettingError: an invalid behaviour variable, or a malformed cisternal configuration file.
    """
    _check_behaviour(behaviour)
    env = os.environ if environ is None else environ

    if registration is not None and not isinstance(registration, Registration):
        registration = Registration.from_mapping(registration)
    registered = registration is not None
    if registration is None:
        registration = discover_registration(consumer)
        registered = registration is not None

    def decision(enabled: bool, layer: str, source: Path | None = None, error: str | None = None) -> TelemetryDecision:
        return TelemetryDecision(consumer, behaviour, enabled, layer, source, error, registered)

    # 1. explicit argument
    if explicit is not None:
        return decision(bool(explicit), "explicit argument")

    # 2. the behaviour's own variable
    var = behaviour_env_var(behaviour)
    own = _parse_switch(env.get(var, ""), f"environment variable {var}")
    if own is not None:
        return decision(own, f"environment variable {var}")

    # 3. the whole-consumer variable
    whole = _consumer_switch(env.get(CONSUMER_ENV_VAR, ""), consumer)
    if whole is not None:
        return decision(whole, f"environment variable {CONSUMER_ENV_VAR}")

    # 4. pyproject.toml of the repository root
    root = repo_root or _find_repo_root()
    if root is not None:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            data = _load_toml(pyproject, "pyproject.toml")
            tool_cisternal = _table(_table(data, "tool", pyproject), "cisternal", pyproject)
            telemetry = _table(tool_cisternal, "telemetry", pyproject)
            hit = _telemetry_layers(telemetry, consumer, behaviour, pyproject, "tool.cisternal.telemetry")
            if hit is not None:
                return decision(hit[0], f"pyproject.toml [{hit[1]}]", pyproject)

    # 5. the user's saved plugin option (fails closed)
    if registration is not None:
        settings_path = claude_settings_path(config_dir, env)
        value, error = _plugin_option(registration, behaviour, settings_path)
        if error is not None:
            _notice(f"{error}; treating {consumer} {behaviour} as off")
            return decision(False, "plugin option (unreadable)", settings_path, error)
        if value is not None:
            return decision(value, "saved plugin option", settings_path)

    # 6. the machine file
    config_file = user_config_file or user_config_path(env)
    if config_file.is_file():
        data = _load_toml(config_file, "user config")
        telemetry = _table(data, "telemetry", config_file)
        hit = _telemetry_layers(telemetry, consumer, behaviour, config_file, "telemetry")
        if hit is not None:
            return decision(hit[0], f"machine file [{hit[1]}]", config_file)

    # 7. the registered default, 8. off
    if registration is not None:
        return decision(registration.default_for(behaviour), "registered default")
    return decision(False, "off (no registered default)")


def consumer_records_dir(
    consumer: str,
    *,
    user_config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, Path] | None:
    """``(directory, machine file)`` from ``[telemetry.<consumer>] records_dir``, or None when unset.

    This is a consumer's own records directory. It is deliberately not cisternal's consumer-agnostic
    ``[telemetry] log_dir``, which would redirect every consumer's records. A leading ``~`` is expanded; a
    relative value resolves against the machine file's directory. Raises on a malformed file or value.
    """
    env = os.environ if environ is None else environ
    config_file = user_config_file or user_config_path(env)
    if not config_file.is_file():
        return None
    data = _load_toml(config_file, "user config")
    telemetry = _table(data, "telemetry", config_file)
    sub = telemetry.get(consumer)
    if sub is None:
        return None
    if not isinstance(sub, dict):
        msg = f"malformed config {config_file}: 'telemetry.{consumer}' must be a table, got {type(sub).__name__}"
        raise TelemetrySettingError(msg)
    if "records_dir" not in sub:
        return None
    raw = sub["records_dir"]
    if not isinstance(raw, str) or not raw.strip():
        msg = f"malformed config {config_file}: telemetry.{consumer}.records_dir must be a non-empty string"
        raise TelemetrySettingError(msg)
    path = Path(raw.strip()).expanduser()
    return (path if path.is_absolute() else config_file.parent / path).resolve(), config_file


# ---------------------------------------------------------------------------
# Machine file writer
# ---------------------------------------------------------------------------


def _toml_value(value: bool | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _edit_table(text: str, header: str, key: str, value_text: str) -> str:
    """Set ``key = value`` inside the ``[header]`` table of ``text``, preserving every other line.

    Replaces the key's line when present, inserts it right after the header when the table exists
    without the key, and appends a new table at the end of the file otherwise.
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{header}]"), None)
    new_line = f"{key} = {value_text}\n"
    if start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend([f"[{header}]\n", new_line])
        return "".join(lines)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
        len(lines),
    )
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith(f"{key} ") or stripped.startswith(f"{key}="):
            lines[i] = new_line
            return "".join(lines)
    if lines[start].endswith("\n"):
        lines.insert(start + 1, new_line)
    else:
        lines[start] += "\n"
        lines.insert(start + 1, new_line)
    return "".join(lines)


def set_machine_value(
    consumer: str,
    key: str,
    value: bool | str,
    *,
    user_config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Write ``key = value`` into ``[telemetry.<consumer>]`` of the machine file; return the file's path.

    Table-aware and line-oriented: every other line is preserved, and the result is parsed with ``tomllib``
    before an atomic replace, so a write that would corrupt the file raises and changes nothing. A symlinked
    file is written through to its target. Last writer wins; there is no locking.
    """
    env = os.environ if environ is None else environ
    link = user_config_file or user_config_path(env)
    target = link.resolve() if link.is_symlink() else link
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    header = f"telemetry.{consumer}"
    if existing:
        updated = _edit_table(existing, header, key, _toml_value(value))
    else:
        updated = (
            "# cisternal per-machine config (edit freely).\n"
            f"[{header}]\n{key} = {_toml_value(value)}\n"
        )
    try:
        parsed = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        msg = f"refusing to write {target}: the edit would make it invalid TOML ({exc}); nothing changed"
        raise TelemetrySettingError(msg) from exc
    written = parsed.get("telemetry", {}).get(consumer, {}).get(key)
    if written != value:
        msg = f"refusing to write {target}: {key} would not read back as {value!r}; nothing changed"
        raise TelemetrySettingError(msg)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.is_file() else 0o644
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return link


@dataclass(frozen=True, slots=True)
class SetResult:
    """What ``set_telemetry_setting`` did and what now decides.

    ``overridden`` is true when the layer that now decides is not the machine file the call just wrote
    (an environment variable, ``pyproject.toml`` or a saved plugin option outranks it, or the saved
    plugin option could not be read), so the write did not change the behaviour. ``decision`` says which.
    """

    path: Path
    decision: TelemetryDecision
    overridden: bool


def set_telemetry_setting(
    consumer: str,
    behaviour: str,
    enabled: bool,
    *,
    registration: Registration | Mapping[str, Any] | None = None,
    config_dir: Path | str | None = None,
    repo_root: Path | None = None,
    user_config_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> SetResult:
    """Write ``[telemetry.<consumer>] <behaviour> = enabled`` to the machine file, then re-resolve.

    The write always happens (it is the owner's stated preference). The returned ``overridden`` flag tells
    a caller such as ``mrx telemetry disable`` to exit nonzero and name ``decision.layer`` when something
    that outranks the machine file still decides.
    """
    _check_behaviour(behaviour)
    path = set_machine_value(consumer, behaviour, bool(enabled), user_config_file=user_config_file, environ=environ)
    decision = telemetry_setting(
        consumer,
        behaviour,
        registration=registration,
        config_dir=config_dir,
        repo_root=repo_root,
        user_config_file=user_config_file,
        environ=environ,
    )
    return SetResult(path, decision, not decision.layer.startswith("machine file"))
