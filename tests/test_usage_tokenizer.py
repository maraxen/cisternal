"""Tests for compound CLI command splitting and tokenization."""

from __future__ import annotations

import pytest

from cisternal.usage.transcript import (
    VerbSpec,
    VerbTable,
    parse_cli_command,
    parse_cli_commands,
)

FIXTURE_VERBS: VerbTable = {
    "bth": VerbSpec(
        binary="bth",
        subcommands={"sql": "bathos/run_sql", "show": "bathos/show_run"},
        tool_family="bathos",
        global_flags_with_value=("--db", "--config", "-c"),
        global_flags=("--verbose", "-v", "--flag"),
        exclude=("run",),
    ),
    "praxia": VerbSpec(
        binary="praxia",
        subcommands={"search": "praxia/search", "status": "praxia/status"},
        tool_family="praxia",
        global_flags_with_value=("--profile",),
        global_flags=("--debug",),
        exclude=(),
    ),
}


class TestUsageTokenizer:
    """Test compound command splitting, wrapper stripping, flag handling, and fail-open."""

    def test_simple_cli_command(self) -> None:
        assert parse_cli_commands("bth sql", FIXTURE_VERBS) == [("bth", "sql")]

    @pytest.mark.parametrize(
        "cmd",
        [
            "rtk bth sql",
            "just bth sql",
            "sudo bth sql",
            "time bth sql",
            "nice bth sql",
            "nice -n 10 bth sql",
            "nice -15 bth sql",
            "nohup bth sql",
            "command bth sql",
            "builtin bth sql",
            "timeout 10s bth sql",
            "timeout -s 9 5m bth sql",
        ],
    )
    def test_prefix_stripping(self, cmd: str) -> None:
        assert parse_cli_commands(cmd, FIXTURE_VERBS) == [("bth", "sql")]

    @pytest.mark.parametrize(
        "cmd",
        [
            "env VAR=1 bth sql",
            "env -i A=1 B=2 bth sql",
            "env -u OLD_VAR X=val bth sql",
            "X=1 bth sql",
            "FOO=bar BAZ=qux bth sql",
        ],
    )
    def test_env_var_prefixes(self, cmd: str) -> None:
        assert parse_cli_commands(cmd, FIXTURE_VERBS) == [("bth", "sql")]

    @pytest.mark.parametrize(
        "cmd",
        [
            "/usr/bin/bth sql",
            "./bth sql",
            "../../bin/bth sql",
            "/opt/tools/praxia search",
        ],
    )
    def test_binary_path_stripping(self, cmd: str) -> None:
        res = parse_cli_commands(cmd, FIXTURE_VERBS)
        assert len(res) == 1
        assert res[0][1] in ("sql", "search")

    def test_valueless_global_flag(self) -> None:
        assert parse_cli_commands("bth --flag sql", FIXTURE_VERBS) == [("bth", "sql")]
        assert parse_cli_commands("bth -v sql", FIXTURE_VERBS) == [("bth", "sql")]
        assert parse_cli_commands("praxia --debug search", FIXTURE_VERBS) == [
            ("praxia", "search")
        ]

    def test_value_taking_global_flag(self) -> None:
        assert parse_cli_commands("bth --db test.db sql", FIXTURE_VERBS) == [
            ("bth", "sql")
        ]
        assert parse_cli_commands("bth -c mycfg.toml sql", FIXTURE_VERBS) == [
            ("bth", "sql")
        ]
        assert parse_cli_commands("praxia --profile prod search", FIXTURE_VERBS) == [
            ("praxia", "search")
        ]

    def test_flag_equals_value_syntax(self) -> None:
        """Finding A3: handle --flag=value syntax in global_flags_with_value."""
        assert parse_cli_commands("bth --db=test.db sql", FIXTURE_VERBS) == [
            ("bth", "sql")
        ]
        assert parse_cli_commands("bth --config=/path/to/conf.toml sql", FIXTURE_VERBS) == [
            ("bth", "sql")
        ]
        assert parse_cli_commands("praxia --profile=prod search", FIXTURE_VERBS) == [
            ("praxia", "search")
        ]
        # Unknown flag with equals fails open
        assert parse_cli_commands("bth --unknown=value sql", FIXTURE_VERBS) == []

    def test_sudo_with_flags_and_user(self) -> None:
        """Finding A2: sudo wrapper consumes user/group flags and environment options."""
        assert parse_cli_commands(
            "env -i VAR=val sudo -u user rtk just bth sql", FIXTURE_VERBS
        ) == [("bth", "sql")]
        assert parse_cli_commands(
            "sudo -u user -g admin -E -i bth sql", FIXTURE_VERBS
        ) == [("bth", "sql")]
        assert parse_cli_commands(
            "sudo --user=alice -s bth show", FIXTURE_VERBS
        ) == [("bth", "show")]
        assert parse_cli_commands(
            "sudo -Eu user bth sql", FIXTURE_VERBS
        ) == [("bth", "sql")]
        assert parse_cli_commands(
            "sudo -- bth sql", FIXTURE_VERBS
        ) == [("bth", "sql")]

    def test_unknown_flag_skips_segment(self) -> None:
        assert parse_cli_commands("bth --unknown sql", FIXTURE_VERBS) == []
        assert parse_cli_commands("bth -x sql", FIXTURE_VERBS) == []

    def test_compound_operators(self) -> None:
        assert parse_cli_commands('cd /tmp && bth sql "SELECT 1"', FIXTURE_VERBS) == [
            ("bth", "sql")
        ]
        assert parse_cli_commands('bth sql "SELECT 1" | head -n 5', FIXTURE_VERBS) == [
            ("bth", "sql")
        ]
        assert parse_cli_commands("echo hi; rtk bth show 42", FIXTURE_VERBS) == [
            ("bth", "show")
        ]
        assert parse_cli_commands(
            'bth run foo && bth sql "SELECT 1"', FIXTURE_VERBS
        ) == [
            ("bth", "run"),
            ("bth", "sql"),
        ]
        assert parse_cli_commands("bth sql || bth show", FIXTURE_VERBS) == [
            ("bth", "sql"),
            ("bth", "show"),
        ]
        assert parse_cli_commands("bth sql\nbth show", FIXTURE_VERBS) == [
            ("bth", "sql"),
            ("bth", "show"),
        ]
        assert parse_cli_commands("sleep 1 & bth sql", FIXTURE_VERBS) == [
            ("bth", "sql")
        ]

    def test_redirection_ampersand_not_split(self) -> None:
        assert parse_cli_commands("bth sql 2>&1 | grep error", FIXTURE_VERBS) == [
            ("bth", "sql")
        ]

    def test_quoted_operators_preserved(self) -> None:
        assert parse_cli_commands(
            "bth sql 'SELECT 1; SELECT 2 && 3'", FIXTURE_VERBS
        ) == [("bth", "sql")]
        assert parse_cli_commands('bth sql "bth && sql"', FIXTURE_VERBS) == [
            ("bth", "sql")
        ]

    def test_command_substitution_skipped(self) -> None:
        assert parse_cli_commands("$(bth sql)", FIXTURE_VERBS) == []
        assert parse_cli_commands("`bth sql`", FIXTURE_VERBS) == []
        assert parse_cli_commands("echo $(bth sql) && bth show", FIXTURE_VERBS) == [
            ("bth", "show")
        ]

    def test_unclosed_quotes_fail_open(self) -> None:
        assert parse_cli_commands('bth sql "unterminated', FIXTURE_VERBS) == []
        assert parse_cli_commands("bth sql 'unterminated", FIXTURE_VERBS) == []

    def test_parse_cli_command_first_match(self) -> None:
        assert parse_cli_command('cd /tmp && bth sql "SELECT 1"', FIXTURE_VERBS) == (
            "bth",
            "sql",
        )
        assert parse_cli_command("echo hi", FIXTURE_VERBS) is None

    @pytest.mark.parametrize("empty_cmd", ["", "   ", "\n\n", ";;; ", "&& ||"])
    def test_empty_and_whitespace_commands(self, empty_cmd: str) -> None:
        assert parse_cli_commands(empty_cmd, FIXTURE_VERBS) == []

    def test_verbs_as_dict(self) -> None:
        dict_verbs = {
            "bth": {
                "subcommands": {"sql": "bathos/run_sql"},
                "global_flags_with_value": ["--db"],
                "global_flags": ["--flag"],
                "exclude": ["run"],
            }
        }
        assert parse_cli_commands("bth --flag sql", dict_verbs) == [("bth", "sql")]
