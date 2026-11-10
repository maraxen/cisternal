"""Tests for canonical tool key normalization (server/tool)."""

from __future__ import annotations

import pytest

from cisternal.usage.transcript import canonical_tool_key


class TestCanonicalToolKey:
    """Test wire normalization, plugin suffix resolution, and bare tool handling."""

    def test_plugin_wire_format(self) -> None:
        assert (
            canonical_tool_key("mcp__plugin_bathos_bathos__run_sql") == "bathos/run_sql"
        )

    def test_standalone_wire_format(self) -> None:
        assert canonical_tool_key("mcp__bathos__run_sql") == "bathos/run_sql"

    def test_ambiguous_plugin_underscores_longest_suffix(self) -> None:
        # gamma_delta is longer than delta; should win longest-suffix match
        assert (
            canonical_tool_key(
                "mcp__plugin_alpha_beta_gamma_delta__exec",
                declared_servers=["gamma_delta", "delta"],
            )
            == "gamma_delta/exec"
        )

    def test_ambiguous_plugin_no_declared_match(self) -> None:
        # If no declared servers match, keeps whole segment as server
        assert (
            canonical_tool_key("mcp__plugin_a_b_c__t", declared_servers=["other"])
            == "a_b_c/t"
        )

    def test_bare_tool_with_single_server_context(self) -> None:
        assert (
            canonical_tool_key("run_sql", declared_servers=["bathos"])
            == "bathos/run_sql"
        )

    def test_bare_tool_without_context_raises(self) -> None:
        with pytest.raises(
            ValueError, match="cannot be resolved without declared server context"
        ):
            canonical_tool_key("run_sql")

    def test_bare_tool_multiple_servers_raises(self) -> None:
        with pytest.raises(ValueError, match="Ambiguous bare tool"):
            canonical_tool_key("run_sql", declared_servers=["bathos", "contemplex"])

    def test_already_canonical_key(self) -> None:
        assert canonical_tool_key("bathos/run_sql") == "bathos/run_sql"
        assert canonical_tool_key("my_server/my_tool") == "my_server/my_tool"

    def test_hyphenated_identifiers(self) -> None:
        assert (
            canonical_tool_key("mcp__plugin_p-1_s-2__tool-3", declared_servers=["s-2"])
            == "s-2/tool-3"
        )

    @pytest.mark.parametrize(
        "bad_name", ["", "   ", "mcp__invalid", "__", "mcp____tool"]
    )
    def test_empty_or_malformed_raw_raises(self, bad_name: str) -> None:
        with pytest.raises(ValueError):
            canonical_tool_key(bad_name)

    @pytest.mark.parametrize(
        ("wire_name", "expected"),
        [
            ("mcp__plugin_praxia_praxia__run_command", "praxia/run_command"),
            ("mcp__plugin_alynxr_alynxr__list_databases", "alynxr/list_databases"),
            (
                "mcp__contemplex_contemplex__brainstorm_start",
                "contemplex_contemplex/brainstorm_start",
            ),
            ("mcp__myxcel_myxcel__submit_job", "myxcel_myxcel/submit_job"),
            ("mcp__plugin_jaxlint_jaxlint__jaxlint_check", "jaxlint/jaxlint_check"),
        ],
    )
    def test_live_names_matrix(self, wire_name: str, expected: str) -> None:
        assert canonical_tool_key(wire_name) == expected
