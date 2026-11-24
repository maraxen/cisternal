"""Tests for the ArtifactData guard that keeps agents from writing cisternal_rulings.

Spec: shadow-ruling-ui Task 4 (ruling R14). Writes to the reserved collection
``cisternal_rulings`` (and anything under ``cisternal_rulings/``) are denied.
Fail closed: a write whose target collection cannot be determined is denied too.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from cisternal.usage.ruling_guard import ruling_write_denial

RULINGS = "cisternal_rulings"


# ---------------------------------------------------------------------------
# ruling_write_denial: pure decision function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["set", "update", "str_replace", "delete"])
@pytest.mark.parametrize("collection", [RULINGS, f"{RULINGS}/sub", f"{RULINGS}/a/b"])
def test_single_write_to_rulings_is_denied(action: str, collection: str) -> None:
    reason = ruling_write_denial(
        "ArtifactData", {"action": action, "collection": collection}
    )
    assert isinstance(reason, str) and reason


@pytest.mark.parametrize("action", ["get", "list", "query", "profiles"])
def test_reads_of_rulings_are_allowed(action: str) -> None:
    assert (
        ruling_write_denial("ArtifactData", {"action": action, "collection": RULINGS})
        is None
    )


@pytest.mark.parametrize("action", ["set", "update", "delete"])
def test_writes_to_other_collections_are_allowed(action: str) -> None:
    assert (
        ruling_write_denial(
            "ArtifactData", {"action": action, "collection": "other"}
        )
        is None
    )


def test_collection_prefix_lookalike_is_not_a_match() -> None:
    # "cisternal_rulings_v2" is a different collection, not a child of ours.
    assert (
        ruling_write_denial(
            "ArtifactData", {"action": "set", "collection": "cisternal_rulings_v2"}
        )
        is None
    )


def test_batch_with_rulings_entry_is_denied() -> None:
    tool_input = {
        "action": "batch",
        "writes": [
            {"op": "set", "collection": "other", "doc_id": "x"},
            {"op": "set", "collection": f"{RULINGS}/sub", "doc_id": "y"},
        ],
    }
    assert ruling_write_denial("ArtifactData", tool_input) is not None


def test_batch_without_rulings_entries_is_allowed() -> None:
    tool_input = {
        "action": "batch",
        "writes": [
            {"op": "set", "collection": "other", "doc_id": "x"},
            {"op": "delete", "collection": "another", "doc_id": "y"},
        ],
    }
    assert ruling_write_denial("ArtifactData", tool_input) is None


def test_empty_batch_is_allowed() -> None:
    assert (
        ruling_write_denial("ArtifactData", {"action": "batch", "writes": []}) is None
    )


@pytest.mark.parametrize(
    "tool_name", ["Bash", "mcp__plugin_praxia_core__search", "ArtifactComments"]
)
def test_other_tools_are_not_checked(tool_name: str) -> None:
    assert (
        ruling_write_denial(tool_name, {"action": "set", "collection": RULINGS})
        is None
    )


# ---------------------------------------------------------------------------
# Fail closed: write whose target cannot be determined is denied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_input", [None, "set", ["set"], 42])
def test_non_dict_tool_input_is_denied(tool_input: Any) -> None:
    assert ruling_write_denial("ArtifactData", tool_input) is not None


def test_set_without_collection_is_denied() -> None:
    assert ruling_write_denial("ArtifactData", {"action": "set"}) is not None


@pytest.mark.parametrize("collection", [None, 123, ["cisternal_rulings"], {}])
def test_set_with_non_string_collection_is_denied(collection: Any) -> None:
    assert (
        ruling_write_denial(
            "ArtifactData", {"action": "update", "collection": collection}
        )
        is not None
    )


def test_batch_without_writes_is_denied() -> None:
    assert ruling_write_denial("ArtifactData", {"action": "batch"}) is not None


@pytest.mark.parametrize("writes", [None, "set", {"collection": "other"}])
def test_batch_with_non_list_writes_is_denied(writes: Any) -> None:
    assert (
        ruling_write_denial("ArtifactData", {"action": "batch", "writes": writes})
        is not None
    )


@pytest.mark.parametrize(
    "entry",
    [
        "cisternal_rulings",
        ["cisternal_rulings"],
        None,
        {"op": "set", "doc_id": "x"},
        {"op": "set", "collection": None, "doc_id": "x"},
        {"op": "set", "collection": 7, "doc_id": "x"},
    ],
)
def test_batch_with_undeterminable_entry_is_denied(entry: Any) -> None:
    # A single bad entry must deny the whole batch, even when other entries are fine.
    tool_input = {
        "action": "batch",
        "writes": [{"op": "set", "collection": "other", "doc_id": "ok"}, entry],
    }
    assert ruling_write_denial("ArtifactData", tool_input) is not None


def test_missing_action_is_denied() -> None:
    assert (
        ruling_write_denial("ArtifactData", {"collection": "other"}) is not None
    )


# ---------------------------------------------------------------------------
# Hook CLI wiring (cisternal.usage.cli_hook.main)
# ---------------------------------------------------------------------------


def _run_hook(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> tuple[int, str]:
    from cisternal.usage.cli_hook import main as cli_hook_main

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    ret = cli_hook_main(["pre-tool-use"])
    return ret, out.getvalue()


def _assert_deny(stdout: str) -> None:
    doc = json.loads(stdout.strip())
    spec = doc["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["permissionDecision"] == "deny"
    assert spec["permissionDecisionReason"]


def test_hook_cli_emits_deny_json(monkeypatch: pytest.MonkeyPatch) -> None:
    ret, out = _run_hook(
        monkeypatch,
        {
            "session_id": "s",
            "tool_name": "ArtifactData",
            "tool_input": {"action": "set", "collection": RULINGS, "doc_id": "r1"},
        },
    )
    assert ret == 0
    _assert_deny(out)


def test_hook_cli_denies_fail_closed_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    ret, out = _run_hook(
        monkeypatch,
        {
            "session_id": "s",
            "tool_name": "ArtifactData",
            "tool_input": {"action": "batch", "writes": ["not-a-dict"]},
        },
    )
    assert ret == 0
    _assert_deny(out)


def test_hook_cli_denies_even_when_usage_handler_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The guard runs outside the fail-open try: a broken usage handler must not
    # let a ruling write through.
    import cisternal.usage.hooks as hooks

    def _boom(payload: dict[str, Any]) -> None:
        raise RuntimeError("usage handler broke")

    monkeypatch.setattr(hooks, "handle_pre_tool_use", _boom)
    ret, out = _run_hook(
        monkeypatch,
        {
            "session_id": "s",
            "tool_name": "ArtifactData",
            "tool_input": {"action": "delete", "collection": RULINGS},
        },
    )
    assert ret == 0
    _assert_deny(out)


def test_hook_cli_allows_ruling_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    import cisternal.usage.hooks as hooks

    monkeypatch.setattr(hooks, "handle_pre_tool_use", lambda payload: None)
    ret, out = _run_hook(
        monkeypatch,
        {
            "session_id": "s",
            "tool_name": "ArtifactData",
            "tool_input": {"action": "get", "collection": RULINGS, "doc_id": "r1"},
        },
    )
    assert ret == 0
    assert "permissionDecision" not in out


def test_plugin_manifest_declares_artifactdata_matcher() -> None:
    plugin = Path(__file__).resolve().parents[1] / "src" / "cisternal" / "agent_plugin.json"
    doc = json.loads(plugin.read_text(encoding="utf-8"))
    specs = doc["bundle"]["hook_specs"]
    assert {
        "content": "",
        "event": "PreToolUse",
        "matcher": "ArtifactData",
        "script": "cisternal-hook pre-tool-use",
        "surfaces": ["claude"],
        "tier": "essential",
    } in specs
