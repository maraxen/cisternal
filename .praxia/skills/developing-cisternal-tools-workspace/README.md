# developing-cisternal-tools eval workspace

Real cisternal/bathos GitHub operations and PyPI publishes are irreversible, so
evals run against a toy sandbox instead: `sandbox-template/` holds two toy
packages (`toy_cisternal`, a stand-in for the real shared library, and
`toy_consumer`, a stand-in for a project like bathos that depends on it) with
a bug seeded into `toy_cisternal`'s `wire()` that exactly mirrors the shape of
the real `maraxen/cisternal#6` bug: the registry-level view is correct, but
the actual transport (`ToyApp`) silently registers tools under the wrong name.

Run `setup_sandbox.sh <target-dir>` to provision a fresh, isolated copy (two
git repos + a local flat-file wheel index standing in for PyPI) for each eval
run. Never point two eval runs at the same sandbox directory.
