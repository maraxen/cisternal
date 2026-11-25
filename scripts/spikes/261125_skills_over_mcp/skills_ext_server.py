"""SPIKE (throwaway, task 261125_skills-over-mcp-spike): serve skills over MCP.

A FastMCP `ServerExtension` that implements the SEP-2640 Skills extension
(`io.modelcontextprotocol/skills`): it advertises the capability, answers
`skills/list` and `skills/get`, and registers each skill file as a
`skill://<name>/<path>` resource.

Run: python skills_ext_server.py <skill-dir> [<skill-dir> ...]
Each <skill-dir> is one skill folder containing SKILL.md.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP
from fastmcp.resources import FunctionResource
from fastmcp.server.extensions import MethodBinding, ServerExtension
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, PaginatedRequestParams, RequestParams

SKILLS_EXTENSION_ID = "io.modelcontextprotocol/skills"
TTL_MS = 300_000


class SkillsGetParams(RequestParams):
    uri: str


def _frontmatter(skill_md: Path) -> dict[str, Any]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{skill_md}: no YAML frontmatter")
    _, block, _ = text.split("---", 2)
    data = yaml.safe_load(block)
    if not isinstance(data, dict) or not data.get("name") or not data.get("description"):
        raise ValueError(f"{skill_md}: frontmatter needs name and description")
    return data


def _entry(skill_dir: Path) -> dict[str, Any]:
    """One SEP-2640 skill entry: uri, unchanged frontmatter, per-file digests."""
    fm = _frontmatter(skill_dir / "SKILL.md")
    name = fm["name"]
    if skill_dir.name != name:
        raise ValueError(f"{skill_dir}: directory name must equal frontmatter name {name!r}")
    files = sorted(
        p for p in skill_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    resources = []
    for p in files:
        data = p.read_bytes()
        resources.append(
            {
                "uri": f"skill://{name}/{p.relative_to(skill_dir).as_posix()}",
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    # SKILL.md first, as in the spec example.
    resources.sort(key=lambda r: (not r["uri"].endswith("/SKILL.md"), r["uri"]))
    return {"uri": f"skill://{name}/SKILL.md", "frontmatter": fm, "resources": resources}


class SkillsExtension(ServerExtension):
    identifier = SKILLS_EXTENSION_ID

    def __init__(self, skill_dirs: list[Path]) -> None:
        self._dirs = {d.name: d for d in skill_dirs}

    def settings(self) -> dict[str, Any]:
        return {}  # no directoryRead

    def methods(self) -> list[MethodBinding]:
        return [
            MethodBinding("skills/list", PaginatedRequestParams, self._list),
            MethodBinding("skills/get", SkillsGetParams, self._get),
        ]

    async def _list(self, ctx: Any, params: Any) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "skills": [_entry(d) for d in self._dirs.values()],
            "ttlMs": TTL_MS,
            "cacheScope": "public",
        }

    async def _get(self, ctx: Any, params: SkillsGetParams) -> dict[str, Any]:
        for d in self._dirs.values():
            entry = _entry(d)
            if entry["uri"] == params.uri:
                return {
                    "resultType": "complete",
                    "skill": entry,
                    "ttlMs": TTL_MS,
                    "cacheScope": "public",
                }
        raise MCPError(INVALID_PARAMS, f"unknown skill uri: {params.uri}")


def build(skill_dirs: list[Path]) -> FastMCP:
    mcp = FastMCP("skillspike")
    for d in skill_dirs:
        fm = _frontmatter(d / "SKILL.md")
        for res in _entry(d)["resources"]:
            path = d / res["uri"].removeprefix(f"skill://{fm['name']}/")
            is_main = path.name == "SKILL.md"
            is_text = path.suffix in {".md", ".py", ".txt", ".toml", ".json", ".yaml", ".sh"}
            mcp.add_resource(
                FunctionResource(
                    uri=res["uri"],
                    name=fm["name"] if is_main else f"{fm['name']}/{path.name}",
                    description=fm["description"] if is_main else None,
                    mime_type="text/markdown" if path.suffix == ".md" else (
                        "text/plain" if is_text else "application/octet-stream"
                    ),
                    fn=(lambda p=path, t=is_text: p.read_text("utf-8") if t else p.read_bytes()),
                )
            )
    mcp.add_extension(SkillsExtension(skill_dirs))

    @mcp.tool
    def ping() -> str:
        """Liveness check for the spike server."""
        return "pong"

    return mcp


if __name__ == "__main__":
    dirs = [Path(a).resolve() for a in sys.argv[1:]]
    if not dirs:
        sys.exit("usage: skills_ext_server.py <skill-dir> [<skill-dir> ...]")
    build(dirs).run()
