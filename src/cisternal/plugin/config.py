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

Otherwise nothing is configured and callers fail with :data:`HOW_TO_CONFIGURE`
-- there is no default path in this library; a machine's default lives in its
config file. When the pre-resolver location (``~/.cisternal/claude-plugin-marketplace``)
exists, the error names the exact config line that keeps using it.
A malformed pyproject/config file raises ``ValueError`` rather than being
skipped.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ENV_VAR = "CISTERNAL_PLUGIN_MARKETPLACE"
CONFIG_KEY = "plugin_marketplace"
PYPROJECT_TABLE = "cisternal"  # [tool.cisternal]
# Where publish-shared used to default to; only ever suggested, never used.
LEGACY_ROOT = Path("~/.cisternal/claude-plugin-marketplace")

HOW_TO_CONFIGURE = (
    "no plugin marketplace location is configured. Set one of: "
    f"--marketplace PATH; ${ENV_VAR}=PATH; "
    f"[tool.{PYPROJECT_TABLE}] {CONFIG_KEY} = \"PATH\" in pyproject.toml; or "
    f"{CONFIG_KEY} = \"PATH\" in ~/.config/cisternal/config.toml "
    f"(e.g. {LEGACY_ROOT}, the family marketplace)"
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


def resolve_marketplace_root(explicit: Path | str | None = None) -> Path:
    """The marketplace root, or ``ValueError(HOW_TO_CONFIGURE)`` when none is configured."""
    root, source = marketplace_root_source(explicit)
    if root is None:
        msg = f"{HOW_TO_CONFIGURE} [resolver: {source}]"
        if LEGACY_ROOT.expanduser().is_dir():
            msg += (
                f". To keep using the existing {LEGACY_ROOT}, add to {user_config_path()}: "
                f'{CONFIG_KEY} = "{LEGACY_ROOT.expanduser()}"'
            )
        raise ValueError(msg)
    return root
