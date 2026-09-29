"""Benchmark: cost and eol behaviour of hashing a no-.git tree for manifest verification.

task_id: 260929_sidecar-verify-2060 (praxia debt #2060)

Builds a synthetic tree of N files (default 5000) in a temp dir with NO .git, then:
  1. hashes every file with pure-Python git-blob-sha1 (sha1(b"blob %d\\0" + bytes));
  2. hashes the same files with ONE batched `git hash-object --no-filters --stdin-paths`
     run from a cwd that is not inside any repository;
  3. positive control: (1) and (2) must agree on every file;
  4. negative controls, which MUST detect a difference:
     a. a one-byte edit changes the file's hash;
     b. a CRLF file hashed WITH filters under core.autocrlf=true differs from
        --no-filters, proving the flag is what makes hashing config-independent;
  5. reports wall time for each method (best of --repeats).

Emits one JSON object on stdout and to --out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

log = logging.getLogger("tree_manifest_hash_cost")


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def make_tree(root: Path, n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    paths = []
    for i in range(n):
        rel = f"pkg{i % 40}/sub{i % 7}/mod_{i}.py"
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        size = min(int(rng.lognormvariate(8.5, 1.0)), 400_000)  # median ~5 KB, long tail
        p.write_bytes(rng.randbytes(size))
        paths.append(rel)
    return paths


def py_hashes(root: Path, paths: list[str]) -> dict[str, str]:
    return {rel: blob_sha1((root / rel).read_bytes()) for rel in paths}


def _hermetic_env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    return env


def git_hashes(root: Path, paths: list[str], extra_cfg: list[str] | None = None,
               no_filters: bool = True) -> dict[str, str]:
    cmd = ["git", *(extra_cfg or []), "hash-object"]
    if no_filters:
        cmd.append("--no-filters")
    cmd.append("--stdin-paths")
    out = subprocess.run(cmd, input="\n".join(paths) + "\n", cwd=root, env=_hermetic_env(root),
                         capture_output=True, text=True, check=True).stdout.split()
    return dict(zip(paths, out, strict=True))


def best_of(fn, repeats: int) -> float:
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-files", type=int, default=5000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=260929)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "tree"
        root.mkdir()
        paths = make_tree(root, args.n_files, args.seed)
        total_bytes = sum((root / p).stat().st_size for p in paths)
        in_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
                                 capture_output=True, text=True,
                                 env=_hermetic_env(root)).returncode == 0

        py = py_hashes(root, paths)
        gh = git_hashes(root, paths)
        agree = sum(py[p] == gh[p] for p in paths)

        # Negative control a: a one-byte edit must change the hash.
        victim = root / paths[0]
        orig = victim.read_bytes()
        victim.write_bytes(orig[:-1] + bytes([(orig[-1] + 1) % 256]) if orig else b"x")
        edit_detected = blob_sha1(victim.read_bytes()) != py[paths[0]]
        victim.write_bytes(orig)

        # Negative control b: CRLF with filters under autocrlf=true must differ from --no-filters.
        crlf = root / "crlf.txt"
        crlf.write_bytes(b"line one\r\nline two\r\n")
        raw = git_hashes(root, ["crlf.txt"])["crlf.txt"]
        filtered = git_hashes(root, ["crlf.txt"], extra_cfg=["-c", "core.autocrlf=true"],
                              no_filters=False)["crlf.txt"]
        crlf_filter_differs = raw != filtered
        crlf_raw_matches_python = raw == blob_sha1(crlf.read_bytes())

        t_py = best_of(lambda: py_hashes(root, paths), args.repeats)
        t_git = best_of(lambda: git_hashes(root, paths), args.repeats)

    result = {
        "n_files": args.n_files,
        "total_bytes": total_bytes,
        "tree_inside_git_repo": in_repo,
        "python_vs_git_agree": agree,
        "one_byte_edit_detected": edit_detected,
        "crlf_filtered_differs_from_no_filters": crlf_filter_differs,
        "crlf_no_filters_matches_python": crlf_raw_matches_python,
        "seconds_python_blob_sha1": round(t_py, 4),
        "seconds_git_hash_object_batched": round(t_git, 4),
        "git_version": subprocess.run(["git", "--version"], capture_output=True,
                                      text=True).stdout.strip(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    ok = (agree == args.n_files and edit_detected and crlf_filter_differs
          and crlf_raw_matches_python and not in_repo)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
