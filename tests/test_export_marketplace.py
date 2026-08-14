"""Tests for cisternal.export.marketplace (local plugin marketplace publishing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisternal.export.marketplace import (
    content_version,
    default_seed,
    merge_marketplace_entry,
    plugin_output_dir,
)


def test_content_version_deterministic_and_content_sensitive() -> None:
    files_a = {"a.md": "hello"}
    files_b = {"a.md": "hello"}
    files_c = {"a.md": "goodbye"}

    v_a = content_version("1.0.0", files_a)
    v_b = content_version("1.0.0", files_b)
    v_c = content_version("1.0.0", files_c)

    assert v_a == v_b
    assert v_a != v_c
    assert v_a.startswith("1.0.0+")


def test_merge_marketplace_entry_creates_from_seed(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"
    entry = {"name": "demo", "source": "./plugins/demo", "description": "d"}

    path = merge_marketplace_entry(marketplace, entry, seed=default_seed())

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["plugins"] == [entry]
    assert doc["name"] == "cisternal-local"


def test_merge_marketplace_entry_replace_by_name_preserves_others(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"
    first = {"name": "demo", "source": "./plugins/demo", "description": "old"}
    other = {"name": "other-tool", "source": "./plugins/other-tool", "description": "x"}
    merge_marketplace_entry(marketplace, first, seed=default_seed())
    merge_marketplace_entry(marketplace, other, seed=default_seed())

    updated = {"name": "demo", "source": "./plugins/demo", "description": "new"}
    path = merge_marketplace_entry(marketplace, updated, seed=default_seed())

    doc = json.loads(path.read_text(encoding="utf-8"))
    names = sorted(p["name"] for p in doc["plugins"])
    assert names == ["demo", "other-tool"]
    demo_entry = next(p for p in doc["plugins"] if p["name"] == "demo")
    assert demo_entry["description"] == "new"


def test_merge_marketplace_entry_requires_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name"):
        merge_marketplace_entry(tmp_path / "mkt", {"source": "./plugins/x"})


def test_merge_marketplace_entry_bootstraps_readme_once(tmp_path: Path) -> None:
    marketplace = tmp_path / "mkt"
    entry = {"name": "demo", "source": "./plugins/demo", "description": "d"}

    merge_marketplace_entry(marketplace, entry, seed=default_seed(), readme_template="v1")
    assert (marketplace / "README.md").read_text(encoding="utf-8") == "v1"

    merge_marketplace_entry(marketplace, entry, seed=default_seed(), readme_template="v2")
    assert (marketplace / "README.md").read_text(encoding="utf-8") == "v1"


def test_plugin_output_dir_rejects_unsafe_names(tmp_path: Path) -> None:
    assert plugin_output_dir(tmp_path, "demo") == tmp_path / "plugins" / "demo"
    for bad in ("..", ".", "../escape", "a/b"):
        with pytest.raises(ValueError, match="unsafe"):
            plugin_output_dir(tmp_path, bad)
