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
        name:        Human-readable bundle name (e.g. ``"cisterna"``).
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
                 Reserved for M3.1 — always empty in M3.

    AssetBundle:
        metadata:    BundleMetadata.
        commands:    Tuple of CommandAsset, sorted by name at construction.
        mcp_servers: Always empty in M3 (reserved forward-compat).
                     No skills/agents/hooks fields (PREMORTEM-1).
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
    """A single MCP server entry (reserved; always empty in M3)."""

    name: str
    command: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AssetBundle:
    """Complete asset bundle; commands are sorted by name at construction.

    Design note: sorting is enforced via ``object.__setattr__`` in
    ``__post_init__`` rather than via a classmethod constructor.  See module
    docstring for rationale.
    """

    metadata: BundleMetadata
    commands: tuple[CommandAsset, ...] = ()
    mcp_servers: tuple[McpAsset, ...] = ()

    def __post_init__(self) -> None:
        # Sort commands by name.  object.__setattr__ is required because the
        # dataclass is frozen and self.commands = ... would raise FrozenInstanceError.
        sorted_commands = tuple(sorted(self.commands, key=lambda c: c.name))
        object.__setattr__(self, "commands", sorted_commands)
