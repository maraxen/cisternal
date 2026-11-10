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

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from cisternal.plugin.config import marketplace_root_source, resolve_marketplace_root

if TYPE_CHECKING:
    from cisternal.plugin.app import (
        INSTALLABLE_SURFACES,
        BundleSource,
        PluginError,
        PluginSpec,
        load_bundle,
        locate_bundle,
        plugin_app,
    )

_APP_EXPORTS = {
    "INSTALLABLE_SURFACES",
    "BundleSource",
    "PluginError",
    "PluginSpec",
    "load_bundle",
    "locate_bundle",
    "plugin_app",
}

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


def __getattr__(name: str) -> Any:
    if name in _APP_EXPORTS:
        mod = importlib.import_module(".app", __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
