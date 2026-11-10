"""Lightweight CLI entry point for Claude Code hooks (PreToolUse, PostToolUse).

Bypasses heavy CLI framework loading to satisfy the <= 150 ms cold start budget (Spec §C5).
"""

from __future__ import annotations

import json
import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Execute hook handler based on CLI arguments and standard input."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        return 0

    subcommand = argv[0].strip()

    try:
        raw_in = sys.stdin.read()
        if not raw_in.strip():
            return 0
        payload = json.loads(raw_in)
    except Exception:
        # Fail open on unreadable/invalid input
        return 0

    if not isinstance(payload, dict):
        return 0

    try:
        if subcommand in ("pre-tool-use", "pre_tool_use"):
            from cisternal.usage.hooks import handle_pre_tool_use

            nudge = handle_pre_tool_use(payload)
            if nudge is not None:
                sys.stdout.write(json.dumps(nudge) + "\n")
                sys.stdout.flush()
        elif subcommand in ("post-tool-use", "post_tool_use"):
            from cisternal.usage.hooks import handle_post_tool_use

            handle_post_tool_use(payload)
        elif subcommand in ("post-tool-failure", "post_tool_failure"):
            from cisternal.usage.hooks import handle_post_tool_use

            payload["is_error"] = True
            handle_post_tool_use(payload)
    except Exception:
        # Hook handlers fail open
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
