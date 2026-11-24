"""Allowlist SVG sanitizer for ruling packets (spec §5.1).

Rulings render verdict SVGs inside a private claude.ai page. Before an SVG is
embedded it is parsed and rebuilt from an allowlist: disallowed elements are
dropped with their subtrees, event-handler and external-reference attributes
are removed, and anything that cannot be parsed is rejected outright.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

_ALLOWED_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "text",
        "tspan",
        "title",
        "desc",
        "defs",
        "use",
        "symbol",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
        "mask",
        "pattern",
        "marker",
    }
)

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "id",
        "class",
        "x",
        "y",
        "x1",
        "x2",
        "y1",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "width",
        "height",
        "d",
        "points",
        "transform",
        "viewBox",
        "preserveAspectRatio",
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "opacity",
        "font-family",
        "font-size",
        "font-weight",
        "text-anchor",
        "dominant-baseline",
        "offset",
        "stop-color",
        "stop-opacity",
        "gradientUnits",
        "gradientTransform",
        "patternUnits",
        "clip-path",
        "mask",
        "marker-start",
        "marker-mid",
        "marker-end",
        "version",
    }
)


class SvgRejected(ValueError):
    """Raised when SVG content is unparseable or its root is not an SVG element."""


def _local(tag: str) -> tuple[str, str]:
    """Split an ElementTree tag into (namespace, local name)."""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


_URL_RE = re.compile(r"url\(([^)]*)\)", re.IGNORECASE)


def _has_external_url(value: str) -> bool:
    """True if any url(...) in an attribute value points outside this document."""
    for match in _URL_RE.finditer(value):
        target = match.group(1).strip().strip("'\"").strip()
        if not target.startswith("#"):
            return True
    return False


def _attr_allowed(name: str, value: str) -> bool:
    ns, local = _local(name)
    if local.lower().startswith("on"):
        return False
    # Any url(...) in any value must be a same-document fragment, including in style.
    if _has_external_url(value):
        return False
    if local in ("href", "src") or (ns == XLINK_NS and local == "href"):
        # Only same-document fragment references survive.
        return value.strip().startswith("#")
    if ns not in ("", SVG_NS):
        return False
    if local == "style":
        lowered = value.lower()
        return "@import" not in lowered and "expression(" not in lowered
    return local in _ALLOWED_ATTRIBUTES


def _clean(elem: ET.Element) -> ET.Element | None:
    ns, local = _local(elem.tag)
    if ns != SVG_NS or local not in _ALLOWED_ELEMENTS:
        return None
    cleaned = ET.Element(elem.tag)
    for name, value in elem.attrib.items():
        if _attr_allowed(name, value):
            cleaned.set(name, value)
    cleaned.text = elem.text
    for child in list(elem):
        kept = _clean(child)
        if kept is not None:
            kept.tail = child.tail
            cleaned.append(kept)
    return cleaned


def sanitize_svg(svg: str) -> str:
    """Return an allowlist-rebuilt copy of an SVG document.

    Raises:
        SvgRejected: The text does not parse, declares a DTD or entities, or
            its root element is not an SVG element.
    """
    if "<!DOCTYPE" in svg or "<!ENTITY" in svg:
        raise SvgRejected("SVG declares a DTD or entities")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise SvgRejected(f"SVG does not parse: {exc}") from exc

    ns, local = _local(root.tag)
    if ns != SVG_NS or local != "svg":
        raise SvgRejected("root element is not an SVG element")

    cleaned = _clean(root)
    if cleaned is None:  # pragma: no cover - root already validated above
        raise SvgRejected("root element is not allowed")

    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    return ET.tostring(cleaned, encoding="unicode")
