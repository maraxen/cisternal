"""SPIKE probe: raw JSON-RPC over stdio against skills_ext_server.py.

Speaks protocol 2026-07-28 by hand (no SDK client), so what it prints is what
any client sees on the wire. Usage: python probe_raw.py <skill-dir> ...
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

VERSION = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "probe", "version": "0"},
    "io.modelcontextprotocol/clientCapabilities": {
        "extensions": {"io.modelcontextprotocol/skills": {}}
    },
}


def main() -> int:
    server = Path(__file__).with_name("skills_ext_server.py")
    proc = subprocess.Popen(
        [sys.executable, str(server), *sys.argv[1:]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdin and proc.stdout
    next_id = 0

    def call(method: str, params: dict | None = None) -> dict:
        nonlocal next_id
        next_id += 1
        msg = {"jsonrpc": "2.0", "id": next_id, "method": method,
               "params": {**(params or {}), "_meta": META}}
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError(f"server closed during {method}")
            reply = json.loads(line)
            if reply.get("id") == next_id:
                return reply

    ok = True
    try:
        disc = call("server/discover")
        print("discover:", json.dumps(disc.get("result", disc), indent=1)[:1500])
        caps = disc.get("result", {}).get("capabilities", {})
        adv = "io.modelcontextprotocol/skills" in (caps.get("extensions") or {})
        print("ADVERTISED:", adv)
        ok &= adv

        lst = call("skills/list")
        print("skills/list:", json.dumps(lst, indent=1)[:2500])
        skills = lst.get("result", {}).get("skills", [])
        ok &= bool(skills)

        for s in skills:
            got = call("skills/get", {"uri": s["uri"]})
            same = got.get("result", {}).get("skill") == s
            print("skills/get", s["uri"], "matches list:", same)
            ok &= same
            for r in s["resources"]:
                rd = call("resources/read", {"uri": r["uri"]})
                c = rd.get("result", {}).get("contents", [{}])[0]
                if "text" in c:
                    data = c["text"].encode("utf-8")
                else:
                    import base64
                    data = base64.b64decode(c.get("blob", ""))
                dig = "sha256:" + hashlib.sha256(data).hexdigest()
                good = dig == r["digest"] and len(data) == r["size"]
                print("  read", r["uri"], c.get("mimeType"), "digest+size ok:", good)
                ok &= good

        bad = call("skills/get", {"uri": "skill://nope/SKILL.md"})
        code = bad.get("error", {}).get("code")
        print("unknown uri error code:", code)
        ok &= code == -32602
    finally:
        proc.kill()
    print("PROBE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
