"""Stub prelude for the consumer modules that the wire-onboarding guide imports.

``docs/guides/wire-onboarding.md`` shows worked examples that import code from
other projects (redsox, alphex, myxcel, maraxiom, contemplex). ``tests/test_docs_examples.py``
executes those examples verbatim, so every consumer import has to resolve to
something. :func:`install` puts the stubs below into ``sys.modules`` under the
module paths the examples import, through a ``monkeypatch`` so each test gets
fresh modules and nothing leaks.

What each stub provides, and the real code it mirrors:

* ``redsox.config.load_config``, ``redsox.core.guard.enforce_no_sibling_parity_leak``
  (a no-op), ``redsox.core.seams.derive_seams`` and ``SeamExplosionError`` (a bare
  ``Exception`` subclass, spec A15).
* ``alphex._render._render`` and ``alphex._surface`` (``catalog``, ``describe``,
  ``classify``, ``table``, ``lint``, ``POLICIES``). ``catalog`` rows carry the keys
  ``_list_fmt`` reads: ``name``, ``size``, ``offset``, ``specials``, ``warnings``.
* ``myxcel.MyxcelError`` (``exit_code = 1``) and ``ConfigError`` (``exit_code = 2``),
  spec A21.
* ``contemplex.errors``: the full ``ErrorCode`` ``StrEnum`` and ``ContemplexError``,
  mirroring ``contemplex/src/contemplex/errors.py:6-22``, with the three subclasses
  the tests raise (``SessionNotFound``, ``GateBlocked``, ``StagingFailed``).
* ``maraxiom.mcp_server.mcp``: a :class:`RecordingServer`, a stand-in server that
  ``wire()`` accepts (``add_tool``) and that remembers the tools it was given.

Stub behaviour is keyed on the input, so a test picks the path it wants without
patching: a config path containing ``explode`` makes ``derive_seams`` raise
``SeamExplosionError`` (``explode-report`` attaches a report object, the optional
``exc.report`` of spec A15); a path containing ``missing`` makes ``load_config``
raise ``FileNotFoundError``.
"""

from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from enum import StrEnum
from types import SimpleNamespace
from typing import Any

import pytest

# --------------------------------------------------------------------------- redsox


class SeamExplosionError(Exception):
    """Bare ``Exception`` subclass with no report attribute (spec A15)."""


@dataclass
class SeamExplosionReport:
    """Stand-in for ``redsox.core.seams.SeamExplosionReport`` (``format_text``)."""

    message: str

    def format_text(self) -> str:
        return self.message


def load_config(path: Any) -> SimpleNamespace:
    text = str(path)
    if "missing" in text:
        raise FileNotFoundError(text)
    return SimpleNamespace(
        path=text,
        sibling_parity_governed=["sibling_a"],
        target_package="redsox_target",
        explode="explode" in text,
        with_report="explode-report" in text,
    )


def enforce_no_sibling_parity_leak(governed: Any, target_package: Any) -> None:
    """No-op, as the T6 spec requires."""


def derive_seams(cfg: SimpleNamespace) -> list[dict[str, Any]]:
    if cfg.explode:
        exc = SeamExplosionError("seam explosion: 4096 seams exceed the cap")
        if cfg.with_report:
            exc.report = SeamExplosionReport(  # type: ignore[attr-defined]
                "REPORT: 4096 seams, cap 1024"
            )
        raise exc
    return [{"id": 1, "name": "seam-one"}, {"id": 2, "name": "seam-two"}]


# --------------------------------------------------------------------------- alphex

POLICIES = ("raise", "unknown", "gap", "mask")

CATALOG: list[dict[str, Any]] = [
    {
        "name": "dna",
        "size": 4,
        "offset": 0,
        "specials": {"gap": 4},
        "warnings": [],
    },
    {
        "name": "protein20",
        "size": 20,
        "offset": 4,
        "specials": {},
        "warnings": ["unused letters"],
    },
]


def _render(result: Any) -> str:
    """Stand-in for alphex's hand renderer: a visibly non-JSON text form."""
    return "RENDERED " + json.dumps(result, sort_keys=True)


def _build_surface() -> types.ModuleType:
    surface = types.ModuleType("alphex._surface")
    surface.POLICIES = POLICIES  # type: ignore[attr-defined]
    surface.LINT_FINDINGS = []  # type: ignore[attr-defined]

    def catalog() -> list[dict[str, Any]]:
        return [dict(row) for row in CATALOG]

    def describe(name: str) -> dict[str, Any]:
        return {"name": name, "size": 4}

    def classify(src: str, dst: str) -> dict[str, Any]:
        return {"src": src, "dst": dst, "relation": "subset"}

    def table(src: str, dst: str, policy: str) -> dict[str, Any]:
        return {"src": src, "dst": dst, "policy": policy, "table": [0, 1, 2, 3]}

    def lint() -> list[dict[str, Any]]:
        return list(surface.LINT_FINDINGS)  # type: ignore[attr-defined]

    surface.catalog = catalog  # type: ignore[attr-defined]
    surface.describe = describe  # type: ignore[attr-defined]
    surface.classify = classify  # type: ignore[attr-defined]
    surface.table = table  # type: ignore[attr-defined]
    surface.lint = lint  # type: ignore[attr-defined]
    return surface


# --------------------------------------------------------------------------- myxcel


class MyxcelError(Exception):
    """Base error with an integer ``exit_code`` class attribute (spec A21)."""

    exit_code = 1


class ConfigError(MyxcelError):
    exit_code = 2


# --------------------------------------------------------------------------- contemplex


class ErrorCode(StrEnum):
    """Mirrors ``contemplex/errors.py:6-16``."""

    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    CORRUPT_SESSION = "CORRUPT_SESSION"
    PHASE_MISMATCH = "PHASE_MISMATCH"
    INVALID_TASK_TYPE = "INVALID_TASK_TYPE"
    INVALID_INPUT = "INVALID_INPUT"
    WRITE_FAILED = "WRITE_FAILED"
    GATE_BLOCKED = "GATE_BLOCKED"
    STAGING_FAILED = "STAGING_FAILED"
    INTERNAL = "INTERNAL"


class ContemplexError(Exception):
    """Mirrors ``contemplex/errors.py:19-22``: a string-valued ``code`` and a ``context``."""

    def __init__(
        self, message: str, code: ErrorCode = ErrorCode.INTERNAL, **context: Any
    ):
        super().__init__(message)
        self.code = code
        self.context = context


class SessionNotFound(ContemplexError):
    def __init__(self, session_id: str):
        super().__init__(
            f"Session {session_id} not found",
            ErrorCode.SESSION_NOT_FOUND,
            session_id=session_id,
        )


class GateBlocked(ContemplexError):
    def __init__(self, gate_name: str, reason: str, **ctx: Any):
        super().__init__(
            f"Gate '{gate_name}' blocked: {reason}",
            ErrorCode.GATE_BLOCKED,
            gate_name=gate_name,
            reason=reason,
            **ctx,
        )


class StagingFailed(ContemplexError):
    def __init__(self, detail: str):
        super().__init__(
            f"staging failed: {detail}", ErrorCode.STAGING_FAILED, detail=detail
        )


# --------------------------------------------------------------------------- MCP stand-in


class RecordingServer:
    """A server stand-in accepted by ``wire()``: it records each ``add_tool`` call."""

    def __init__(self, name: str = "docs") -> None:
        self.name = name
        self.tools: dict[str, Any] = {}

    def add_tool(self, tool: Any) -> None:
        self.tools[tool.name] = tool

    def schema(self, tool_name: str) -> dict[str, Any]:
        """The JSON-schema ``parameters`` of a recorded tool."""
        return dict(self.tools[tool_name].parameters)


# --------------------------------------------------------------------------- install


def _module(name: str, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def install(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Install fresh stub modules into ``sys.modules`` and return handles to them.

    Every module is a new object per call, so a test can mutate
    ``alphex._surface.LINT_FINDINGS`` or inspect ``mcp.tools`` without leaking.
    Names are removed again by ``monkeypatch`` at teardown.
    """
    surface = _build_surface()
    mcp = RecordingServer("docs")
    modules = {
        "redsox": _module("redsox"),
        "redsox.core": _module("redsox.core"),
        "redsox.core.guard": _module(
            "redsox.core.guard",
            enforce_no_sibling_parity_leak=enforce_no_sibling_parity_leak,
        ),
        "redsox.core.seams": _module(
            "redsox.core.seams",
            SeamExplosionError=SeamExplosionError,
            derive_seams=derive_seams,
        ),
        "redsox.config": _module("redsox.config", load_config=load_config),
        "alphex": _module("alphex", _surface=surface),
        "alphex._surface": surface,
        "alphex._render": _module("alphex._render", _render=_render),
        "myxcel": _module("myxcel", MyxcelError=MyxcelError, ConfigError=ConfigError),
        "maraxiom": _module("maraxiom"),
        "maraxiom.mcp_server": _module("maraxiom.mcp_server", mcp=mcp),
        "contemplex": _module("contemplex"),
        "contemplex.errors": _module(
            "contemplex.errors",
            ErrorCode=ErrorCode,
            ContemplexError=ContemplexError,
            SessionNotFound=SessionNotFound,
            GateBlocked=GateBlocked,
            StagingFailed=StagingFailed,
        ),
    }
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    # Make the dotted names importable as attributes, as a real package would.
    modules["redsox"].core = modules["redsox.core"]  # type: ignore[attr-defined]
    modules["redsox.core"].guard = modules["redsox.core.guard"]  # type: ignore[attr-defined]
    modules["redsox.core"].seams = modules["redsox.core.seams"]  # type: ignore[attr-defined]
    modules["redsox"].config = modules["redsox.config"]  # type: ignore[attr-defined]
    modules["alphex"]._render = modules["alphex._render"]  # type: ignore[attr-defined]
    modules["maraxiom"].mcp_server = modules["maraxiom.mcp_server"]  # type: ignore[attr-defined]
    modules["contemplex"].errors = modules["contemplex.errors"]  # type: ignore[attr-defined]
    return SimpleNamespace(modules=modules, mcp=mcp, surface=surface)
