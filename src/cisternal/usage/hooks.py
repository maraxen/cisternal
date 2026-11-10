"""Hook handlers and error classification for Claude Code PreToolUse and PostToolUse (Spec §C5)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any

from cisternal.usage.paths import atomic_append_jsonl, resolve_sessions_dir
from cisternal.usage.registrations import ActiveRegistrations, scan_active_registrations
from cisternal.usage.transcript import canonical_tool_key, parse_cli_commands

_log = logging.getLogger("cisternal.usage.hooks")


def classify_mcp_error(
    canonical_key: str,
    tool_response: Any,
    *,
    is_protocol_error: bool = False,
) -> tuple[bool, str | None, str | None]:
    """Classify tool result into (is_error, error_code, error_message) per server rules.

    Rules:
    - Protocol error: returns True, "PROTOCOL_ERROR", extracted message.
    - Non-protocol error: decode JSON text from tool_response.
      - bathos, xperiri: top-level ok is False.
      - contemplex: top-level ok is False or (bool(error_code) and ok is not True).
      - myxcel: top-level dict where isinstance(error, str) and bool(error) and isinstance(message, str) and ok is not True.
      - default servers: top-level ok is False.
      - Nested data keys (e.g. SQL rows with 'error' column) when top-level ok is True are NOT errors.
    """
    if is_protocol_error:
        msg: str | None = None
        if isinstance(tool_response, dict):
            if "content" in tool_response and isinstance(
                tool_response["content"], list
            ):
                for item in tool_response["content"]:
                    if isinstance(item, dict) and "text" in item:
                        msg = str(item["text"])
                        break
                    elif isinstance(item, str):
                        msg = item
                        break
            elif "text" in tool_response:
                msg = str(tool_response["text"])
            elif "message" in tool_response:
                msg = str(tool_response["message"])
            elif "error" in tool_response:
                msg = str(tool_response["error"])
        elif isinstance(tool_response, str):
            msg = tool_response

        if not msg:
            msg = "Protocol error" if tool_response is None else str(tool_response)
        return True, "PROTOCOL_ERROR", msg

    # Non-protocol: extract JSON text or dict
    text: str | None = None
    resp_obj: dict[str, Any] | None = None

    if isinstance(tool_response, dict):
        if "content" in tool_response and isinstance(tool_response["content"], list):
            for item in tool_response["content"]:
                if isinstance(item, dict) and "text" in item:
                    text = str(item["text"])
                    break
                elif isinstance(item, str):
                    text = item
                    break
        elif "text" in tool_response:
            text = str(tool_response["text"])
        else:
            resp_obj = tool_response
    elif isinstance(tool_response, list):
        for item in tool_response:
            if isinstance(item, dict) and "text" in item:
                text = str(item["text"])
                break
            elif isinstance(item, str):
                text = item
                break
    elif isinstance(tool_response, str):
        text = tool_response

    if resp_obj is None and text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                resp_obj = parsed
        except Exception:
            return False, None, None

    if resp_obj is None:
        return False, None, None

    server = canonical_key.split("/", 1)[0] if "/" in canonical_key else ""

    # Envelope classification rules:
    if server in ("bathos", "xperiri"):
        if resp_obj.get("ok") is False:
            err_code = resp_obj.get("error_code") or resp_obj.get("error") or "error"
            msg = resp_obj.get("error") or resp_obj.get("message") or ""
            return True, str(err_code), str(msg)
        return False, None, None

    if server == "contemplex":
        ok_val = resp_obj.get("ok")
        err_code = resp_obj.get("error_code")
        if ok_val is False or (bool(err_code) and ok_val is not True):
            code = str(err_code or resp_obj.get("error") or "error")
            msg = str(resp_obj.get("message") or resp_obj.get("error") or "")
            return True, code, msg
        return False, None, None

    if server == "myxcel":
        err = resp_obj.get("error")
        msg = resp_obj.get("message")
        ok_val = resp_obj.get("ok")
        if (
            isinstance(err, str)
            and bool(err)
            and isinstance(msg, str)
            and ok_val is not True
        ):
            return True, err, msg
        return False, None, None

    # Default rule for any other server
    if resp_obj.get("ok") is False:
        err_code = resp_obj.get("error_code") or resp_obj.get("error") or "error"
        msg = resp_obj.get("message") or resp_obj.get("error") or ""
        return True, str(err_code), str(msg)

    return False, None, None


def handle_post_tool_use(
    payload: dict[str, Any] | str,
    sessions_dir: Path | None = None,
    *,
    families: dict[str, tuple[str, ...]] | None = None,
    registrations: ActiveRegistrations | None = None,
) -> bool:
    """Process PostToolUse hook payload and record errors to session ledger."""
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return False

        tool_name = str(payload.get("tool_name") or payload.get("tool") or "")
        if not tool_name.startswith("mcp__"):
            return False

        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return False

        s_dir = sessions_dir
        if s_dir is None:
            resolved, _ = resolve_sessions_dir(is_hook=True)
            if resolved is None:
                return False
            s_dir = resolved

        regs = registrations
        if regs is None:
            try:
                regs = scan_active_registrations(sessions_dir=s_dir)
            except Exception:
                regs = None

        declared_servers = regs.servers if regs is not None else ()
        try:
            canonical_key = canonical_tool_key(tool_name, declared_servers=declared_servers)
        except Exception:
            return False

        tool_response = payload.get("tool_response") or payload.get("tool_result")

        is_proto_error = bool(
            payload.get("is_error")
            or payload.get("isError")
            or payload.get("hook_event_name") in ("PostToolUseFailure",)
            or (
                isinstance(tool_response, dict)
                and (
                    tool_response.get("is_error")
                    or tool_response.get("isError")
                )
            )
        )

        is_err, err_code, err_msg = classify_mcp_error(
            canonical_key, tool_response, is_protocol_error=is_proto_error
        )
        if not is_err:
            return False

        fam_map = families
        if fam_map is None:
            fam_map = regs.families if regs is not None else {}

        tool_family: str | None = None
        if fam_map:
            for fam_name, members in fam_map.items():
                if canonical_key in members:
                    tool_family = fam_name
                    break

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "tool": canonical_key,
            "family": tool_family,
            "error_code": str(err_code) if err_code is not None else None,
            "message": str(err_msg)[:512] if err_msg else None,
            "source": "post_tool_use",
        }

        ledger_path = s_dir / session_id / "errors.jsonl"
        return atomic_append_jsonl(ledger_path, record)
    except Exception as exc:
        _log.warning("PostToolUse hook error (failing open): %s", exc)
        return False


def is_suppressed(
    ledger_path: Path,
    canonical_key: str,
    tool_family: str | None,
) -> bool:
    """Return True if session ledger contains matching error for tool or family."""
    try:
        if not ledger_path.is_file():
            return False
        content = ledger_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        _log.warning("Failed reading error ledger %s: %s", ledger_path, exc)
        return False

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("tool") == canonical_key:
            return True
        if tool_family and rec.get("family") == tool_family:
            return True
    return False


def _normalize_verb_table(verbs: dict[str, Any]) -> dict[str, Any]:
    """Ensure verb table contains lookups by both manifest key and binary name."""
    norm = dict(verbs)
    for _k, v_val in verbs.items():
        binary = getattr(v_val, "binary", None)
        if not binary and isinstance(v_val, dict):
            binary = v_val.get("binary")
        if binary and isinstance(binary, str) and binary not in norm:
            norm[binary] = v_val
    return norm


def handle_pre_tool_use(
    payload: dict[str, Any] | str,
    sessions_dir: Path | None = None,
    *,
    registrations: ActiveRegistrations | None = None,
) -> dict[str, Any] | None:
    """Process PreToolUse hook payload and return nudge dictionary if applicable."""
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None

        tool_name = str(payload.get("tool_name") or payload.get("tool") or "")
        if tool_name != "Bash":
            return None

        s_dir = sessions_dir
        if s_dir is None:
            resolved, _ = resolve_sessions_dir(is_hook=True)
            if resolved is None:
                return None
            s_dir = resolved

        try:
            if s_dir.exists() and not os.access(s_dir, os.R_OK | os.X_OK):
                return None
        except OSError:
            return None

        regs = registrations
        if regs is None:
            regs = scan_active_registrations(sessions_dir=s_dir)

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = payload.get("toolCall", {}).get("args", {})
        if not isinstance(tool_input, dict):
            return None

        cmd = str(
            tool_input.get("command") or tool_input.get("CommandLine") or ""
        ).strip()
        if not cmd:
            return None

        verb_table = _normalize_verb_table(regs.verbs)
        matches = parse_cli_commands(cmd, verb_table)
        if not matches:
            return None

        session_id = str(payload.get("session_id") or "").strip()
        ledger_path = (
            (s_dir / session_id / "errors.jsonl")
            if session_id
            else Path("/nonexistent")
        )

        for binary, subcommand in matches:
            verb_info = verb_table.get(binary)
            if not verb_info:
                continue

            exclude = getattr(verb_info, "exclude", ())
            if not exclude and isinstance(verb_info, dict):
                exclude = verb_info.get("exclude", ())
            if subcommand in exclude:
                continue

            subcommands = getattr(verb_info, "subcommands", {})
            if not subcommands and isinstance(verb_info, dict):
                subcommands = verb_info.get("subcommands", {})
            canonical_target = subcommands.get(subcommand)
            if not canonical_target or not isinstance(canonical_target, str):
                continue

            tool_family = getattr(verb_info, "tool_family", None)
            if not tool_family and isinstance(verb_info, dict):
                tool_family = verb_info.get("tool_family")

            # Active check: canonical key must be registered
            raw_name = regs.tools.get(canonical_target)
            if not raw_name:
                continue

            # Suppression check: check session error ledger
            if is_suppressed(ledger_path, canonical_target, tool_family):
                continue

            # Nudge triggered on first eligible segment
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": (
                        f"An equivalent MCP tool is available: {raw_name} ({canonical_target})."
                    ),
                }
            }

        return None
    except Exception as exc:
        _log.warning("PreToolUse hook error (failing open): %s", exc)
        return None
