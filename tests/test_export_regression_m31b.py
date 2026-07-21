"""M13: Claude surface intentionally diverges from frozen M3.1b baseline.

Historical context: M3.1b deliberately froze the Claude surface's output
(AC-M31b-5) while cursor/copilot/antigravity were upgraded to the real
per-file asset layout (agents/, skills/, hooks/, .mcp.json). That freeze
was intentional at the time — Claude's real plugin manifest schema hadn't
been validated yet.

M13 lifts the freeze: per the fetched Claude Code plugin docs
(code.claude.com/docs/en/plugins), the real plugin.json schema is just
name/description/version/author/homepage/repository/license — no
``commands``/``mcpServers`` keys. Those concepts now live in
``agents/<name>.md``, ``skills/<name>/SKILL.md``, ``hooks/hooks.json``, and
a root ``.mcp.json``, matching the other three surfaces. This is a known,
intentional breaking change to Claude's default export output, not a
regression. The golden digests for ``claude`` were regenerated alongside
this change (see ``tests/golden/*/claude/**/digest.sha256``).

The one invariant from the M3.1b era that still holds and is worth
guarding here: ``ClaudeEmitter()`` (the default constructor) still matches
``ClaudeEmitter(emit_command_bodies=False)`` — that invariant is orthogonal
to the plugin-format change and should remain true.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cisterna.assets.manifest import ManifestAssetSource
from cisterna.assets.validate_golden import golden_digest_path, surface_digest
from cisterna.export.claude import ClaudeEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_claude_emitter_default_unchanged_vs_explicit_false() -> None:
    """ClaudeEmitter() matches emit_command_bodies=False (invariant unrelated to M13)."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    default = ClaudeEmitter().emit(bundle)
    explicit = ClaudeEmitter(emit_command_bodies=False).emit(bundle)
    assert default == explicit


def test_claude_golden_names_only_reflects_m13_real_plugin_format() -> None:
    """validate golden claude/names_only digest matches the post-M13 real plugin shape."""
    bundle = ManifestAssetSource(FIXTURE_MANIFEST).load().bundle
    digest = surface_digest(bundle, "claude")
    golden = golden_digest_path("claude", "names_only")
    assert digest == golden.read_text(encoding="utf-8").strip()


def test_validate_cli_claude_golden(tmp_path: Path) -> None:
    """CLI validate --surface claude still exits 0 for manifest_minimal."""
    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(FIXTURE_MANIFEST),
                "--surface",
                "claude",
            ]
        )
    assert exc_info.value.code == 0
