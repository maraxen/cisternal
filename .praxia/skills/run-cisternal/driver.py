"""Driver script for the run-cisternal skill.

Exercises the two agent-facing surfaces of cisternal end to end:

  1. Library API  — init(), @tool, wire() against a real FastMCP server,
     emit_event/span, status().
  2. CLI           — `cisternal telemetry doctor` and the assets
     export/inspect/validate trio, run as real subprocesses.

Run with: uv run python .praxia/skills/run-cisternal/driver.py [--out DIR]

Exits non-zero if any stage fails. Prints one PASS/FAIL line per stage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False, **kwargs
    )


def stage_library_api() -> None:
    """Drive cisternal.init/tool/wire/emit_event/span/status in-process."""
    import fastmcp

    import cisternal
    from cisternal import wire  # direct import: cisternal.wire is a lazy __getattr__ re-export
    from cisternal.registration.registry import clear_registry

    with tempfile.TemporaryDirectory() as tmp:
        cisternal.init(log_dir=tmp)

        clear_registry(name="default")

        @cisternal.tool
        def double(x: int) -> int:
            return x * 2

        server = fastmcp.FastMCP("run-cisternal-smoke")
        registry = wire(server, expected=["double"])  # ty: ignore[call-non-callable]
        assert "double" in registry.mcp_tools, registry.mcp_tools

        async def _list_tools() -> None:
            tools = await server.list_tools()
            names = {t.name for t in tools}
            assert "double" in names, names

        asyncio.run(_list_tools())

        with cisternal.span("smoke.op", request_id="driver"):
            pass
        cisternal.emit_event("smoke.custom_event", tool="driver")

        st = cisternal.status()
        assert st is not None

        clear_registry(name="default")

    print("PASS: library API (init/tool/wire/list_tools/span/emit_event/status)")


def stage_cli_doctor() -> None:
    """Drive `cisternal telemetry doctor --json` and parse its report."""
    proc = _run(["uv", "run", "cisternal", "telemetry", "doctor", "--json"])
    report = json.loads(proc.stdout)
    assert report["schema_version"] == 1, report
    assert "checks" in report and len(report["checks"]) > 0, report
    print(f"PASS: cli telemetry doctor (exit={proc.returncode}, "
          f"pass={report['summary']['pass']} warn={report['summary']['warn']} "
          f"fail={report['summary']['fail']})")


def stage_cli_assets(out_dir: Path) -> None:
    """Drive `cisternal assets export/inspect/validate` against the repo's own manifest."""
    manifest = REPO_ROOT / ".praxia" / "manifest.toml"

    inspect = _run(
        ["uv", "run", "cisternal", "assets", "inspect", "--manifest", str(manifest)]
    )
    assert inspect.returncode == 0, inspect.stderr
    payload = json.loads(inspect.stdout)
    skill_names = {s["name"] for s in payload["bundle"]["skills"]}
    assert "run-cisternal" in skill_names, (
        f"run-cisternal skill missing from inspect output: {skill_names}"
    )
    print(f"PASS: cli assets inspect (skills={sorted(skill_names)})")

    export = _run(
        ["uv", "run", "cisternal", "assets", "export",
         "--manifest", str(manifest), "--surface", "claude", "--out", str(out_dir)]
    )
    assert export.returncode == 0, export.stderr
    written = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file())
    assert "skills/run-cisternal/SKILL.md" in written, written
    print(f"PASS: cli assets export -> {out_dir} ({len(written)} files, "
          f"run-cisternal SKILL.md present)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None,
                         help="Export output dir (default: a temp dir)")
    args = parser.parse_args()

    stages = []
    try:
        stage_library_api()
        stages.append(True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: library API: {exc}")
        stages.append(False)

    try:
        stage_cli_doctor()
        stages.append(True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cli telemetry doctor: {exc}")
        stages.append(False)

    try:
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            stage_cli_assets(args.out)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                stage_cli_assets(Path(tmp))
        stages.append(True)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cli assets export/inspect: {exc}")
        stages.append(False)

    ok = all(stages)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
