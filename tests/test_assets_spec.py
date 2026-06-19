"""Tests for AC-M3-1, AC-M3-2, AC-M3-3 — registry_assets / AssetSpec extraction.

AC-M3-1: registry_assets on empty/unknown registry returns () and never raises.
AC-M3-2: ToolEntry -> AssetSpec: name, cleandoc first-paragraph description with a
          MULTILINE docstring, signature param names; verifies _snapshot coupling by
          registering a real @cisterna.tool.
AC-M3-3: A tool whose inspect.signature raises (any Exception) → params=() + WARNING
          is emitted; a second well-formed tool in the same bundle still exports.
"""

from __future__ import annotations

import logging

import pytest

import cisterna
from cisterna.assets.source import registry_assets


# ---------------------------------------------------------------------------
# AC-M3-1: empty/unknown registry → () never raises
# ---------------------------------------------------------------------------


def test_empty_registry_returns_empty_tuple() -> None:
    """registry_assets on an empty default registry returns ()."""
    # _clear_all_registries autouse fixture guarantees clean state.
    result = registry_assets()
    assert result == ()


def test_unknown_named_registry_returns_empty_tuple() -> None:
    """registry_assets on a never-created named partition returns ()."""
    result = registry_assets("does_not_exist")
    assert result == ()


def test_registry_assets_never_raises_on_empty() -> None:
    """registry_assets must not raise under any circumstance on empty input."""
    # Confirm no exception for default partition.
    registry_assets()
    # And for arbitrary name.
    registry_assets("nonexistent_partition_xyz")


# ---------------------------------------------------------------------------
# AC-M3-2: ToolEntry → AssetSpec — name, description, params, _snapshot coupling
# ---------------------------------------------------------------------------


def test_asset_spec_name_reflects_tool_name() -> None:
    """AssetSpec.name must equal the registered tool name."""
    @cisterna.tool
    def my_tool(x: int) -> int:
        """Simple tool."""
        return x

    specs = registry_assets()
    assert len(specs) == 1
    assert specs[0].name == "my_tool"


def test_asset_spec_description_single_line_docstring() -> None:
    """Single-line docstring is returned as-is (stripped)."""
    @cisterna.tool
    def tool_single_doc(x: int) -> str:
        """Short description."""
        return str(x)

    specs = registry_assets()
    assert len(specs) == 1
    assert specs[0].description == "Short description."


def test_asset_spec_description_multiline_docstring_first_paragraph() -> None:
    """Multiline docstring: only the first paragraph is kept (inspect.cleandoc)."""
    @cisterna.tool
    def tool_multiline(a: str, b: int = 0) -> str:
        """First paragraph of the docstring.

        This second paragraph should be excluded.  It has multiple lines and
        contains extra detail that is not part of the first paragraph.

        Args:
            a: First argument.
            b: Second argument.
        """
        return a * b

    specs = registry_assets()
    assert len(specs) == 1
    # Must be the first paragraph only.
    assert specs[0].description == "First paragraph of the docstring."
    # Must not bleed into the Args section or second paragraph.
    assert "excluded" not in (specs[0].description or "")
    assert "Args" not in (specs[0].description or "")


def test_asset_spec_description_indented_multiline_docstring() -> None:
    """inspect.cleandoc must dedent the docstring before splitting paragraphs."""
    @cisterna.tool
    def tool_indented() -> None:
        """
        Indented first paragraph.

        Indented second paragraph should not appear.
        """

    specs = registry_assets()
    assert len(specs) == 1
    # After cleandoc, leading whitespace is stripped and first para is plain text.
    assert specs[0].description == "Indented first paragraph."


def test_asset_spec_no_docstring_gives_none_description() -> None:
    """A tool without a docstring produces description=None."""
    @cisterna.tool
    def tool_no_doc(x: int) -> int:
        return x

    specs = registry_assets()
    assert len(specs) == 1
    assert specs[0].description is None


def test_asset_spec_params_from_signature() -> None:
    """params must be the tuple of parameter names from inspect.signature."""
    @cisterna.tool
    def tool_params(alpha: int, beta: str, gamma: float = 1.0) -> str:
        """Tool with params."""
        return f"{alpha}{beta}{gamma}"

    specs = registry_assets()
    assert len(specs) == 1
    assert specs[0].params == ("alpha", "beta", "gamma")


def test_asset_spec_params_no_params() -> None:
    """A tool with no parameters has params=()."""
    @cisterna.tool
    def tool_no_params() -> None:
        """No params."""

    specs = registry_assets()
    assert len(specs) == 1
    assert specs[0].params == ()


def test_asset_spec_snapshot_coupling() -> None:
    """Exercises the _snapshot coupling: tools registered via @cisterna.tool are
    visible to registry_assets without any extra wiring step."""
    @cisterna.tool
    def snapshot_tool_a(x: int) -> int:
        """Tool A."""
        return x

    @cisterna.tool
    def snapshot_tool_b(y: str) -> str:
        """Tool B."""
        return y

    specs = registry_assets()
    names = {s.name for s in specs}
    assert "snapshot_tool_a" in names
    assert "snapshot_tool_b" in names


def test_asset_spec_source_field_reflects_registry_name() -> None:
    """AssetSpec.source must equal the registry partition name."""
    @cisterna.tool(registry="test_partition")
    def tool_in_partition(x: int) -> int:
        """Tool in a named partition."""
        return x

    specs = registry_assets("test_partition")
    assert len(specs) == 1
    assert specs[0].source == "test_partition"


def test_asset_spec_kind_is_command() -> None:
    """AssetSpec.kind must always be 'command' in M3."""
    @cisterna.tool
    def any_tool() -> None:
        """Any tool."""

    specs = registry_assets()
    assert len(specs) == 1
    assert specs[0].kind == "command"


def test_registry_assets_sorted_by_name() -> None:
    """registry_assets returns specs sorted by name for canonical determinism."""
    @cisterna.tool
    def zebra() -> None:
        """Z tool."""

    @cisterna.tool
    def alpha() -> None:
        """A tool."""

    @cisterna.tool
    def mango() -> None:
        """M tool."""

    specs = registry_assets()
    names = [s.name for s in specs]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# AC-M3-3: signature introspection failure → params=() + WARNING; second tool OK
# ---------------------------------------------------------------------------


def test_signature_failure_emits_warning_and_params_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A tool whose inspect.signature raises yields params=() + WARNING."""
    import inspect as _inspect

    broken_fn_ref: list[object] = []

    @cisterna.tool
    def broken_sig_tool2() -> None:
        """Tool with broken signature (2)."""

    broken_fn_ref.append(broken_sig_tool2)

    _real_sig = _inspect.signature

    def _patched_sig(obj: object, **kwargs: object) -> object:
        if obj is broken_fn_ref[0]:
            raise TypeError("Intentional introspection failure")
        return _real_sig(obj, **kwargs)  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger="cisterna.export"):
        _inspect.signature = _patched_sig  # type: ignore[assignment]
        try:
            specs = registry_assets()
        finally:
            _inspect.signature = _real_sig

    broken_spec = next((s for s in specs if s.name == "broken_sig_tool2"), None)
    assert broken_spec is not None, "broken_sig_tool2 must still appear in output"
    assert broken_spec.params == (), "params must be () on signature failure"
    # WARNING must name the tool.
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("broken_sig_tool2" in str(m) for m in warning_messages), (
        f"Expected WARNING naming 'broken_sig_tool2'; got: {warning_messages}"
    )


def test_second_tool_exports_despite_first_signature_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A second well-formed tool still exports when the first tool's signature raises."""
    import inspect as _insp

    @cisterna.tool
    def good_tool(x: int, y: str) -> str:
        """Good tool with valid signature."""
        return f"{x}{y}"

    @cisterna.tool
    def bad_tool_introspect() -> None:
        """Bad tool whose signature will fail."""

    bad_fn_ref: list[object] = []
    bad_fn_ref.append(bad_tool_introspect)

    original_sig = _insp.signature

    def _patched_sig(obj: object, **kwargs: object) -> object:
        if obj is bad_fn_ref[0]:
            raise ValueError("Synthetic introspection failure")
        return original_sig(obj, **kwargs)  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger="cisterna.export"):
        _insp.signature = _patched_sig  # type: ignore[assignment]
        try:
            specs = registry_assets()
        finally:
            _insp.signature = original_sig

    names = {s.name for s in specs}
    assert "good_tool" in names, "good_tool must export even when bad_tool_introspect fails"
    assert "bad_tool_introspect" in names, "bad_tool_introspect still appears (with params=())"

    good_spec = next(s for s in specs if s.name == "good_tool")
    assert good_spec.params == ("x", "y"), "good_tool params must be correct"

    bad_spec = next(s for s in specs if s.name == "bad_tool_introspect")
    assert bad_spec.params == (), "bad tool params must be () on failure"
