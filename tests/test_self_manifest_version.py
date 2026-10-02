"""cisternal's own plugin manifest version tracks the package version.

`cisternal assets export --manifest .praxia/manifest.toml` writes the manifest's [plugin].version
into plugin.json (only `plugin install` / `publish-shared` override it from the installed
package). A stale manifest version gives every release the same plugin version string, so
version-keyed plugin caches keep serving an old bundle. Bump both in each release.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_version_equals_package_version() -> None:
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    plugin = tomllib.loads((ROOT / ".praxia" / "manifest.toml").read_text(encoding="utf-8"))["plugin"]["version"]
    assert plugin == package, f".praxia/manifest.toml version {plugin!r} != pyproject {package!r}"


def test_changelog_has_a_section_for_the_current_version() -> None:
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    headings = [line for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
    assert any(h.split()[1] == package for h in headings), f"CHANGELOG.md has no '## {package}' section"
