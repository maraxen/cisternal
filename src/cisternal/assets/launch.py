"""Resolve how a bundle's MCP servers launch on the installing machine.

A plugin installed from a marketplace (GitHub, or the shared local one) gets
the tool's *files*, not the tool's Python package. ``launch = "path"`` keeps
``command`` as written and needs the tool installed already; ``launch = "uvx"``
rewrites it to ``uvx --from <spec> <command...>`` so the server runs the exact
release the plugin was built from. Resolution happens once the bundle's
version is final (:func:`cisternal.assets.composite.merge_registry`), and the
result is plain ``launch = "path"`` -- so it is idempotent and every emitter
just reads ``command``.
"""

from __future__ import annotations

from dataclasses import replace

from cisternal.assets.bundle import AssetBundle, McpAsset

LAUNCH_MODES = ("path", "uvx")

__all__ = ["LAUNCH_MODES", "resolve_mcp_launch", "uvx_spec"]


def uvx_spec(template: str, *, name: str, version: str) -> str:
    """Fill ``{name}``/``{version}`` in a ``uvx --from`` spec (default ``{name}=={version}``).

    A local version suffix (``+<digest>``) is dropped: it never exists on an
    index or as a tag, so a pin carrying it could not resolve.
    """
    public = version.split("+", 1)[0]
    return (template or "{name}=={version}").format(name=name, version=public)


def resolve_mcp_launch(bundle: AssetBundle) -> AssetBundle:
    """Return *bundle* with every ``launch = "uvx"`` server rewritten to a plain command."""
    if not any(s.launch == "uvx" for s in bundle.mcp_servers):
        return bundle
    servers: list[McpAsset] = []
    for srv in bundle.mcp_servers:
        if srv.launch != "uvx":
            servers.append(srv)
            continue
        spec = uvx_spec(srv.uvx_from, name=bundle.metadata.name, version=bundle.metadata.version)
        servers.append(
            replace(srv, command=("uvx", "--from", spec, *srv.command), launch="path", uvx_from="")
        )
    return replace(bundle, mcp_servers=tuple(servers))
