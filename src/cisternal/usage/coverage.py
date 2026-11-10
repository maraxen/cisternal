"""Skill invocation coverage, opportunity matching, and precision evaluation (Spec §C3)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from cisternal.assets.bundle import SkillAsset
from cisternal.assets.manifest import ManifestAssetSource, _split_frontmatter
from cisternal.assets.skill_schema import parse_frontmatter
from cisternal.plugin.config import marketplace_root_source
from cisternal.usage.transcript import (
    TranscriptEvent,
    discover_transcript_files,
    stream_transcript_events,
)
from cisternal.usage.usage import WilsonInterval, wilson_confidence_interval


@dataclass(frozen=True, slots=True)
class UnmonitoredSkill:
    """Skill missing distinctive_strings or unmonitored for opportunity tracking."""

    name: str
    path: str
    reason: str = "missing distinctive_strings"


@dataclass(frozen=True, slots=True)
class SituationEvaluationRecord:
    """Evaluation result for a single prompt situation."""

    id: str
    prompt: str
    expected_skills: tuple[str, ...]
    detected_skills: tuple[str, ...]
    tp: int
    fp: int
    fn: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "expected_skills": list(self.expected_skills),
            "detected_skills": list(self.detected_skills),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


@dataclass(frozen=True, slots=True)
class PrecisionRecallReport:
    """Statistical precision/recall evaluation report over situation benchmarks."""

    total_situations: int
    matched_turns: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    precision_ci: WilsonInterval
    recall: float
    recall_ci: WilsonInterval
    threshold: float
    status: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    unmonitored_skills: tuple[UnmonitoredSkill, ...] = ()
    per_skill_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_situations": self.total_situations,
            "matched_turns": self.matched_turns,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "precision_ci": [
                round(self.precision_ci.lower, 4),
                round(self.precision_ci.upper, 4),
            ],
            "precision_ci_formatted": self.precision_ci.format_pct(),
            "recall": round(self.recall, 4),
            "recall_ci": [
                round(self.recall_ci.lower, 4),
                round(self.recall_ci.upper, 4),
            ],
            "recall_ci_formatted": self.recall_ci.format_pct(),
            "threshold": self.threshold,
            "status": self.status,
            "unmonitored_skills": [
                {"name": u.name, "path": u.path, "reason": u.reason}
                for u in self.unmonitored_skills
            ],
            "per_skill_stats": self.per_skill_stats,
        }


@dataclass(frozen=True, slots=True)
class SkillOpportunityStat:
    """Opportunity and invocation counts for a single monitored skill."""

    name: str
    opportunities: int = 0
    invoked: int = 0
    loaded_before_action: int = 0
    missed_opportunities: int = 0
    post_load_tool_calls: int = 0


@dataclass(frozen=True, slots=True)
class SkillOpportunityReport:
    """Report on mined skill opportunities across session transcripts."""

    skills: dict[str, SkillOpportunityStat]
    unmonitored_skills: tuple[UnmonitoredSkill, ...]
    mined_situations: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "skills": {
                name: {
                    "opportunities": stat.opportunities,
                    "invoked": stat.invoked,
                    "loaded_before_action": stat.loaded_before_action,
                    "missed_opportunities": stat.missed_opportunities,
                    "post_load_tool_calls": stat.post_load_tool_calls,
                }
                for name, stat in self.skills.items()
            },
            "unmonitored_skills": [
                {"name": u.name, "path": u.path, "reason": u.reason}
                for u in self.unmonitored_skills
            ],
            "mined_situations_count": len(self.mined_situations),
        }


def load_monitored_skills(
    manifest_paths: Sequence[Path] | None = None,
    marketplace_dir: Path | None = None,
) -> tuple[dict[str, SkillAsset], list[UnmonitoredSkill]]:
    """Discover skills from workspace manifests and installed marketplace plugins.

    Marketplace resolution is strictly read-only via marketplace_root_source.
    Third-party installed skills lacking distinctive_strings are recorded in
    unmonitored_skills.
    """
    monitored_skills: dict[str, SkillAsset] = {}
    unmonitored_skills: list[UnmonitoredSkill] = []

    # 1. Load workspace manifests
    paths = list(manifest_paths) if manifest_paths else [Path(".praxia/manifest.toml")]
    for mpath in paths:
        if not mpath.is_file():
            continue
        try:
            report = ManifestAssetSource(mpath).load()
            for skill in report.bundle.skills:
                if skill.distinctive_strings:
                    monitored_skills[skill.name] = skill
                else:
                    unmonitored_skills.append(
                        UnmonitoredSkill(
                            name=skill.name,
                            path=str(mpath),
                            reason="missing distinctive_strings",
                        )
                    )
        except Exception:
            continue

    # 2. Inspect marketplace plugins (read-only)
    m_root, _ = marketplace_root_source(marketplace_dir)
    if m_root is not None and m_root.is_dir():
        plugins_dir = m_root / "plugins"
        search_dirs = [plugins_dir] if plugins_dir.is_dir() else [m_root]
        for s_dir in search_dirs:
            for plugin_dir in sorted(s_dir.iterdir()):
                if not plugin_dir.is_dir() or plugin_dir.name in {
                    ".claude-plugin",
                    "plugins",
                }:
                    continue

                # Priority 1: .claude-plugin/cisternal-source.json -> source["manifest"]
                source_json = plugin_dir / ".claude-plugin" / "cisternal-source.json"
                handled = False
                if source_json.is_file():
                    try:
                        data = json.loads(source_json.read_text(encoding="utf-8"))
                        rel_manifest = data.get("manifest")
                        if rel_manifest:
                            full_m = plugin_dir / rel_manifest
                            if full_m.is_file():
                                rep = ManifestAssetSource(full_m).load()
                                for sk in rep.bundle.skills:
                                    if sk.distinctive_strings:
                                        monitored_skills[sk.name] = sk
                                    else:
                                        unmonitored_skills.append(
                                            UnmonitoredSkill(
                                                name=sk.name,
                                                path=str(full_m),
                                                reason="missing distinctive_strings",
                                            )
                                        )
                                handled = True
                        # Priority 2: inline skills_meta in cisternal-source.json
                        if not handled and "skills_meta" in data:
                            skills_meta = data["skills_meta"]
                            if isinstance(skills_meta, dict):
                                for s_name, meta in skills_meta.items():
                                    if not isinstance(meta, dict):
                                        continue
                                    covers = _as_string_tuple(
                                        meta.get("covers_families", ())
                                    )
                                    distinctive = _as_string_tuple(
                                        meta.get("distinctive_strings", ())
                                    )
                                    if distinctive:
                                        monitored_skills[s_name] = SkillAsset(
                                            name=s_name,
                                            covers_families=covers,
                                            distinctive_strings=distinctive,
                                        )
                                    else:
                                        unmonitored_skills.append(
                                            UnmonitoredSkill(
                                                name=s_name,
                                                path=str(source_json),
                                                reason="missing distinctive_strings",
                                            )
                                        )
                                handled = True
                    except Exception:
                        pass

                if handled:
                    continue

                # Priority 3: direct frontmatter parse of <plugin_dir>/skills/<skill>/SKILL.md
                skills_dir = plugin_dir / "skills"
                if skills_dir.is_dir():
                    for sdir in sorted(skills_dir.iterdir()):
                        if not sdir.is_dir():
                            continue
                        skill_md = sdir / "SKILL.md"
                        if not skill_md.is_file():
                            continue
                        try:
                            content = skill_md.read_text(encoding="utf-8")
                            fm, body = _split_frontmatter(content)
                            warns: list[str] = []
                            doc = parse_frontmatter(fm, warns, f"skill {sdir.name!r}")
                            distinctive = _as_string_tuple(
                                doc.get("distinctive_strings", ())
                            )
                            covers = _as_string_tuple(doc.get("covers_families", ()))
                            desc = str(doc.get("description", ""))
                            if distinctive:
                                monitored_skills[sdir.name] = SkillAsset(
                                    name=sdir.name,
                                    description=desc,
                                    body=body,
                                    covers_families=covers,
                                    distinctive_strings=distinctive,
                                )
                            else:
                                unmonitored_skills.append(
                                    UnmonitoredSkill(
                                        name=sdir.name,
                                        path=str(skill_md),
                                        reason="missing distinctive_strings",
                                    )
                                )
                        except Exception:
                            continue

    return monitored_skills, unmonitored_skills


def match_distinctive_strings(
    text: str, distinctive_strings: Sequence[str]
) -> list[str]:
    """Whole-token case-insensitive matching for distinctive strings."""
    matched: list[str] = []
    for s in distinctive_strings:
        s_clean = s.strip()
        if not s_clean:
            continue
        # Token boundary pattern supporting hyphenated/underscored words
        pattern = rf"(?<![a-zA-Z0-9_-]){re.escape(s_clean)}(?![a-zA-Z0-9_-])"
        if re.search(pattern, text, re.IGNORECASE):
            matched.append(s_clean)
    return matched


def evaluate_situation_set(
    situations_path: Path,
    skills: Mapping[str, SkillAsset],
    threshold: float = 0.80,
) -> tuple[PrecisionRecallReport, list[SituationEvaluationRecord]]:
    """Evaluate situation benchmark against monitored skills.

    Computes TP, FP, FN, precision, recall, and Wilson 95% confidence intervals.
    Status is INCONCLUSIVE if n < 50 matched turns.
    """
    records: list[SituationEvaluationRecord] = []
    total_situations = 0

    per_skill: dict[str, dict[str, int]] = {
        name: {"tp": 0, "fp": 0, "fn": 0} for name in skills
    }

    if situations_path.is_file():
        with open(situations_path, encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    item = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                total_situations += 1
                sit_id = str(item.get("id") or f"sit_{total_situations:03d}")
                prompt = str(item.get("prompt") or "")
                expected = set(item.get("expected_skills") or [])

                detected: set[str] = set()
                for s_name, skill in skills.items():
                    if match_distinctive_strings(prompt, skill.distinctive_strings):
                        detected.add(s_name)

                tp = len(detected & expected)
                fp = len(detected - expected)
                fn = len(expected - detected)

                for s in detected & expected:
                    if s in per_skill:
                        per_skill[s]["tp"] += 1
                for s in detected - expected:
                    if s in per_skill:
                        per_skill[s]["fp"] += 1
                for s in expected - detected:
                    if s in per_skill:
                        per_skill[s]["fn"] += 1

                records.append(
                    SituationEvaluationRecord(
                        id=sit_id,
                        prompt=prompt,
                        expected_skills=tuple(sorted(expected)),
                        detected_skills=tuple(sorted(detected)),
                        tp=tp,
                        fp=fp,
                        fn=fn,
                    )
                )

    total_tp = sum(r.tp for r in records)
    total_fp = sum(r.fp for r in records)
    total_fn = sum(r.fn for r in records)
    n = total_tp + total_fp

    p_hat = total_tp / n if n > 0 else 0.0
    recall_den = total_tp + total_fn
    recall = total_tp / recall_den if recall_den > 0 else 0.0

    precision_ci = wilson_confidence_interval(total_tp, n)
    recall_ci = wilson_confidence_interval(total_tp, recall_den)

    if n < 50:
        status: Literal["PASS", "FAIL", "INCONCLUSIVE"] = "INCONCLUSIVE"
    elif p_hat >= threshold:
        status = "PASS"
    else:
        status = "FAIL"

    per_skill_stats: dict[str, dict[str, Any]] = {}
    for s_name, counts in per_skill.items():
        s_n = counts["tp"] + counts["fp"]
        s_p = counts["tp"] / s_n if s_n > 0 else 0.0
        per_skill_stats[s_name] = {
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
            "matched_turns": s_n,
            "precision": round(s_p, 4),
            "precision_ci": wilson_confidence_interval(counts["tp"], s_n).format_pct(),
        }

    report = PrecisionRecallReport(
        total_situations=total_situations,
        matched_turns=n,
        true_positives=total_tp,
        false_positives=total_fp,
        false_negatives=total_fn,
        precision=p_hat,
        precision_ci=precision_ci,
        recall=recall,
        recall_ci=recall_ci,
        threshold=threshold,
        status=status,
        per_skill_stats=per_skill_stats,
    )
    return report, records


def _resolve_skill_name(raw: Any, skills: Mapping[str, SkillAsset]) -> str | None:
    """Map a Skill invocation (``<skill>`` or plugin-qualified ``<plugin>:<skill>``) to a monitored name."""
    name = str(raw or "").strip()
    if not name:
        return None
    if name in skills:
        return name
    if ":" in name:
        bare = name.split(":", 1)[1]
        if bare in skills:
            return bare
    return None


def _is_prompt_record(raw: Mapping[str, Any]) -> bool:
    """True when a user-typed record is a real prompt, not a tool result or injected meta text.

    Claude Code writes every tool result back as a ``type: "user"`` record whose
    content is a list of ``tool_result`` blocks, and injects skill bodies and
    command output as ``isMeta`` user records; neither starts a new turn.
    """
    if raw.get("isMeta") is True:
        return False
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else raw
    content = msg.get("content") if isinstance(msg, Mapping) else None
    if isinstance(content, list) and content:
        if all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return False
    return True


def _as_string_tuple(value: Any) -> tuple[str, ...]:
    """A YAML/JSON list of strings, or one scalar string, as a tuple (never split per character)."""
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


def _extract_user_prompt(ev: TranscriptEvent) -> str:
    """Extract prompt text from user event across Claude Code and synthetic formats."""
    raw = ev.raw_record if isinstance(ev.raw_record, dict) else {}
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else raw
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            parts: list[str] = []
            for b in content:
                if isinstance(b, dict):
                    if b.get("type") == "text" and "text" in b:
                        parts.append(str(b["text"]))
                    elif b.get("type") == "text" and "content" in b:
                        parts.append(str(b["content"]))
                elif isinstance(b, str):
                    parts.append(b)
            if parts:
                return " ".join(parts)
        for key in ("text", "prompt"):
            val = msg.get(key)
            if isinstance(val, str):
                return val

    # Fallback to top-level raw fields
    for key in ("text", "prompt", "content"):
        val = raw.get(key)
        if isinstance(val, str):
            return val
    return ""


def mine_skill_opportunities(
    projects_dir: Path | None,
    skills: Mapping[str, SkillAsset],
    sessions_dir: Path | None = None,
) -> SkillOpportunityReport:
    """Mine skill opportunities and invocation patterns across transcript files."""
    stats = {name: [0, 0, 0, 0, 0] for name in skills}  # [opp, inv, lba, missed, post]
    mined_situations: list[dict[str, Any]] = []

    if projects_dir and projects_dir.is_dir():
        for _, tpath in discover_transcript_files(projects_dir):
            try:
                events = list(stream_transcript_events(tpath))
            except Exception:
                continue

            current_turn_skills: set[str] = set()
            turn_actions_seen_after_opp: set[str] = set()
            turn_invoked_skills: set[str] = set()
            invoked_in_session: set[str] = set()
            post_load_tools: dict[str, int] = {name: 0 for name in skills}

            for ev in events:
                raw = ev.raw_record if isinstance(ev.raw_record, dict) else {}
                raw_type = str(raw.get("type") or raw.get("event") or "")
                ev_type = ev.event_type

                is_user = (
                    ev_type in ("user", "user_turn", "human")
                    or raw_type in ("user", "user_turn", "human")
                ) and _is_prompt_record(raw)

                if is_user:
                    text = _extract_user_prompt(ev)
                    # Close the previous turn: an opportunity with no invocation
                    # in its own turn is missed.
                    for s_name in current_turn_skills - turn_invoked_skills:
                        stats[s_name][3] += 1
                    # Reset turn-level tracking on each new user turn
                    current_turn_skills = set()
                    turn_actions_seen_after_opp = set()
                    turn_invoked_skills = set()

                    if text:
                        for s_name, skill in skills.items():
                            if match_distinctive_strings(
                                text, skill.distinctive_strings
                            ):
                                stats[s_name][0] += 1
                                current_turn_skills.add(s_name)
                                mined_situations.append(
                                    {
                                        "id": f"mined_{len(mined_situations) + 1:04d}",
                                        "prompt": text,
                                        "expected_skills": [s_name],
                                        "source_file": str(tpath.name),
                                    }
                                )

                # Extract tool call blocks from assistant messages or flat tool_use records
                tool_blocks: list[dict[str, Any]] = []
                if ev_type in ("assistant", "message") or raw_type in (
                    "assistant",
                    "message",
                ):
                    msg = (
                        raw.get("message")
                        if isinstance(raw.get("message"), dict)
                        else raw
                    )
                    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                        for b in msg["content"]:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                tool_blocks.append(b)
                elif ev_type == "tool_use" or raw_type == "tool_use":
                    tool_blocks.append(raw)

                for b in tool_blocks:
                    tool_name = str(b.get("name") or "")
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}

                    # Check if Skill tool or direct skill name invocation
                    if tool_name == "Skill":
                        sk_str = _resolve_skill_name(inp.get("skill"), skills)
                        if sk_str is not None:
                            if sk_str not in turn_invoked_skills:
                                turn_invoked_skills.add(sk_str)
                                invoked_in_session.add(sk_str)
                                stats[sk_str][1] += 1
                                if (
                                    sk_str in current_turn_skills
                                    and sk_str not in turn_actions_seen_after_opp
                                ):
                                    stats[sk_str][2] += 1  # loaded_before_action
                    elif tool_name in skills:
                        sk_str = tool_name
                        if sk_str not in turn_invoked_skills:
                            turn_invoked_skills.add(sk_str)
                            invoked_in_session.add(sk_str)
                            stats[sk_str][1] += 1
                            if (
                                sk_str in current_turn_skills
                                and sk_str not in turn_actions_seen_after_opp
                            ):
                                stats[sk_str][2] += 1  # loaded_before_action
                    else:
                        for s_name in current_turn_skills:
                            if s_name not in turn_invoked_skills:
                                turn_actions_seen_after_opp.add(s_name)
                            else:
                                post_load_tools[s_name] += 1

                # Check explicit invoked_skills events
                if (
                    ev_type in ("invoked_skills", "skill_invocation")
                    or raw_type in ("invoked_skills", "skill_invocation")
                    or "invoked_skills" in raw
                ):
                    sk_list = raw.get("skills") or raw.get("invoked_skills") or []
                    if isinstance(sk_list, list):
                        for sk in sk_list:
                            sk_str = _resolve_skill_name(sk, skills)
                            if sk_str is not None:
                                if sk_str not in turn_invoked_skills:
                                    turn_invoked_skills.add(sk_str)
                                    invoked_in_session.add(sk_str)
                                    stats[sk_str][1] += 1
                                    if (
                                        sk_str in current_turn_skills
                                        and sk_str not in turn_actions_seen_after_opp
                                    ):
                                        stats[sk_str][2] += 1  # loaded_before_action

            # Close the session's last turn.
            for s_name in current_turn_skills - turn_invoked_skills:
                stats[s_name][3] += 1
            for s_name in skills:
                stats[s_name][4] += post_load_tools.get(s_name, 0)

    result_stats = {
        name: SkillOpportunityStat(
            name=name,
            opportunities=v[0],
            invoked=v[1],
            loaded_before_action=v[2],
            missed_opportunities=v[3],
            post_load_tool_calls=v[4],
        )
        for name, v in stats.items()
    }

    return SkillOpportunityReport(
        skills=result_stats,
        unmonitored_skills=(),
        mined_situations=tuple(mined_situations),
    )
