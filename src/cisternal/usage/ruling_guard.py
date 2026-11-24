"""PreToolUse guard: agents must never write the reserved ``cisternal_rulings`` collection.

Owners rule on a claude.ai Artifact page; agents only read the rulings through the
``ArtifactData`` tool. This guard is the attestation boundary that keeps agent
writes out. Stdlib only: it runs on every hook call and must stay inside the
cold-start budget.

Fail closed: a write whose target collection(s) cannot be determined is denied.
"""

from __future__ import annotations

import re
from typing import Any

RULINGS_COLLECTION = "cisternal_rulings"
ARTIFACT_DATA_TOOL = "ArtifactData"

# Actions that never mutate a collection. Anything else (including a missing or
# non-string action) is treated as a write and checked.
_READ_ACTIONS = frozenset({"get", "list", "query", "profiles"})


def _is_reserved(collection: str) -> bool:
    return collection == RULINGS_COLLECTION or collection.startswith(
        RULINGS_COLLECTION + "/"
    )


def _denied(detail: str) -> str:
    return (
        f"ArtifactData write to the reserved collection {RULINGS_COLLECTION} is denied: "
        f"{detail}. Rulings are written only by the owner, never by an agent."
    )


def _could_not_check(detail: str) -> str:
    return (
        "ArtifactData write could not be checked against the reserved collection "
        f"{RULINGS_COLLECTION} ({detail}), so it is denied."
    )


def ruling_write_denial(tool_name: str, tool_input: Any) -> str | None:
    """Return a deny reason when this tool call would write ``cisternal_rulings``.

    Returns ``None`` when the call may proceed. Tools other than ``ArtifactData``
    are never checked here.
    """
    if tool_name != ARTIFACT_DATA_TOOL:
        return None

    if not isinstance(tool_input, dict):
        return _could_not_check("tool input is not an object")

    action = tool_input.get("action")
    if not isinstance(action, str):
        return _could_not_check("action is missing or not a string")
    if action in _READ_ACTIONS:
        return None

    if action == "batch":
        writes = tool_input.get("writes")
        if not isinstance(writes, list):
            return _could_not_check("batch writes is missing or not a list")
        for index, entry in enumerate(writes):
            if not isinstance(entry, dict):
                return _could_not_check(f"batch writes[{index}] is not an object")
            collection = entry.get("collection")
            if not isinstance(collection, str):
                return _could_not_check(
                    f"batch writes[{index}] has no string collection"
                )
            if _is_reserved(collection):
                return _denied(f"batch writes[{index}] targets {collection!r}")
        return None

    # Single-document writes, and any action not known to be a read.
    collection = tool_input.get("collection")
    if not isinstance(collection, str):
        return _could_not_check(f"{action} has no string collection")
    if _is_reserved(collection):
        return _denied(f"{action} targets {collection!r}")
    return None


# ---------------------------------------------------------------------------
# Bash: owner-only `cisternal shadow import-labels --confirm-owner`
# ---------------------------------------------------------------------------

OWNER_CONFIRM_FLAG = "--confirm-owner"
_OWNER_DENIAL_REASON = (
    "Bash `cisternal shadow import-labels --confirm-owner` is owner-only and denied "
    "for agents. The owner runs this line as a `!` command, which bypasses hooks."
)
_OWNER_CHECK_FAILED_REASON = (
    "Bash command could not be checked for `cisternal shadow import-labels "
    "--confirm-owner` ({detail}), so it is denied."
)
# Quoting, grouping and escaping characters are blanked out so that a command
# hidden inside `sh -c '...'` or `$(...)` still tokenizes as its own command.
_BLANKED = re.compile(r"[\"'`()\\{}]")
_SEPARATORS = re.compile(r"&&|\|\||[;&|\n]")


def _is_cisternal_binary(token: str) -> bool:
    """True for `cisternal`, a path ending in `/cisternal`, or `cisternal.exe`."""
    base = token.rsplit("/", 1)[-1]
    return base in ("cisternal", "cisternal.exe")


def _segment_runs_owner_import(tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if token != "import-labels" or index < 2:
            continue
        if tokens[index - 1] != "shadow" or not _is_cisternal_binary(tokens[index - 2]):
            continue
        if any(t == OWNER_CONFIRM_FLAG or t.startswith(OWNER_CONFIRM_FLAG + "=") for t in tokens[index + 1 :]):
            return True
    return False


def owner_import_denial(tool_name: str, tool_input: Any) -> str | None:
    """Return a deny reason when a Bash call runs `shadow import-labels --confirm-owner`.

    Matches the plain binary, `uv run ...`, `python -m cisternal ...` and a path to
    the binary. Fail closed: a Bash call whose command cannot be read is denied.
    Every other Bash command, and every other tool, is unaffected.
    """
    if tool_name != "Bash":
        return None
    if not isinstance(tool_input, dict):
        return _OWNER_CHECK_FAILED_REASON.format(detail="tool input is not an object")
    command = tool_input.get("command")
    if not isinstance(command, str):
        return _OWNER_CHECK_FAILED_REASON.format(detail="command is missing or not a string")
    if OWNER_CONFIRM_FLAG not in command:
        return None
    for segment in _SEPARATORS.split(_BLANKED.sub(" ", command)):
        if _segment_runs_owner_import(segment.split()):
            return _OWNER_DENIAL_REASON
    return None


def guard_denial(tool_name: str, tool_input: Any) -> str | None:
    """First deny reason from every ruling guard, or ``None`` when the call may proceed."""
    return ruling_write_denial(tool_name, tool_input) or owner_import_denial(
        tool_name, tool_input
    )
