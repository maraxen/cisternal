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
    """A single skill asset entry."""

    name: str
    description: str = ""
    body: str = ""


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
