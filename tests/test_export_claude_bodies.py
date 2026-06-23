"""Tests for M3.1a Claude command body emission (AC-M31a-4, AC-M31a-5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisterna.assets.bundle import AssetBundle, BundleMetadata, CommandAsset
from cisterna.assets.manifest import ManifestAssetSource
from cisterna.assets.validate_golden import surface_digest
from cisterna.export._hash import bundle_sha256
from cisterna.export.claude import ClaudeEmitter

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)
_PLUGIN_JSON = ".claude-plugin/plugin.json"
_PROVENANCE = ".claude-plugin/cisterna-provenance.json"


def _bundle(
    *,
    commands: tuple[CommandAsset, ...] = (),
) -> AssetBundle:
    return AssetBundle(
        metadata=BundleMetadata(name="test", version="1.0.0", description=""),
        commands=commands,
    )


def test_default_emitter_matches_names_only_mode() -> None:
    """AC-M31a-4: default ctor output matches names-only emission (M3 parity)."""
    bundle = _bundle(
        commands=(
            CommandAsset(name="alpha", description="A", body="ignored when off"),
            CommandAsset(name="beta", description="B", body="also ignored"),
        ),
    )
    default_files = ClaudeEmitter().emit(bundle)
    explicit_files = ClaudeEmitter(emit_command_bodies=False).emit(bundle)

    assert default_files == explicit_files
    assert not any(path.startswith("commands/") for path in default_files)
    assert json.loads(default_files[_PLUGIN_JSON])["commands"] == ["alpha", "beta"]


def test_emit_command_bodies_writes_md_and_name_strings() -> None:
    """AC-M31a-5: bodies emit commands/<name>.md; plugin.json lists name strings."""
    bundle = _bundle(
        commands=(
            CommandAsset(name="foo", description=None, body="# Foo\n\nBody text.\n"),
            CommandAsset(name="empty", description="No body", body=""),
        ),
    )

    files = ClaudeEmitter(emit_command_bodies=True).emit(bundle)
    manifest = json.loads(files[_PLUGIN_JSON])

    assert manifest["commands"] == ["empty", "foo"]
    assert files["commands/foo.md"] == "# Foo\n\nBody text.\n"
    assert "commands/empty.md" not in files

    non_provenance = {k: v for k, v in files.items() if _PROVENANCE not in k}
    sidecar = json.loads(files[_PROVENANCE])
    assert sidecar["sha256"] == bundle_sha256(non_provenance)


def test_validate_with_command_bodies_golden() -> None:
    """Golden digest passes for manifest_minimal with command bodies enabled."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    digest = surface_digest(report.bundle, "claude", emit_command_bodies=True)
    golden = (
        Path(__file__).parent
        / "golden"
        / "claude"
        / "with_command_bodies"
        / "digest.sha256"
    )
    assert digest == golden.read_text(encoding="utf-8").strip()


def test_export_manifest_writes_fixture_plugin(tmp_path: Path) -> None:
    """export --manifest emits manifest-driven plugin.json."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "export",
                "--manifest",
                str(FIXTURE_MANIFEST),
                "--out",
                str(out_dir),
            ]
        )
    assert exc_info.value.code == 0

    manifest = json.loads(
        (out_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "fixture-plugin"
    assert manifest["commands"] == ["foo"]


def test_export_manifest_emit_command_bodies(tmp_path: Path) -> None:
    """export --manifest --emit-command-bodies writes commands/foo.md."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    from cisterna.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "export",
                "--manifest",
                str(FIXTURE_MANIFEST),
                "--emit-command-bodies",
                "--out",
                str(out_dir),
            ]
        )
    assert exc_info.value.code == 0

    body_path = out_dir / "commands" / "foo.md"
    assert body_path.is_file()
    assert "Manifest command" in body_path.read_text(encoding="utf-8")
