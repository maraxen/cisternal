"""``skillmod``: migrate a plugin's shipped skills to the valid SKILL.md schema.

Today it does one thing: fold the legacy ``triggers`` list into ``when_to_use``.
Claude Code ignores a ``triggers`` key, so the phrases only influence skill
selection once they sit in ``when_to_use`` (appended to ``description`` in the
skill listing). For every ``[[plugin.skills]]`` entry of a manifest it:

* writes ``when_to_use`` into the skill's SKILL.md frontmatter (existing text
  first, then ``Triggers: a, b, c.``);
* removes ``triggers`` from the SKILL.md frontmatter and from the manifest entry;
* re-parses both files and refuses to write unless every other key is unchanged
  and the exported ``description`` + ``when_to_use`` text is identical.

Edits are textual, not a YAML/TOML round trip, so comments, quoting and key
order elsewhere in the files survive. Dry run is the default; the caller passes
``apply=True`` to write.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cisternal.assets.manifest import ManifestAssetSource, _split_frontmatter
from cisternal.assets.skill_schema import LISTING_CAP_CHARS, norm_key


@dataclass(slots=True)
class SkillChange:
    skill: str
    status: str = "unchanged"  # unchanged | migrate | skipped | failed
    triggers: tuple[str, ...] = ()
    when_to_use: str = ""
    listing_chars: int = 0
    notes: list[str] = field(default_factory=list)


def _entry_end(lines: list[str], start: int) -> int:
    """Index after the YAML entry that begins at ``lines[start]``."""
    i = start + 1
    while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t-"):
        # A blank line only continues the entry if more continuation follows.
        if not lines[i].strip() and not (i + 1 < len(lines) and lines[i + 1][:1] in " \t"):
            break
        i += 1
    return i


def _find_key(lines: list[str], key: str) -> int | None:
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            return i
    return None


def _rewrite_frontmatter(fm: str, folded: str) -> str:
    """Drop ``triggers`` and set ``when_to_use: folded`` in a frontmatter block."""
    lines = fm.strip("\n").splitlines()
    t = _find_key(lines, "triggers")
    if t is not None:
        del lines[t : _entry_end(lines, t)]
    new = yaml.safe_dump(
        {"when_to_use": folded}, allow_unicode=True, width=10**6, default_flow_style=False
    ).rstrip("\n").splitlines()
    w = _find_key(lines, "when_to_use")
    if w is not None:
        lines[w : _entry_end(lines, w)] = new
    else:
        d = _find_key(lines, "description")
        at = _entry_end(lines, d) if d is not None else len(lines)
        lines[at:at] = new
    return "\n".join(lines) + "\n"


def _strip_manifest_triggers(text: str, skill: str) -> str:
    """Remove the ``triggers = [...]`` assignment from skill ``skill``'s entry."""
    lines = text.splitlines(keepends=True)
    in_entry = False
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("[["):
            in_entry = stripped == "[[plugin.skills]]"
            # The entry is the right one only once its ``name`` is seen; keep a
            # buffer-free approach by checking the entry's name up front.
            if in_entry:
                j = i + 1
                name = None
                while j < len(lines) and not lines[j].strip().startswith("["):
                    s = lines[j].strip()
                    if s.startswith("name") and "=" in s:
                        name = s.split("=", 1)[1].strip().strip("\"'")
                    j += 1
                in_entry = name == skill
        elif stripped.startswith("["):
            in_entry = False
        if in_entry and stripped.startswith("triggers") and "=" in stripped:
            depth, quote = 0, ""
            while True:
                for ch in lines[i]:
                    if quote:
                        if ch == quote:
                            quote = ""
                    elif ch in "\"'":
                        quote = ch
                    elif ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                i += 1
                if depth <= 0 or i >= len(lines):
                    break
            continue
        out.append(line)
        i += 1
    return "".join(out)


def _entries(manifest_toml: dict[str, Any]) -> list[dict[str, Any]]:
    entries = manifest_toml.get("plugin", {}).get("skills", [])
    return [e for e in entries if isinstance(e, dict)]


def migrate_manifest(manifest_path: Path, *, apply: bool = False) -> list[SkillChange]:
    """Plan (and with ``apply`` write) the triggers -> when_to_use migration."""
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent.parent
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_toml = tomllib.loads(manifest_text)
    before = {s.name: s for s in ManifestAssetSource(manifest_path).load().bundle.skills}
    changes: list[SkillChange] = []
    new_manifest_text = manifest_text
    pending_writes: list[tuple[Path, str]] = []

    for entry in _entries(manifest_toml):
        name = str(entry.get("name") or "")
        change = SkillChange(skill=name)
        changes.append(change)
        skill = before.get(name)
        if skill is None:
            change.status, change.notes = "skipped", ["not loadable"]
            continue
        change.listing_chars = skill.listing_chars
        if skill.listing_chars > LISTING_CAP_CHARS:
            change.notes.append(f"over the {LISTING_CAP_CHARS}-char listing cap")
        if not skill.triggers:
            continue
        change.triggers = skill.triggers
        if "when_to_use" in {norm_key(str(k)) for k in entry}:
            change.status = "skipped"
            change.notes.append("manifest entry sets when_to_use itself; fold by hand")
            continue

        src = root / str(entry["path"])
        try:
            raw = src.read_text(encoding="utf-8")
        except OSError as exc:
            change.status = "skipped"
            change.notes.append(f"SKILL.md unreadable: {exc}")
            continue
        fm, body_after = _split_frontmatter(raw)
        if not fm.strip():
            change.status = "skipped"
            change.notes.append("SKILL.md has no frontmatter")
            continue
        try:
            old_doc = yaml.safe_load(fm) or {}
        except yaml.YAMLError:
            change.status = "skipped"
            change.notes.append(
                "SKILL.md frontmatter is invalid YAML (Claude Code loads it with empty "
                "metadata); quote the description, then re-run"
            )
            continue
        folded = skill.effective_when_to_use
        new_fm = _rewrite_frontmatter(fm, folded)
        new_raw = f"---\n{new_fm}---\n{body_after}"
        new_mtext = _strip_manifest_triggers(new_manifest_text, name)

        new_doc = yaml.safe_load(new_fm)
        expected = {k: v for k, v in old_doc.items() if k not in ("triggers", "when_to_use")}
        got = {k: v for k, v in new_doc.items() if k not in ("when_to_use",)}
        ok = expected == got and new_doc.get("when_to_use") == folded and "triggers" not in new_doc
        try:
            new_toml = tomllib.loads(new_mtext)
        except tomllib.TOMLDecodeError as exc:
            ok = False
            change.notes.append(f"manifest no longer parses: {exc}")
        else:
            old_entry = {k: v for k, v in entry.items() if k != "triggers"}
            new_entry = next((e for e in _entries(new_toml) if e.get("name") == name), None)
            ok = ok and new_entry == old_entry
        if not ok:
            change.status = "failed"
            change.notes.append("verification failed; nothing written for this skill")
            continue
        change.status, change.when_to_use = "migrate", folded
        new_manifest_text = new_mtext
        pending_writes.append((src, new_raw))

    if apply and pending_writes:
        for path, text in pending_writes:
            path.write_text(text, encoding="utf-8")
        manifest_path.write_text(new_manifest_text, encoding="utf-8")
        after = {s.name: s for s in ManifestAssetSource(manifest_path).load().bundle.skills}
        for change in changes:
            if change.status != "migrate":
                continue
            old, new = before[change.skill], after[change.skill]
            same = (old.description, old.effective_when_to_use) == (
                new.description,
                new.effective_when_to_use,
            )
            if not same or new.triggers:
                change.status = "failed"
                change.notes.append("post-write reload differs from the plan; inspect with git diff")
    return changes
