"""Where the shared Claude plugin marketplace lives (resolved, never baked in).

The marketplace is derived data -- every plugin under it is rebuilt from a
manifest or a packaged snapshot -- so its location is configuration.
Resolution order (first hit wins; :func:`marketplace_root_source` says which):

1. explicit argument (``--marketplace``);
2. ``$CISTERNAL_PLUGIN_MARKETPLACE`` (``none``/empty disables -> error);
3. ``[tool.cisternal] plugin_marketplace`` in the nearest ``pyproject.toml``
   at or above the start dir (relative paths resolve against that file);
4. ``plugin_marketplace`` in ``${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml``
   (per machine; relative paths resolve against the config dir).

When none of these is set, :func:`resolve_marketplace_root` *generates*
layer 4: it writes ``plugin_marketplace = "~/.cisternal/claude-plugin-marketplace"``
(the family marketplace) into the user config file, says so on stderr, and
uses it. The machine's default therefore always lives in that one file, where
it can be read and changed -- resolution itself never falls back to a path
the config does not name. ``$CISTERNAL_PLUGIN_MARKETPLACE=none`` opts out
(an error instead). :func:`marketplace_root_source` is read-only and never
generates anything.

A malformed pyproject/config file raises ``ValueError`` rather than being
skipped.
"""

from __future__ import annotations

import os
import sys
import tempfile
import tomllib
from pathlib import Path

ENV_VAR = "CISTERNAL_PLUGIN_MARKETPLACE"
CONFIG_KEY = "plugin_marketplace"
PYPROJECT_TABLE = "cisternal"  # [tool.cisternal]
# The value written into a freshly generated user config (kept unexpanded, so
# the file stays portable across home directories).
GENERATED_DEFAULT = "~/.cisternal/claude-plugin-marketplace"

HOW_TO_CONFIGURE = (
    "no plugin marketplace location is configured. Set one of: "
    f"--marketplace PATH; ${ENV_VAR}=PATH; "
    f"[tool.{PYPROJECT_TABLE}] {CONFIG_KEY} = \"PATH\" in pyproject.toml; or "
    f"{CONFIG_KEY} = \"PATH\" in ~/.config/cisternal/config.toml"
)


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "cisternal" / "config.toml"


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path}: invalid TOML: {exc}"
        raise ValueError(msg) from exc


def _value(raw: object, where: Path) -> str:
    if not isinstance(raw, str) or not raw.strip():
        msg = f"{where}: {CONFIG_KEY} must be a non-empty string, got {raw!r}"
        raise ValueError(msg)
    return raw.strip()


def _table(raw: object, where: Path, name: str) -> dict:
    if not isinstance(raw, dict):
        msg = f"{where}: [{name}] must be a table, got {type(raw).__name__}"
        raise ValueError(msg)
    return raw


def _nearest_pyproject_value(start: Path) -> tuple[Path, Path] | None:
    """(resolved root, pyproject path) from the nearest pyproject with the key."""
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if not candidate.is_file():
            continue
        tool = _table(_read_toml(candidate).get("tool", {}), candidate, "tool")
        table = _table(tool.get(PYPROJECT_TABLE, {}), candidate, f"tool.{PYPROJECT_TABLE}")
        if CONFIG_KEY in table:
            raw = _value(table[CONFIG_KEY], candidate)
            return (directory / Path(raw).expanduser()).resolve(), candidate
    return None


def marketplace_root_source(
    explicit: Path | str | None = None,
    *,
    start: Path | None = None,
) -> tuple[Path | None, str]:
    """``(root or None, which layer decided)``. See the module docstring for the order."""
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser().resolve(), "argument"

    if ENV_VAR in os.environ:
        value = os.environ[ENV_VAR].strip()
        if value.lower() in {"", "none"}:
            return None, f"${ENV_VAR} (disabled)"
        return Path(value).expanduser().resolve(), f"${ENV_VAR}"

    hit = _nearest_pyproject_value((start or Path.cwd()).resolve())
    if hit is not None:
        root, pyproject = hit
        return root, f"[tool.{PYPROJECT_TABLE}] in {pyproject}"

    config = user_config_path()
    if config.is_file():
        doc = _read_toml(config)
        if CONFIG_KEY in doc:
            raw = _value(doc[CONFIG_KEY], config)
            return (config.parent / Path(raw).expanduser()).resolve(), str(config)

    return None, "unconfigured"


def write_user_config(value: str = GENERATED_DEFAULT) -> Path:
    """Record ``plugin_marketplace = value`` in the user config file; return its path.

    Creates the file (and its directory) if missing. An existing file that
    lacks the key gets it as the first line -- a top-level key must precede
    any table to stay top-level -- and nothing else in it changes. An existing
    key is left alone. Written atomically (temp file + rename), so a
    concurrent reader never sees a half-written file. A symlinked config
    (e.g. from a dotfiles repo) is written through to its target, keeping
    the link and the target's permissions.
    """
    link = user_config_path()
    config = link.resolve() if link.is_symlink() else link
    existing = config.read_text(encoding="utf-8") if config.is_file() else None
    if existing is not None and CONFIG_KEY in _read_toml(config):
        return config
    header = (
        "# cisternal per-machine config (generated; edit freely).\n"
        "# Shared Claude plugin marketplace used by `<tool> plugin install` and\n"
        "# `cisternal assets publish-shared` / `update-all`.\n"
    )
    line = f"{CONFIG_KEY} = {_toml_string(value)}\n"
    text = header + line if existing is None else line + existing
    config.parent.mkdir(parents=True, exist_ok=True)
    mode = config.stat().st_mode & 0o777 if existing is not None else 0o644
    fd, tmp = tempfile.mkstemp(dir=config.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)  # mkstemp creates 0600
        os.replace(tmp, config)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return link


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def resolve_marketplace_root(explicit: Path | str | None = None) -> Path:
    """The marketplace root, generating the user config entry when nothing is configured.

    Raises ``ValueError`` only when the location is explicitly disabled
    (``$CISTERNAL_PLUGIN_MARKETPLACE=none``) or a config file is malformed.
    """
    root, source = marketplace_root_source(explicit)
    if root is not None:
        return root
    if source != "unconfigured":
        msg = f"{HOW_TO_CONFIGURE} [resolver: {source}]"
        raise ValueError(msg)
    config = write_user_config()
    print(
        f"cisternal: no plugin marketplace configured; wrote "
        f"{CONFIG_KEY} = {_toml_string(GENERATED_DEFAULT)} to {config}",
        file=sys.stderr,
    )
    root, _ = marketplace_root_source()
    if root is None:  # pragma: no cover - the write above guarantees a value
        msg = f"{HOW_TO_CONFIGURE} [resolver: generated {config} did not resolve]"
        raise ValueError(msg)
    return root
