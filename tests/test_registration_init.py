"""Tests for the cisternal top-level M2 public API surface (src/cisternal/__init__.py).

Verifies that all M2 symbols are importable from the cisternal top-level package
and that the exported objects are the canonical implementations.

Acceptance criteria exercised:
  AC-M2-1  — top-level tool is the same object as registration.decorator.tool
  AC-M2-7  — @cisternal.tool(registry="bathos") isolates to named registry
  AC-M2-9  — cisternal.wire() raises CisternalWireError on missing expected tools
  AC-M2-12 — cisternal.clear_registry() empties the default partition
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tomllib
from pathlib import Path

import fastmcp
import pytest

# --- M2 top-level imports (the public surface validated here) ---
import cisternal
from cisternal import (
    CisternalWireError,
    clear_registry,
    tool,
    wire,
)
from cisternal.registration.registry import _registry


# ---------------------------------------------------------------------------
# Fixture: clean state before and after each test (A7)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registries():
    """Wipe all known partitions before and after every test (A7)."""
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)
    yield
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)


# ---------------------------------------------------------------------------
# Top-level symbol availability
# ---------------------------------------------------------------------------

class TestTopLevelExports:
    """Verify all M2 symbols are reachable from the cisternal top-level package."""

    def test_tool_importable_from_top_level(self):
        """cisternal.tool is importable via top-level 'from cisternal import tool'."""
        assert callable(tool)

    def test_wire_importable_from_top_level(self):
        """cisternal.wire is importable via top-level 'from cisternal import wire'."""
        assert callable(wire)

    def test_cisternal_wire_error_importable(self):
        """cisternal.CisternalWireError is importable from top level."""
        assert issubclass(CisternalWireError, Exception)

    def test_clear_registry_importable_from_top_level(self):
        """cisternal.clear_registry is importable from top level."""
        assert callable(clear_registry)

    def test_wired_registry_accessible(self):
        """cisternal.WiredRegistry is accessible via lazy __getattr__."""
        WiredRegistry = cisternal.WiredRegistry
        assert WiredRegistry is not None

    def test_m1_exports_intact(self):
        """M1 telemetry exports are still present after M2 additions."""
        assert callable(cisternal.init)
        assert callable(cisternal.emit_event)
        assert callable(cisternal.span)
        assert callable(cisternal.aspan)
        assert callable(cisternal.status)

    def test_all_contains_m2_symbols(self):
        """__all__ includes all M2 public symbols."""
        assert "tool" in cisternal.__all__
        assert "wire" in cisternal.__all__
        assert "WiredRegistry" in cisternal.__all__
        assert "CisternalWireError" in cisternal.__all__
        assert "clear_registry" in cisternal.__all__

    def test_wire_visible_in_dir(self):
        """Issue #18: `wire` (and other __getattr__-lazy-loaded symbols) must
        show up in dir(cisternal), not just __all__ -- the default dir(module)
        only reflects real __dict__ entries, silently omitting anything that
        only resolves via module-level __getattr__."""
        assert "wire" in dir(cisternal)
        assert "WiredRegistry" in dir(cisternal)

    def test_all_preserves_m1_symbols(self):
        """__all__ still includes all M1 telemetry public symbols."""
        assert "init" in cisternal.__all__
        assert "emit_event" in cisternal.__all__
        assert "span" in cisternal.__all__
        assert "aspan" in cisternal.__all__
        assert "status" in cisternal.__all__


# ---------------------------------------------------------------------------
# AC-M2-1: top-level tool is the canonical marker (pure passthrough)
# ---------------------------------------------------------------------------

class TestTopLevelToolIsCanonical:
    """AC-M2-1: cisternal.tool from the top level is the same object as
    cisternal.registration.decorator.tool, and decorated_fn is fn."""

    def test_top_level_tool_is_registration_tool(self):
        """cisternal.tool is the same object as cisternal.registration.decorator.tool."""
        from cisternal.registration.decorator import tool as reg_tool
        assert tool is reg_tool

    def test_tool_decorator_identity_via_top_level(self):
        """AC-M2-1: using top-level cisternal.tool — decorated_fn is fn."""
        def my_fn(x: int) -> int:
            return x

        decorated = tool(my_fn)
        assert decorated is my_fn

    def test_tool_iscoroutinefunction_preserved_via_top_level(self):
        """AC-M2-1: iscoroutinefunction not changed by cisternal.tool (top-level)."""
        @tool
        def sync_fn() -> None:
            pass

        @tool
        async def async_fn() -> None:
            pass

        assert not asyncio.iscoroutinefunction(sync_fn)
        assert asyncio.iscoroutinefunction(async_fn)


# ---------------------------------------------------------------------------
# AC-M2-7: named registry isolation via top-level @cisternal.tool
# ---------------------------------------------------------------------------

class TestNamedRegistryViaTopLevel:
    """AC-M2-7: @cisternal.tool(registry="bathos") isolates to named partition."""

    def test_named_registry_isolation_via_top_level_import(self):
        """AC-M2-7: using top-level 'tool' — named partition is isolated."""

        @tool(registry="bathos")
        def bathos_fn() -> None:
            pass

        assert "bathos_fn" in _registry("bathos")
        assert "bathos_fn" not in _registry("default")


# ---------------------------------------------------------------------------
# AC-M2-9: CisternalWireError from top-level wire()
# ---------------------------------------------------------------------------

class TestWireErrorViaTopLevel:
    """AC-M2-9: cisternal.wire() raises CisternalWireError on missing expected tools."""

    def test_wire_raises_cisternalwireerror_missing_tool(self):
        """AC-M2-9: top-level wire() raises CisternalWireError with .missing attribute."""

        @tool
        def present_tool(x: int) -> int:
            return x

        server = fastmcp.FastMCP("test-init-wire-error")
        with pytest.raises(CisternalWireError) as exc_info:
            wire(server, expected=["missing_tool", "present_tool"])

        err = exc_info.value
        assert hasattr(err, "missing")
        assert "missing_tool" in err.missing
        assert "present_tool" not in err.missing


# ---------------------------------------------------------------------------
# AC-M2-12: top-level clear_registry()
# ---------------------------------------------------------------------------

class TestClearRegistryViaTopLevel:
    """AC-M2-12: cisternal.clear_registry() empties the default registry."""

    def test_clear_registry_empties_default_partition(self):
        """AC-M2-12: calling cisternal.clear_registry() from top-level empties 'default'."""

        @tool
        def my_tool() -> None:
            pass

        assert "my_tool" in _registry("default")
        clear_registry()
        assert len(_registry("default")) == 0

    def test_clear_registry_named_partition_via_top_level(self):
        """AC-M2-13: clear_registry(name='bathos') via top-level leaves 'default' untouched."""

        @tool
        def default_tool() -> None:
            pass

        @tool(registry="bathos")
        def bathos_tool() -> None:
            pass

        clear_registry(name="bathos")
        assert len(_registry("bathos")) == 0
        assert "default_tool" in _registry("default")


# ---------------------------------------------------------------------------
# T5 (cisternal #30): eager CLI-contract exports and import-cycle checks
# ---------------------------------------------------------------------------

_CLI_CONTRACT_NAMES = (
    "CliContract",
    "CliOption",
    "CliContext",
    "json_option",
    "default_report",
    "exit_code_attr",
    "cli_command",
    "cli_group",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_fresh(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter (clean sys.modules)."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestCliContractExports:
    """Spec 4 'Exports': the eight CLI-contract names are public on both packages."""

    @pytest.mark.parametrize("name", _CLI_CONTRACT_NAMES)
    def test_in_all_and_dir_of_top_level(self, name):
        assert name in cisternal.__all__
        assert name in dir(cisternal)
        assert hasattr(cisternal, name)

    @pytest.mark.parametrize("name", _CLI_CONTRACT_NAMES)
    def test_in_all_and_dir_of_registration(self, name):
        import cisternal.registration as reg

        assert name in reg.__all__
        assert name in dir(reg)
        assert hasattr(reg, name)

    @pytest.mark.parametrize("name", _CLI_CONTRACT_NAMES)
    def test_same_object_as_cli_contract_module(self, name):
        import cisternal.registration as reg
        from cisternal.registration import cli_contract

        canonical = getattr(cli_contract, name)
        assert getattr(cisternal, name) is canonical
        assert getattr(reg, name) is canonical

    def test_wire_bits_still_exported(self):
        """The eager additions leave the lazy wire/WiredRegistry exports intact."""
        import cisternal.registration as reg

        assert "wire" in reg.__all__ and "WiredRegistry" in reg.__all__
        assert "wire" in dir(cisternal) and "WiredRegistry" in dir(cisternal)


class TestCliContractImportSafety:
    """R10: the exports are fastmcp-free and cycle-free, in both import orders."""

    def test_fastmcp_free_import(self):
        proc = _run_fresh(
            'import sys; sys.modules["fastmcp"]=None; import cisternal; '
            "cisternal.CliContract; cisternal.cli_group"
        )
        assert proc.returncode == 0, proc.stderr

    def test_fastmcp_free_registration_import(self):
        names = ", ".join(_CLI_CONTRACT_NAMES)
        proc = _run_fresh(
            'import sys; sys.modules["fastmcp"]=None; '
            f"from cisternal.registration import {names}"
        )
        assert proc.returncode == 0, proc.stderr

    def test_import_adapters_cli_then_cisternal(self):
        proc = _run_fresh("import cisternal.adapters.cli; import cisternal; cisternal.cli_group")
        assert proc.returncode == 0, proc.stderr

    def test_import_cisternal_then_adapters_cli(self):
        proc = _run_fresh("import cisternal; import cisternal.adapters.cli; cisternal.cli_group")
        assert proc.returncode == 0, proc.stderr

    def test_package_import_does_not_pull_adapters_cli(self):
        """cli_contract imports adapters.cli lazily (R10), so the eager package
        import must not load it at module scope."""
        proc = _run_fresh(
            "import sys; import cisternal; "
            "assert 'cisternal.adapters.cli' not in sys.modules, 'adapters.cli loaded eagerly'"
        )
        assert proc.returncode == 0, proc.stderr

    def test_group_cache_lives_in_cli_contract(self):
        """wired re-exports the very dict that cli_contract owns."""
        from cisternal.registration import cli_contract, wired

        assert wired._CLI_SUBAPPS is cli_contract._CLI_SUBAPPS
        assert wired._get_or_create_subapp is cli_contract._get_or_create_subapp


class TestCycloptsBound:
    """R3: cyclopts is pinned below the unverified 5.x line."""

    def test_pyproject_pins_cyclopts_upper_bound(self):
        data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
        deps = data["project"]["dependencies"]
        assert "cyclopts>=4.18.0,<5" in deps, deps
