"""PreToolUse guard: agents must never write the reserved ``cisternal_rulings`` collection.

Owners rule on a claude.ai Artifact page; agents only read the rulings through the
``ArtifactData`` tool. This guard is the attestation boundary that keeps agent
writes out. Stdlib only: it runs on every hook call and must stay inside the
cold-start budget.

Fail closed: a write whose target collection(s) cannot be determined is denied.
"""

from __future__ import annotations

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
