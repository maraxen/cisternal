"""5-layer derived-data resolution hierarchy (spec §3.7).

Resolution precedence:
Layer 1: CLI argument / API parameter
Layer 2: Environment variable (empty, whitespace, or "none" disables; the
         first variable that is SET decides, later variables are not consulted)
Layer 3: pyproject.toml
Layer 4: User config (${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml)
Layer 5: Fallback off (refuses operation)

Contract:
- No default path in library code.
- Report which layer decided each path.
- Fail loudly on malformed configuration files (exit code 3).
- Relative paths in pyproject.toml resolve against the pyproject directory;
  relative paths in the user config resolve against the config file's directory.

This module must not import cisternal.telemetry or cisternal.shadow's package
__init__ at module level: cisternal.shadow.events imports the telemetry
pipeline, and the pipeline imports this module lazily.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Single source of truth for telemetry log-dir env precedence (writer and reader).
LOG_DIR_ENV_VARS: tuple[str, ...] = (
    "CISTERNAL_TELEMETRY_LOG_DIR",
    "CISTERNAL_LOG_DIR",
    "BTH_LOG_DIR",
    "CTXP_LOG_DIR",
)
MODE_STATE_ENV_VAR = "CISTERNAL_MODE_STATE_DIR"


class ResolutionError(RuntimeError):
    """Raised when resolution fails or falls through to Layer 5 (off)."""

    def __init__(self, message: str, exit_code: int = 3) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class LogDirOffError(ResolutionError):
    """log_dir resolved to off: nothing configured (Layer 5) or an env var disabled it.

    Distinct from malformed configuration (plain ResolutionError) so that the
    telemetry writer can fall back to its legacy default for the off cases only.
    """


@dataclass(frozen=True)
class ResolvedPath:
    """Represents a successfully resolved path along with provenance."""

    path: Path
    layer: int
    provenance: str


def find_repo_root(start_dir: Path | None = None) -> Path | None:
    """Find nearest git repository root directory."""
    curr = (start_dir or Path.cwd()).resolve()
    for parent in [curr, *curr.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return None


def env_setting(names: Iterable[str]) -> tuple[str, str] | None:
    """Return (name, raw_value) for the first variable in ``names`` that is SET.

    An empty string counts as set; only an unset variable (None) is skipped.
    """
    for name in names:
        raw = os.getenv(name)
        if raw is not None:
            return name, raw
    return None


def is_disabled_value(raw: str) -> bool:
    """True when an env value means "disabled": empty, whitespace, or "none"."""
    stripped = raw.strip()
    return not stripped or stripped.lower() == "none"


def _section(container: dict[str, Any], key: str, source: Path) -> dict[str, Any]:
    """Return ``container[key]`` as a table, or raise a malformed-config error (exit 3)."""
    value = container.get(key, {})
    if not isinstance(value, dict):
        raise ResolutionError(
            f"Malformed config {source}: '{key}' must be a table, got {type(value).__name__}",
            exit_code=3,
        )
    return value


def _config_path(raw: object, base: Path, key: str, source: Path) -> Path:
    """Resolve a config-file path value; relative values resolve against ``base``."""
    if not isinstance(raw, str) or not raw.strip():
        raise ResolutionError(
            f"Malformed config {source}: '{key}' must be a non-empty string path",
            exit_code=3,
        )
    p = Path(raw.strip())
    return (p if p.is_absolute() else base / p).resolve()


def _load_toml(path: Path, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ResolutionError(f"Malformed {label} at {path}: {exc}", exit_code=3) from exc


def _user_config_path(user_config_file: Path | None) -> Path:
    if user_config_file is not None:
        return Path(user_config_file).resolve()
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "cisternal" / "config.toml"


def resolve_mode_state_dir(
    cli_arg: Path | str | None = None,
    *,
    repo_root: Path | None = None,
    user_config_file: Path | None = None,
) -> ResolvedPath:
    """Resolve directory for mode-state TOML files via 5-layer hierarchy.

    Args:
        cli_arg: Layer 1 CLI argument or API parameter.
        repo_root: Repository root for Layer 3 pyproject.toml inspection.
        user_config_file: Optional override for Layer 4 config.toml.

    Returns:
        ResolvedPath with resolved path, layer index (1-4), and provenance string.

    Raises:
        ResolutionError: On malformed config (exit 3), an env var that disables
            the directory (exit 3, no fall-through), or Layer 5 fallback (exit 3).
    """
    checked_layers: list[str] = []

    # Layer 1: CLI argument / API param
    if cli_arg is not None:
        p = Path(cli_arg).resolve()
        return ResolvedPath(
            path=p,
            layer=1,
            provenance=f"resolved mode_state_dir from Layer 1 (CLI argument): {p}",
        )
    checked_layers.append("Layer 1 (CLI argument: none)")

    # Layer 2: Environment variable (first SET decides; disabled value stops resolution)
    env_val = os.getenv(MODE_STATE_ENV_VAR)
    if env_val is not None:
        if not is_disabled_value(env_val):
            p = Path(env_val.strip()).resolve()
            return ResolvedPath(
                path=p,
                layer=2,
                provenance=f"resolved mode_state_dir from Layer 2 (environment variable {MODE_STATE_ENV_VAR}): {p}",
            )
        raise ResolutionError(
            f"mode_state_dir disabled by environment variable {MODE_STATE_ENV_VAR}={env_val!r}; "
            "unset it to use configuration layers. Layer 5 (off).",
            exit_code=3,
        )
    checked_layers.append(f"Layer 2 (env {MODE_STATE_ENV_VAR}: unset)")

    # Layer 3: pyproject.toml
    root = repo_root or find_repo_root()
    if root is not None:
        pyproj = root / "pyproject.toml"
        if pyproj.is_file():
            data = _load_toml(pyproj, "pyproject.toml")
            tool_cist = _section(_section(data, "tool", pyproj), "cisternal", pyproj)
            shadow_sec = _section(tool_cist, "shadow", pyproj)
            if "mode_state_dir" in shadow_sec:
                p = _config_path(shadow_sec["mode_state_dir"], root, "mode_state_dir", pyproj)
                return ResolvedPath(
                    path=p,
                    layer=3,
                    provenance=f"resolved mode_state_dir from Layer 3 (pyproject.toml [tool.cisternal.shadow]): {p}",
                )
            checked_layers.append(f"Layer 3 (pyproject.toml at {pyproj}: key missing)")
        else:
            checked_layers.append(f"Layer 3 (pyproject.toml at {pyproj}: not found)")
    else:
        checked_layers.append("Layer 3 (pyproject.toml: repo root not found)")

    # Layer 4: User config
    cfg_path = _user_config_path(user_config_file)
    if cfg_path.is_file():
        data = _load_toml(cfg_path, "user config")
        shadow_sec = _section(data, "shadow", cfg_path)
        if "mode_state_dir" in shadow_sec:
            p = _config_path(shadow_sec["mode_state_dir"], cfg_path.parent, "mode_state_dir", cfg_path)
            return ResolvedPath(
                path=p,
                layer=4,
                provenance=f"resolved mode_state_dir from Layer 4 (user config {cfg_path}): {p}",
            )
        checked_layers.append(f"Layer 4 (user config {cfg_path}: key missing)")
    else:
        checked_layers.append(f"Layer 4 (user config {cfg_path}: not found)")

    # Layer 5: Fallback off
    layers_msg = "\n  - ".join(["", *checked_layers])
    raise ResolutionError(
        f"Layer 5 (off): mode_state_dir is not configured. Checked layers:{layers_msg}",
        exit_code=3,
    )


def resolve_log_dir(
    cli_arg: Path | str | None = None,
    *,
    repo_root: Path | None = None,
    user_config_file: Path | None = None,
) -> ResolvedPath:
    """Resolve directory for telemetry JSONL records via 5-layer hierarchy.

    Layer 2 walks ``LOG_DIR_ENV_VARS`` in order; the first variable that is SET
    decides. If it is empty, whitespace, or "none", log_dir is disabled and
    resolution stops with LogDirOffError (no fall-through to later variables or
    to Layers 3/4).

    Args:
        cli_arg: Layer 1 CLI argument or API parameter.
        repo_root: Repository root for Layer 3 pyproject.toml inspection.
        user_config_file: Optional override for Layer 4 config.toml.

    Returns:
        ResolvedPath with resolved path, layer index (1-4), and provenance string.

    Raises:
        LogDirOffError: Env var disabled log_dir, or Layer 5 (off), both exit 3.
        ResolutionError: On malformed config (exit 3).
    """
    checked_layers: list[str] = []

    # Layer 1: CLI argument
    if cli_arg is not None:
        p = Path(cli_arg).resolve()
        return ResolvedPath(
            path=p,
            layer=1,
            provenance=f"resolved log_dir from Layer 1 (CLI argument): {p}",
        )
    checked_layers.append("Layer 1 (CLI argument: none)")

    # Layer 2: Environment variables (shared precedence, first SET decides)
    hit = env_setting(LOG_DIR_ENV_VARS)
    if hit is not None:
        name, raw = hit
        if not is_disabled_value(raw):
            p = Path(raw.strip()).resolve()
            return ResolvedPath(
                path=p,
                layer=2,
                provenance=f"resolved log_dir from Layer 2 (environment variable {name}): {p}",
            )
        raise LogDirOffError(
            f"log_dir disabled by environment variable {name}={raw!r}; "
            f"unset {name} to use configuration layers. Layer 5 (off).",
            exit_code=3,
        )
    checked_layers.append(f"Layer 2 (env {'/'.join(LOG_DIR_ENV_VARS)}: unset)")

    # Layer 3: pyproject.toml
    root = repo_root or find_repo_root()
    if root is not None:
        pyproj = root / "pyproject.toml"
        if pyproj.is_file():
            data = _load_toml(pyproj, "pyproject.toml")
            tool_cist = _section(_section(data, "tool", pyproj), "cisternal", pyproj)
            telem_sec = _section(tool_cist, "telemetry", pyproj)
            if "log_dir" in telem_sec:
                p = _config_path(telem_sec["log_dir"], root, "log_dir", pyproj)
                return ResolvedPath(
                    path=p,
                    layer=3,
                    provenance=f"resolved log_dir from Layer 3 (pyproject.toml [tool.cisternal.telemetry]): {p}",
                )
            checked_layers.append(f"Layer 3 (pyproject.toml at {pyproj}: key missing)")
        else:
            checked_layers.append(f"Layer 3 (pyproject.toml at {pyproj}: not found)")
    else:
        checked_layers.append("Layer 3 (pyproject.toml: repo root not found)")

    # Layer 4: User config
    cfg_path = _user_config_path(user_config_file)
    if cfg_path.is_file():
        data = _load_toml(cfg_path, "user config")
        telem_sec = _section(data, "telemetry", cfg_path)
        if "log_dir" in telem_sec:
            p = _config_path(telem_sec["log_dir"], cfg_path.parent, "log_dir", cfg_path)
            return ResolvedPath(
                path=p,
                layer=4,
                provenance=f"resolved log_dir from Layer 4 (user config {cfg_path}): {p}",
            )
        checked_layers.append(f"Layer 4 (user config {cfg_path}: key missing)")
    else:
        checked_layers.append(f"Layer 4 (user config {cfg_path}: not found)")

    # Layer 5: Fallback off (config error exit code 3)
    layers_msg = "\n  - ".join(["", *checked_layers])
    raise LogDirOffError(
        f"Layer 5 (off): log_dir is not configured. Checked layers:{layers_msg}",
        exit_code=3,
    )
