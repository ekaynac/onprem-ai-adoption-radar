"""Inline-SVG sparklines: tiny, deterministic, theme-aware (currentColor).

Static-site constraint: no JS chart libraries, no external assets — the
whole chart is one self-contained <svg> string (spec 2026-07-28 §F2).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from xml.sax.saxutils import escape


_W, _H = 120, 28
_PAD = 4
_MIN_POINTS = 3


def sparkline_svg(values: Sequence[float], *, label: str) -> str:
    """A 120x28 polyline sparkline, or '' below 3 finite points."""
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(finite) < _MIN_POINTS:
        return ""
    lo, hi = min(finite), max(finite)
    span = hi - lo
    step = (_W - 2 * _PAD) / (len(finite) - 1)

    def _y(v: float) -> float:
        if span == 0:
            return _H / 2
        return _H - _PAD - ((v - lo) / span) * (_H - 2 * _PAD)

    points = [
        (round(_PAD + i * step, 2), round(_y(v), 2)) for i, v in enumerate(finite)
    ]
    pts = " ".join(f"{x},{y}" for x, y in points)
    end_x, end_y = points[-1]
    safe_label = escape(label, {'"': "&quot;"})
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{_H}" '
        f'viewBox="0 0 {_W} {_H}" role="img" aria-label="{safe_label}">'
        f"<title>{safe_label}</title>"
        f'<polyline points="{pts}" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{end_x}" cy="{end_y}" r="2" fill="currentColor"/>'
        "</svg>"
    )
