"""Asset bundle data model (spec §1).

All dataclasses are frozen + slotted for hashability and determinism.
Collections are tuples — never lists — so bundles are fully hashable.

AssetBundle.commands is always sorted by name.  Because the dataclass is
frozen, mutation after construction is prohibited.  Sorting is enforced at
construction time via ``object.__setattr__`` in ``__post_init__``.

Design note on sorting approach:
    PEP-557 frozen dataclasses disallow ``self.field = ...`` in __post_init__.
    The canonical escape hatch is ``object.__setattr__(self, "field", value)``,
    which bypasses the frozen guard during the constructor call.  We use this
    so that callers can pass commands in any order and always receive a
    canonically sorted bundle.  This is preferable to a classmethod constructor
    (AssetBundle.build) because it makes the sort invariant unconditional and
    invisible to callers — there is no "wrong" entry point that bypasses sorting.

Fields:
    BundleMetadata:
        name:        Human-readable bundle name (e.g. ``"cisternal"``).
        version:     SemVer string (e.g. ``"1.0.0"``).
        description: Optional description (default ``""``).

    CommandAsset:
        name:        Command name (must be unique within a bundle).
        description: First-paragraph docstring or ``None``.
        body:        Full command body (default ``""``).  Carried for M3.1;
                     NOT emitted in M3 (B1 resolution: names-only manifest).

    McpAsset:
        name:    MCP server identifier.
        command: Argv tuple for the server process.
        env:     Environment variable pairs ``((key, val), ...)``.

    SkillAsset / AgentAsset / HookSpecAsset:
        M3.1a manifest-loaded asset kinds (see rev2 buildable spec).

    AssetBundle:
        metadata:    BundleMetadata.
        commands:    Tuple of CommandAsset, sorted by name at construction.
        mcp_servers: MCP server entries.
        skills:      Tuple of SkillAsset, sorted by name at construction.
        agents:      Tuple of AgentAsset, sorted by name at construction.
        hook_specs:  Tuple of HookSpecAsset, sorted by (event, matcher, script).
        marketplace: Optional MarketplaceAsset (from [plugin.marketplace]).

    LoadReport:
        bundle:     Loaded AssetBundle.
        warnings:   Non-fatal load issues (missing files, parse degrade).
        conflicts:  Composite merge conflict messages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BundleMetadata:
    """Metadata header for an asset bundle."""

    name: str
    version: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class CommandAsset:
    """A single command asset entry."""

    name: str
    description: str | None
    body: str = ""


@dataclass(frozen=True, slots=True)
class McpAsset:
    """A single MCP server entry."""

    name: str
    command: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SkillAsset:
    """A single skill asset entry.

    ``triggers`` (bugfix, cisternal/manifest-skill-export) carries the
    manifest's ``[[plugin.skills]] triggers = [...]`` list through to export,
    so Claude Code's skill-selection heuristics see the same trigger phrases
    the manifest declares. Empty by default — most SKILL.md sources don't set
    it, and omitting it from the exported frontmatter entirely (rather than
    emitting ``triggers: []``) matches existing agent/skill export behavior.

    ``resources`` carries sibling ``references/``, ``scripts/``, and
    ``assets/`` files found next to the manifest-declared SKILL.md, as
    ``(relative_path, content)`` pairs (e.g. ``("references/foo.md", "...")``).
    Previously an emitter wrote only the single SKILL.md body and silently
    dropped everything else in a skill's directory — a documented gap
    (myxcel's marketplace README, "sibling-file export limitation"). Text
    files only: a resource that fails UTF-8 decoding is skipped with a
    warning by the loader rather than raising, matching the rest of this
    module's fail-open convention.
    """

    name: str
    description: str = ""
    body: str = ""
    triggers: tuple[str, ...] = ()
    resources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AgentAsset:
    """A single agent asset entry."""

    name: str
    description: str = ""
    tools: tuple[str, ...] = ()
    model: str | None = None
    body: str = ""


@dataclass(frozen=True, slots=True)
class HookSpecAsset:
    """A hook specification asset entry.

    ``content`` (M13.2) is the hook script's body, populated only when the
    manifest entry sets a ``path`` key (mirrors ``SkillAsset``/``AgentAsset``
    loading). Empty by default — most surfaces (claude/cursor/copilot)
    ignore it and treat ``script`` as a literal command string, matching
    prior behavior exactly. Antigravity is the one surface that uses
    ``content`` when present, to bundle a self-contained ``scripts/<script>``
    file rather than referencing an external path.
    """

    event: str
    matcher: str
    script: str
    tier: str = ""
    surfaces: tuple[str, ...] = ()
    content: str = ""


@dataclass(frozen=True, slots=True)
class MarketplaceAsset:
    """Local Claude Code marketplace metadata for self-installing a plugin.

    When present on a bundle, ``ClaudeEmitter`` renders a
    ``.claude-plugin/marketplace.json`` alongside the plugin bundle, listing
    the plugin itself via ``source: "./"`` — a single-repo, self-contained
    marketplace+plugin pair, installable via ``cisternal assets install``.
    """

    name: str
    owner_name: str = ""
    owner_email: str = ""
    owner_url: str = ""


@dataclass(frozen=True, slots=True)
class AssetBundle:
    """Complete asset bundle with canonical sort invariants at construction.

    Design note: sorting is enforced via ``object.__setattr__`` in
    ``__post_init__`` rather than via a classmethod constructor.  See module
    docstring for rationale.
    """

    metadata: BundleMetadata
    commands: tuple[CommandAsset, ...] = ()
    mcp_servers: tuple[McpAsset, ...] = ()
    skills: tuple[SkillAsset, ...] = ()
    agents: tuple[AgentAsset, ...] = ()
    hook_specs: tuple[HookSpecAsset, ...] = ()
    marketplace: MarketplaceAsset | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "commands",
            tuple(sorted(self.commands, key=lambda c: c.name)),
        )
        object.__setattr__(
            self,
            "skills",
            tuple(sorted(self.skills, key=lambda s: s.name)),
        )
        object.__setattr__(
            self,
            "agents",
            tuple(sorted(self.agents, key=lambda a: a.name)),
        )
        object.__setattr__(
            self,
            "hook_specs",
            tuple(
                sorted(
                    self.hook_specs,
                    key=lambda h: (h.event, h.matcher, h.script),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class LoadReport:
    """Result of an AssetSource load (never-raise convention on load itself)."""

    bundle: AssetBundle
    warnings: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
