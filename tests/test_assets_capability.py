"""Tests for M3.1a capability resolution (W3)."""

from __future__ import annotations

import pytest

from cisterna.assets.capability import (
    Capability,
    resolve_model_hint,
    resolve_tools,
)


def test_capability_parse_all_fourteen() -> None:
    for cap in Capability:
        assert Capability.parse(cap.value) is cap


def test_resolve_tools_read_search_claude_code() -> None:
    """AC-M31a-3: read+search map to concrete Claude tools (+ Glob when Grep present)."""
    tools = resolve_tools(("read", "search"), "claude_code")
    assert tools == ("Glob", "Grep", "Read")


def test_resolve_tools_invalid_token_raises() -> None:
    with pytest.raises(ValueError, match="banana"):
        resolve_tools(("read", "banana"), "claude_code")


def test_resolve_tools_unbound_capability_raises() -> None:
    with pytest.raises(ValueError, match="delegate"):
        resolve_tools(("delegate",), "claude_code")


def test_resolve_tools_mcp_passthrough() -> None:
    tools = resolve_tools(("mcp__praxia__custom_tool",), "claude_code")
    assert tools == ("mcp__praxia__custom_tool",)


def test_resolve_tools_read_search_antigravity_cli() -> None:
    """AC-M31c-6: read+search map on antigravity_cli surface."""
    tools = resolve_tools(("read", "search"), "antigravity_cli")
    assert tools == ("read_file", "search_file_content")


def test_resolve_model_hint_claude_fast() -> None:
    assert resolve_model_hint("fast", "claude_code") == "haiku"
    assert resolve_model_hint("deep", "claude_code") == "opus"
    assert resolve_model_hint("missing", "claude_code") is None
