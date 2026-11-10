"""5-layer derived-data resolution hierarchy (spec §3.7).

Resolution precedence:
Layer 1: CLI argument / API parameter
Layer 2: Environment variable (empty string or "none" disables)
Layer 3: pyproject.toml
Layer 4: User config (${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml)
Layer 5: Fallback off (refuses operation)

Contract:
- No default path in library code.
- Report which layer decided each path.
- Fail loudly on malformed configuration files (exit code 3).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ResolutionError(RuntimeError):
    """Raised when resolution fails or falls through to Layer 5 (off)."""

    def __init__(self, message: str, exit_code: int = 3) -> None:
        super().__init__(message)
        self.exit_code = exit_code


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
        ResolutionError: On malformed config (exit 3) or Layer 5 fallback (exit 3).
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

    # Layer 2: Environment variable
    env_val = os.getenv("CISTERNAL_MODE_STATE_DIR")
    if env_val is not None:
        stripped = env_val.strip()
        if stripped and stripped.lower() != "none":
            p = Path(stripped).resolve()
            return ResolvedPath(
                path=p,
                layer=2,
                provenance=f"resolved mode_state_dir from Layer 2 (environment variable CISTERNAL_MODE_STATE_DIR): {p}",
            )
        checked_layers.append(f"Layer 2 (env CISTERNAL_MODE_STATE_DIR: {env_val!r} disabled)")
    else:
        checked_layers.append("Layer 2 (env CISTERNAL_MODE_STATE_DIR: unset)")

    # Layer 3: pyproject.toml
    root = repo_root or find_repo_root()
    if root is not None:
        pyproj = root / "pyproject.toml"
        if pyproj.is_file():
            try:
                data = tomllib.loads(pyproj.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ResolutionError(
                    f"Malformed pyproject.toml at {pyproj}: {exc}",
                    exit_code=3,
                ) from exc

            tool_cist = data.get("tool", {}).get("cisternal", {})
            shadow_sec = tool_cist.get("shadow", {})
            if "mode_state_dir" in shadow_sec:
                raw_dir = shadow_sec["mode_state_dir"]
                p = (root / raw_dir).resolve() if not Path(raw_dir).is_absolute() else Path(raw_dir)
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
    if user_config_file is not None:
        cfg_path = Path(user_config_file).resolve()
    else:
        xdg = os.getenv("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        cfg_path = base / "cisternal" / "config.toml"

    if cfg_path.is_file():
        try:
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ResolutionError(
                f"Malformed user config at {cfg_path}: {exc}",
                exit_code=3,
            ) from exc

        shadow_sec = data.get("shadow", {})
        if "mode_state_dir" in shadow_sec:
            raw_dir = shadow_sec["mode_state_dir"]
            p = Path(raw_dir).resolve()
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

    Args:
        cli_arg: Layer 1 CLI argument or API parameter.
        repo_root: Repository root for Layer 3 pyproject.toml inspection.
        user_config_file: Optional override for Layer 4 config.toml.

    Returns:
        ResolvedPath with resolved path, layer index (1-4), and provenance string.

    Raises:
        ResolutionError: On malformed config (exit 3) or Layer 5 fallback (exit 2).
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

    # Layer 2: Environment variable (CISTERNAL_TELEMETRY_LOG_DIR > CISTERNAL_LOG_DIR)
    env_val = os.getenv("CISTERNAL_TELEMETRY_LOG_DIR") or os.getenv("CISTERNAL_LOG_DIR")
    if env_val is not None:
        stripped = env_val.strip()
        if stripped and stripped.lower() != "none":
            p = Path(stripped).resolve()
            return ResolvedPath(
                path=p,
                layer=2,
                provenance=f"resolved log_dir from Layer 2 (environment variable): {p}",
            )
        checked_layers.append(f"Layer 2 (env: {env_val!r} disabled)")
    else:
        checked_layers.append("Layer 2 (env CISTERNAL_TELEMETRY_LOG_DIR/CISTERNAL_LOG_DIR: unset)")

    # Layer 3: pyproject.toml
    root = repo_root or find_repo_root()
    if root is not None:
        pyproj = root / "pyproject.toml"
        if pyproj.is_file():
            try:
                data = tomllib.loads(pyproj.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ResolutionError(
                    f"Malformed pyproject.toml at {pyproj}: {exc}",
                    exit_code=3,
                ) from exc

            tool_cist = data.get("tool", {}).get("cisternal", {})
            telem_sec = tool_cist.get("telemetry", {})
            if "log_dir" in telem_sec:
                raw_dir = telem_sec["log_dir"]
                p = (root / raw_dir).resolve() if not Path(raw_dir).is_absolute() else Path(raw_dir)
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
    if user_config_file is not None:
        cfg_path = Path(user_config_file).resolve()
    else:
        xdg = os.getenv("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        cfg_path = base / "cisternal" / "config.toml"

    if cfg_path.is_file():
        try:
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ResolutionError(
                f"Malformed user config at {cfg_path}: {exc}",
                exit_code=3,
            ) from exc

        telem_sec = data.get("telemetry", {})
        if "log_dir" in telem_sec:
            raw_dir = telem_sec["log_dir"]
            p = Path(raw_dir).resolve()
            return ResolvedPath(
                path=p,
                layer=4,
                provenance=f"resolved log_dir from Layer 4 (user config {cfg_path}): {p}",
            )
        checked_layers.append(f"Layer 4 (user config {cfg_path}: key missing)")
    else:
        checked_layers.append(f"Layer 4 (user config {cfg_path}: not found)")

    # Layer 5: Fallback off (exit code 2 for log_dir refusal)
    layers_msg = "\n  - ".join(["", *checked_layers])
    raise ResolutionError(
        f"Layer 5 (off): log_dir is not configured. Checked layers:{layers_msg}",
        exit_code=2,
    )
