"""MinimalEmitter — example third-party surface for cisterna.emitters."""

from __future__ import annotations

import json

from cisterna.assets.bundle import AssetBundle
from cisterna.export.base import Emitter


class MinimalEmitter(Emitter):
    def emit(self, bundle: AssetBundle) -> dict[str, str]:
        payload = {
            "name": bundle.metadata.name,
            "version": bundle.metadata.version,
            "commands": [c.name for c in bundle.commands],
        }
        return {"minimal-plugin.json": json.dumps(payload, sort_keys=True)}


def factory(**_kwargs: object) -> Emitter:
    return MinimalEmitter()
