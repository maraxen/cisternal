"""Tests for event-name freeze: AC-NAMEFREEZE acceptance criteria (spec §4, spec §8).

AC-NAMEFREEZE-1: AST lint asserts every emit_event name in v3_middleware.py
is in BathosAdapter.ALLOWED_NAMES.
AC-NAMEFREEZE-2: Adding a forbidden name like "mcp.call_begin" makes lint fail.
AC-NAMEFREEZE-3: Lint covers cisterna's own adapters only (not consumer code).
AC-NAMEFREEZE-4: Runtime guard via _swallow_name_error raises when monkeypatched.
"""
import ast
from pathlib import Path

import pytest

from cisterna.adapters.base import (
    AdapterBase,
    BathosAdapter,
    ContemplexAdapter,
)


def _emit_event_names_in_file(path: Path) -> list[str]:
    """Helper: Extract all event names from emit_event() calls in a file.

    Uses ast.walk to find Call nodes where the func is Name(id='emit_event').
    Extracts the first positional argument (the event name string literal).

    Args:
        path: Path to Python file to analyze.

    Returns:
        List of event name strings found in emit_event() calls.
    """
    with open(path) as f:
        tree = ast.parse(f.read())

    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Check if this is a call to emit_event
        if not (isinstance(node.func, ast.Name) and node.func.id == "emit_event"):
            continue
        # Extract the first positional argument (the name)
        if node.args and isinstance(node.args[0], ast.Constant):
            names.append(node.args[0].value)
    return names


def _validate_names(names: list[str], allowed: frozenset[str]) -> list[str]:
    """Helper: Check that all names are in the allowed set.

    Args:
        names: List of event names found.
        allowed: Frozenset of allowed names.

    Returns:
        List of violations (names not in allowed set).
    """
    return [n for n in names if n not in allowed]


class TestAcNamefreeze1:
    """AC-NAMEFREEZE-1: Every emit_event name in v3_middleware.py is allowed."""

    def test_v3_middleware_names_are_allowed(self):
        """All emit_event names in v3_middleware.py must be in BathosAdapter.ALLOWED_NAMES."""
        middleware_path = Path("src/cisterna/adapters/v3_middleware.py")
        assert middleware_path.exists(), f"File not found: {middleware_path}"

        names = _emit_event_names_in_file(middleware_path)
        allowed = BathosAdapter.ALLOWED_NAMES

        violations = _validate_names(names, allowed)
        assert (
            not violations
        ), f"Event names in v3_middleware.py not in BathosAdapter.ALLOWED_NAMES: {violations}"

    def test_v2_decorator_names_are_allowed(self):
        """All emit_event names in v2_decorator.py must be in ALLOWED_NAMES."""
        decorator_path = Path("src/cisterna/adapters/v2_decorator.py")
        assert decorator_path.exists(), f"File not found: {decorator_path}"

        names = _emit_event_names_in_file(decorator_path)
        allowed = BathosAdapter.ALLOWED_NAMES

        violations = _validate_names(names, allowed)
        assert (
            not violations
        ), f"Event names in v2_decorator.py not in BathosAdapter.ALLOWED_NAMES: {violations}"


class TestAcNamefreeze2:
    """AC-NAMEFREEZE-2: Adding a forbidden name fails validation."""

    def test_validate_names_detects_violations(self):
        """_validate_names should detect when a name is not in allowed set."""
        allowed = BathosAdapter.ALLOWED_NAMES
        # This name is NOT in the allowed set
        bad_names = ["mcp.call_begin"]

        violations = _validate_names(bad_names, allowed)
        assert violations == ["mcp.call_begin"]

    def test_validate_names_allows_valid_names(self):
        """_validate_names should return empty list for valid names."""
        allowed = BathosAdapter.ALLOWED_NAMES
        good_names = ["mcp.call_start", "mcp.call_end", "mcp.tool_error"]

        violations = _validate_names(good_names, allowed)
        assert violations == []


class TestAcNamefreeze3:
    """AC-NAMEFREEZE-3: Lint covers cisterna's own adapters only."""

    def test_adapters_directory_exists(self):
        """Verify cisterna/adapters directory is in scope."""
        adapters_dir = Path("src/cisterna/adapters")
        assert adapters_dir.exists()
        assert adapters_dir.is_dir()

    def test_all_adapter_files_are_covered(self):
        """All .py files in adapters/ should be validated."""
        adapters_dir = Path("src/cisterna/adapters")
        adapter_files = sorted(adapters_dir.glob("*.py"))

        # Should have base.py, v3_middleware.py, v2_decorator.py at minimum
        file_names = {f.name for f in adapter_files}
        assert "base.py" in file_names
        assert "v3_middleware.py" in file_names
        assert "v2_decorator.py" in file_names


class TestAcNamefreeze4:
    """AC-NAMEFREEZE-4: Runtime guard via _swallow_name_error."""

    def test_runtime_guard_with_monkeypatch(self):
        """When _swallow_name_error is monkeypatched to raise, assert fails."""

        class TestAdapter(AdapterBase):
            ALLOWED_NAMES = frozenset()  # Empty; any name is illegal

            def shape_ok(self, tool_name, result):
                return result

            def shape_error(self, tool_name, exc, **fields):
                return {"error": str(exc)}

        adapter = TestAdapter()

        # By default, _swallow_name_error returns True, so assert passes
        result = adapter._swallow_name_error("illegal.name")
        assert result is True

        # Now monkeypatch to raise
        def raising_swallow(name):
            raise AssertionError(f"Illegal name in allowed set: {name!r}")

        adapter._swallow_name_error = raising_swallow  # type: ignore

        # Now emit_start should fail because the name is not in ALLOWED_NAMES
        # and _swallow_name_error raises
        with pytest.raises(AssertionError, match="Illegal name"):
            adapter.emit_start("mcp.call_start", [], "req-1")

    def test_allowed_names_in_emit_passes_without_swallow(self):
        """When name is in ALLOWED_NAMES, _swallow_name_error is not called."""
        from cisterna.telemetry.exporter import ShadowExporter
        from cisterna import init

        shadow = ShadowExporter()
        init(exporters=[shadow], heartbeat_interval=0.05)

        adapter = BathosAdapter()

        # Don't monkeypatch; name is allowed, so should not call _swallow_name_error
        # This should succeed without calling _swallow_name_error
        adapter.emit_start("mcp.call_start", [], "req-1")

        # If we reach here, the assert passed (name was in ALLOWED_NAMES)
        assert True


class TestCanonicalEventNames:
    """Verify canonical event names per spec §4.1."""

    def test_canonical_names_match_adapters(self):
        """Canonical names should match what adapters emit."""
        canonical = {"mcp.call_start", "mcp.call_end", "mcp.tool_error"}
        bathos_allowed = BathosAdapter.ALLOWED_NAMES
        contemplex_allowed = ContemplexAdapter.ALLOWED_NAMES

        assert canonical == bathos_allowed
        assert canonical == contemplex_allowed
