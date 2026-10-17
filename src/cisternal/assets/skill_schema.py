"""Claude Code SKILL.md frontmatter schema, as far as the exporter models it.

Source of truth: https://code.claude.com/docs/en/skills (fetched 2026-10-17)
and the 2.1.302 binary's frontmatter key list. Research note:
``.praxia/docs/research/261017_skill-frontmatter-schema.md``.

Keys are matched with ``-`` and ``_`` treated alike (the docs spell
``when_to_use`` with underscores and ``allowed-tools`` with hyphens).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import yaml

from cisternal.assets.bundle import SkillAsset

#: Per-entry cap on ``description`` + ``when_to_use`` in the skill listing
#: (docs; configurable in Claude Code via ``skillListingMaxDescChars``).
LISTING_CAP_CHARS = 1536

#: SkillAsset attribute -> value kind, for every modelled frontmatter key.
FIELD_KINDS: dict[str, str] = {
    "when_to_use": "str",
    "paths": "list",
    "argument_hint": "str",
    "arguments": "list",
    "disable_model_invocation": "bool",
    "user_invocable": "bool",
    "allowed_tools": "list",
    "disallowed_tools": "list",
    "model": "str",
    "effort": "str",
    "context": "str",
    "agent": "str",
    "shell": "str",
    "license": "str",
    "compatibility": "str",
}

#: Keys the loader reads elsewhere (name/description/triggers) and so never
#: reports as dropped.
_HANDLED = {"name", "description", "triggers"}

#: Documented keys the exporter does not carry yet (tech debt, see research note).
UNMODELLED = {"hooks", "background", "metadata"}

# Zero-width, control, private-use and direction characters, plus < and >
# (the docs forbid all of them in a skill name).
_BAD_NAME_CHARS = re.compile(
    "[<>\x00-\x1f\x7f​-‏‪-‮⁦-⁩-]"
)


def norm_key(key: str) -> str:
    return key.replace("-", "_")


def parse_frontmatter(fm: str, warnings: list[str], label: str) -> dict[str, Any]:
    """Parse a frontmatter block with a real YAML parser (fail-open).

    A YAML error makes Claude Code load the skill with *empty* metadata, so it
    is worth a loud warning here; the caller then falls back to manifest values.
    """
    if not fm.strip():
        return {}
    try:
        doc = yaml.safe_load(fm)
    except yaml.YAMLError as exc:
        warnings.append(f"{label}: frontmatter is not valid YAML: {exc}")
        return {}
    if not isinstance(doc, dict):
        warnings.append(f"{label}: frontmatter is not a mapping")
        return {}
    return {norm_key(str(k)): v for k, v in doc.items()}


def _as_list(value: object, key: str, warnings: list[str], label: str) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, str):
        if key == "paths":
            return tuple(p.strip() for p in value.split(",") if p.strip())
        warnings.append(
            f"{label}: {key!r} given as a string is kept as one list item "
            "(Claude Code accepts a space-separated string; use a YAML list)"
        )
        return (value,) if value.strip() else ()
    warnings.append(f"{label}: {key!r} must be a list or string, got {type(value).__name__}")
    return ()


def skill_fields(
    sources: tuple[Mapping[str, Any], ...], warnings: list[str], label: str
) -> dict[str, Any]:
    """Merge modelled frontmatter keys from ``sources`` (earlier wins).

    Each source maps normalised keys to raw values (manifest entry first,
    then the SKILL.md frontmatter). Returns kwargs for ``SkillAsset``.
    """
    out: dict[str, Any] = {}
    for attr, kind in FIELD_KINDS.items():
        for src in sources:
            if attr not in src or src[attr] is None:
                continue
            value = src[attr]
            if kind == "list":
                out[attr] = _as_list(value, attr, warnings, label)
            elif kind == "bool":
                out[attr] = bool(value)
            else:
                out[attr] = str(value)
            break
    return out


def dropped_keys(fm_keys: Mapping[str, Any]) -> list[str]:
    """Source frontmatter keys the export cannot carry (unknown or unmodelled)."""
    known = set(FIELD_KINDS) | _HANDLED
    return sorted(k for k in fm_keys if k not in known)


def check_skill(skill: SkillAsset) -> list[str]:
    """Warnings for the documented limits a skill breaks."""
    out: list[str] = []
    if _BAD_NAME_CHARS.search(skill.name):
        out.append(
            f"skill {skill.name!r}: name contains a forbidden character "
            "(<, >, or a zero-width/control/private-use/direction character)"
        )
    if skill.listing_chars > LISTING_CAP_CHARS:
        out.append(
            f"skill {skill.name!r}: description + when_to_use is {skill.listing_chars} chars, "
            f"over the {LISTING_CAP_CHARS}-char listing cap (the excess is truncated)"
        )
    return out
