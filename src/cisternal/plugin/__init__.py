"""cisternal.plugin — let a tool install its own agent plugin.

Mount the sub-app into a tool's cyclopts CLI::

    from cisternal.plugin import PluginSpec, plugin_app

    app.command(plugin_app(PluginSpec(name="bathos", package="bathos")))

which gives ``bth plugin install|update claude``, ``bth plugin export <surface>
--out DIR`` and ``bth plugin info``. See :mod:`cisternal.plugin.app` for how
the bundle is located (explicit manifest > source checkout > packaged
snapshot) and :mod:`cisternal.plugin.config` for where the shared marketplace
resolves.

Fastmcp-free.
"""

from cisternal.plugin.app import (
    INSTALLABLE_SURFACES,
    BundleSource,
    PluginError,
    PluginSpec,
    load_bundle,
    locate_bundle,
    plugin_app,
)
from cisternal.plugin.config import marketplace_root_source, resolve_marketplace_root

__all__ = [
    "INSTALLABLE_SURFACES",
    "BundleSource",
    "PluginError",
    "PluginSpec",
    "load_bundle",
    "locate_bundle",
    "marketplace_root_source",
    "plugin_app",
    "resolve_marketplace_root",
]
