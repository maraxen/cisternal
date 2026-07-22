#!/usr/bin/env bash
# Provisions a fresh, isolated toy-cisternal / toy-consumer sandbox for one
# eval run. Usage: setup_sandbox.sh <target-dir>
set -euo pipefail

TARGET="${1:?usage: setup_sandbox.sh <target-dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/sandbox-template"

rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$TEMPLATE/toy_cisternal" "$TARGET/toy_cisternal"
cp -r "$TEMPLATE/toy_consumer" "$TARGET/toy_consumer"

# --- toy_cisternal: its own git repo, main branch, initial release tagged ---
cd "$TARGET/toy_cisternal"
git init -q -b main
git add -A
git -c user.email=sandbox@example.com -c user.name=Sandbox commit -q -m "toy-cisternal 0.1.0"
git tag v0.1.0

# Build the initial (buggy) wheel and publish it to a local flat-file index.
uv build -q --out-dir dist >/dev/null 2>&1
mkdir -p "$TARGET/toy_cisternal_index"
cp dist/*.whl "$TARGET/toy_cisternal_index/"

# --- toy_consumer: its own git repo, resolves toy-cisternal from the local index ---
cd "$TARGET/toy_consumer"
git init -q -b main
uv venv -q .venv
uv pip install -q --python .venv/bin/python \
  --find-links "$TARGET/toy_cisternal_index" \
  -e . "pytest>=8"
git add -A
git -c user.email=sandbox@example.com -c user.name=Sandbox commit -q -m "toy-consumer 0.1.0, depends on toy-cisternal 0.1.0"

echo "Sandbox ready at $TARGET"
echo "  toy_cisternal:       $TARGET/toy_cisternal        (git repo, tag v0.1.0)"
echo "  toy_cisternal_index: $TARGET/toy_cisternal_index  (stand-in for PyPI -- flat wheel index)"
echo "  toy_consumer:        $TARGET/toy_consumer          (git repo, venv at .venv/, installed toy-cisternal from the index above)"
