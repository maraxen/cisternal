"""Tests for M3.3d L14 validate-only workflow/pipeline/snippet parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from cisternal.assets.manifest import ManifestAssetSource

FIXTURE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "manifest_minimal" / "manifest.toml"
)


def test_manifest_minimal_unchanged_no_extension_warnings() -> None:
    """AC-M33d-1: manifest_minimal has no L14 warnings."""
    report = ManifestAssetSource(FIXTURE_MANIFEST).load()
    assert not any("workflow" in w or "pipeline" in w or "snippet" in w for w in report.warnings)


def test_workflow_missing_path_warns(tmp_path: Path) -> None:
    """AC-M33d-2: missing workflow path → load warning (validate exit 1)."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.workflows]]
name = "wf"
path = "workflows/missing.toml"
""".strip(),
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert report.bundle.commands == ()
    assert any("workflows" in w and "missing" in w for w in report.warnings)


def test_snippet_invalid_scope_warns(tmp_path: Path) -> None:
    """AC-M33d-3: invalid snippet scope → warning."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    snippets = manifest_dir / "snippets"
    snippets.mkdir()
    (snippets / "s.toml").write_text("", encoding="utf-8")
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.snippets]]
name = "s"
path = "snippets/s.toml"
scope = "invalid"
""".strip(),
        encoding="utf-8",
    )
    report = ManifestAssetSource(manifest_dir / "manifest.toml").load()
    assert any("invalid scope" in w for w in report.warnings)


def test_validate_workflow_warning_exits_one(tmp_path: Path) -> None:
    """AC-M33d-4: validate fails when L14 extension path missing."""
    manifest_dir = tmp_path / "plugin"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.toml").write_text(
        """
[plugin]
name = "p"
version = "1.0.0"
description = ""
requires_praxia = "0.0.0"

[[plugin.pipelines]]
name = "pipe"
path = "pipelines/nope.toml"
""".strip(),
        encoding="utf-8",
    )

    from cisternal.cli import app

    with pytest.raises(SystemExit) as exc_info:
        app(
            [
                "assets",
                "validate",
                "--manifest",
                str(manifest_dir / "manifest.toml"),
            ]
        )
    assert exc_info.value.code == 1
