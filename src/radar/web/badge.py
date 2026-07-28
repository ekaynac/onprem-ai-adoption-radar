"""Shields-style ring/fit badges — self-contained, deterministic SVG.

Badges are earned, never sold: every badge is rendered straight from data the
radar already commits (a project's computed/pinned ring, a model's hardware
tier and minimum-viable quant) — there is no sponsored-placement mechanism,
matching the design spec's "placement cannot be bought" principle
(2026-07-28 differentiation-pass design, §2). Pure and dependency-free, like
``web/cards.py``, so the live dashboard and the static export render byte-
identical SVG for the same inputs.
"""

from __future__ import annotations

from xml.sax.saxutils import escape


# Right-cell background per ring. WCAG AA (>=4.5:1) white-text contrast is the
# authority (see tests/test_badge.py) — these starting values already clear
# it; darken further if a future palette change ever regresses one.
RING_BADGE_COLORS: dict[str, str] = {
    "adopt": "#00719E",
    "pilot": "#005F85",
    "watch": "#8C6200",
    "avoid": "#B93025",
}

_LEFT_FILL = "#555"
_FIT_FILL = "#005F85"
_HEIGHT = 20
_TEXT_Y = 14  # baseline for font-size 11 in a height-20 pill
_FONT_FAMILY = "Verdana,Geneva,DejaVu Sans,sans-serif"
_FONT_SIZE = 11


def _text_width(s: str) -> int:
    """Deterministic width estimate for a text cell (no real font metrics)."""
    return round(len(s) * 6.8) + 12


def _pill_svg(left: str, right: str, right_fill: str, title: str) -> str:
    """Two-cell shields.io-style pill: ``left`` on gray, ``right`` on ``right_fill``.

    Two ``<rect>`` cells + two centered ``<text>`` elements; total width is
    the sum of both cells' estimated widths.
    """
    safe_left = escape(left, {'"': "&quot;"})
    safe_right = escape(right, {'"': "&quot;"})
    safe_title = escape(title, {'"': "&quot;"})
    left_w = _text_width(left)
    right_w = _text_width(right)
    width = left_w + right_w
    left_cx = round(left_w / 2, 1)
    right_cx = round(left_w + right_w / 2, 1)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{_HEIGHT}" '
        f'viewBox="0 0 {width} {_HEIGHT}" role="img" aria-label="{safe_title}">'
        f"<title>{safe_title}</title>"
        f'<rect width="{left_w}" height="{_HEIGHT}" rx="3" fill="{_LEFT_FILL}"/>'
        f'<rect x="{left_w}" width="{right_w}" height="{_HEIGHT}" rx="3" fill="{right_fill}"/>'
        f'<g fill="#ffffff" font-family="{_FONT_FAMILY}" font-size="{_FONT_SIZE}" '
        'text-anchor="middle">'
        f'<text x="{left_cx}" y="{_TEXT_Y}">{safe_left}</text>'
        f'<text x="{right_cx}" y="{_TEXT_Y}">{safe_right}</text>'
        "</g></svg>"
    )


def ring_badge_svg(ring: str) -> str:
    """Two-cell pill: ``on-prem radar | {RING}`` in the ring's brand color."""
    color = RING_BADGE_COLORS[ring]
    return _pill_svg("on-prem radar", ring.upper(), color, f"on-prem radar: {ring}")


def fit_badge_svg(tier: str, quant_format: str | None) -> str:
    """Two-cell pill: ``runs on | {tier} ({quant_format})`` (quant suffix optional)."""
    right = f"{tier} ({quant_format})" if quant_format else tier
    return _pill_svg("runs on", right, _FIT_FILL, f"on-prem radar: runs on {right}")


def badge_markdown(badge_url: str, target_url: str, alt: str) -> str:
    """Copy-ready Markdown embedding ``badge_url`` and linking to ``target_url``."""
    return f"[![{alt}]({badge_url})]({target_url})"
