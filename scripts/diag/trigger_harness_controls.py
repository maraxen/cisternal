#!/usr/bin/env python3
"""Diagnostic script for skill trigger harness.

Tests the measurement pipeline with positive and negative controls.
- Positive: skill description triggers on "zebrafrob", query contains "zebrafrob" (must trigger)
- Negative: same description, query is "What is 2+2?" (must NOT trigger)
- 3 runs each, timeout 90s
- Captures raw diagnostics: exit code, stdout/stderr from a simple `claude -p` call
- Records whether `claude` is on PATH
"""

import argparse
import datetime
import glob
import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

# The harness is Anthropic's skill-creator `scripts/run_eval.py`, loaded from the
# installed (synced) skill rather than vendored -- we are testing THAT code.
_DEFAULT_HARNESS_GLOB = str(
    Path.home() / ".claude/skills/synced/*/skill-creator"
)


def load_harness(harness_dir: Path):
    """Import run_single_query from <harness_dir>/scripts/run_eval.py."""
    sys.path.insert(0, str(harness_dir))
    from scripts.run_eval import run_single_query  # noqa: E402

    return run_single_query


def resolve_harness_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    candidates = sorted(glob.glob(_DEFAULT_HARNESS_GLOB))
    if not candidates:
        raise SystemExit(f"no skill-creator found under {_DEFAULT_HARNESS_GLOB}")
    return Path(candidates[0])


def find_project_root() -> Path:
    """Find the project root by walking up from cwd looking for .claude/."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


def test_raw_claude_diagnostics() -> dict:
    """Run a simple `claude -p "say hi"` with stderr captured.

    Records: exit_code, stdout (first 20 lines), stderr (first 20 lines),
    and whether `claude` is on PATH.
    """
    # Check if claude is on PATH
    which_result = subprocess.run(
        ["which", "claude"],
        capture_output=True,
        text=True,
    )
    claude_on_path = which_result.returncode == 0

    # Run raw claude -p with stderr captured
    try:
        result = subprocess.run(
            [
                "claude",
                "-p", "say hi",
                "--output-format", "stream-json",
                "--verbose",
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=60,
        )
        stdout_lines = result.stdout.split("\n")[:20]
        stderr_lines = result.stderr.split("\n")[:20]
        exit_code = result.returncode
        timeout_exceeded = False
    except subprocess.TimeoutExpired as e:
        logging.warning(f"Raw claude -p command timed out: {e}")
        stdout_lines = []
        stderr_lines = []
        exit_code = -1
        timeout_exceeded = True

    return {
        "claude_on_path": claude_on_path,
        "exit_code": exit_code,
        "timeout_exceeded": timeout_exceeded,
        "stdout_sample": "\n".join(stdout_lines),
        "stderr_sample": "\n".join(stderr_lines),
    }


def run_control_tests(
    run_single_query,
    skill_name: str,
    description: str,
    project_root: Path,
    timeout: int = 90,
    runs_per_control: int = 3,
) -> dict:
    """Run positive and negative control tests.

    Positive: query contains trigger word (zebrafrob)
    Negative: query doesn't trigger (2+2)
    """
    positive_query = "Please handle this zebrafrob for me."
    negative_query = "What is 2+2?"

    logging.info(f"Testing with skill_name={skill_name}, timeout={timeout}s")
    logging.info(f"Description: {description}")

    positive_results = []
    negative_results = []
    exceptions: list[str] = []

    # Run positive control
    logging.info(f"Running positive control ({runs_per_control} runs)...")
    for i in range(runs_per_control):
        try:
            triggered = run_single_query(
                query=positive_query,
                skill_name=skill_name,
                skill_description=description,
                timeout=timeout,
                project_root=str(project_root),
            )
            positive_results.append(triggered)
            logging.info(f"  Run {i+1}: triggered={triggered}")
        except Exception as e:
            logging.error(f"  Run {i+1}: exception={e}")
            positive_results.append(False)
            exceptions.append(repr(e))

    # Run negative control
    logging.info(f"Running negative control ({runs_per_control} runs)...")
    for i in range(runs_per_control):
        try:
            triggered = run_single_query(
                query=negative_query,
                skill_name=skill_name,
                skill_description=description,
                timeout=timeout,
                project_root=str(project_root),
            )
            negative_results.append(triggered)
            logging.info(f"  Run {i+1}: triggered={triggered}")
        except Exception as e:
            logging.error(f"  Run {i+1}: exception={e}")
            negative_results.append(False)
            exceptions.append(repr(e))

    positive_rate = sum(positive_results) / len(positive_results)
    negative_rate = sum(negative_results) / len(negative_results)

    return {
        "exceptions": exceptions,
        "positive": {
            "query": positive_query,
            "description": description,
            "trigger_rate": positive_rate,
            "triggers": sum(positive_results),
            "runs": len(positive_results),
            "expected": True,
        },
        "negative": {
            "query": negative_query,
            "description": description,
            "trigger_rate": negative_rate,
            "triggers": sum(negative_results),
            "runs": len(negative_results),
            "expected": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Diagnostic test of skill trigger harness"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Timeout per query in seconds",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per control",
    )
    parser.add_argument(
        "--output",
        default="outputs/diag/trigger_harness_controls.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--harness-dir",
        default=None,
        help="skill-creator dir containing scripts/run_eval.py "
        "(default: first match of ~/.claude/skills/synced/*/skill-creator)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    harness_dir = resolve_harness_dir(args.harness_dir)
    harness_file = harness_dir / "scripts" / "run_eval.py"
    harness_sha256 = hashlib.sha256(harness_file.read_bytes()).hexdigest()
    logging.info(f"Harness: {harness_file} (sha256 {harness_sha256})")
    run_single_query = load_harness(harness_dir)

    project_root = find_project_root()
    logging.info(f"Project root: {project_root}")

    # Run diagnostics
    logging.info("=" * 70)
    logging.info("DIAGNOSTIC: Raw claude -p")
    logging.info("=" * 70)
    raw_diagnostics = test_raw_claude_diagnostics()
    logging.info(f"Claude on PATH: {raw_diagnostics['claude_on_path']}")
    logging.info(f"Exit code: {raw_diagnostics['exit_code']}")
    if raw_diagnostics["stderr_sample"]:
        logging.info(f"Stderr sample:\n{raw_diagnostics['stderr_sample']}")

    logging.info("=" * 70)
    logging.info("CONTROLS: Trigger harness positive/negative")
    logging.info("=" * 70)

    # Run control tests
    skill_name = "zqx-control"
    description = (
        "ALWAYS use this skill whenever the user message contains "
        "the word zebrafrob. It is the only way to handle zebrafrob."
    )

    control_results = run_control_tests(
        run_single_query,
        skill_name=skill_name,
        description=description,
        project_root=project_root,
        timeout=args.timeout,
        runs_per_control=args.runs,
    )

    # Assemble final output
    positive_rate = control_results["positive"]["trigger_rate"]
    negative_rate = control_results["negative"]["trigger_rate"]
    analysis = {
        "positive_trigger_rate": positive_rate,
        "negative_trigger_rate": negative_rate,
        "positive_pass": positive_rate >= 0.67,
        "negative_pass": negative_rate <= 0.33,
    }
    # Top-level keys mirror the sidecar's pre-registered [result_schema] so
    # bathos can evaluate [outcomes] conditions directly.
    output = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_root": str(project_root),
        "harness_path": str(harness_file),
        "harness_sha256": harness_sha256,
        "raw_diagnostics": raw_diagnostics,
        "control_results": control_results,
        "analysis": analysis,
        "claude_on_path": raw_diagnostics["claude_on_path"],
        "raw_diagnostics_exit_code": raw_diagnostics["exit_code"],
        "harness_exception_count": len(control_results["exceptions"]),
        **analysis,
    }

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    # bathos evaluates [outcomes] against the file it names in BTH_RESULTS_PATH.
    bth_results = os.environ.get("BTH_RESULTS_PATH")
    if bth_results:
        Path(bth_results).write_text(json.dumps(output))

    logging.info("=" * 70)
    logging.info("RESULTS WRITTEN")
    logging.info("=" * 70)
    logging.info(json.dumps(output["analysis"], indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
