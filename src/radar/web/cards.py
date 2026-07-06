"""Deterministic Mega-branded SVG social cards (pure strings, zero deps).

Cards use ONLY the Process Blue brand color, a text wordmark, and a safe
sans-serif stack — the Mega brand kit never enters the repo. Two sizes:
Instagram portrait and link-preview OG. A CI step rasterizes PNG siblings.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from radar.reports.digest import WeeklyDigest


PROCESS_BLUE = "#009FDA"
CARD_SIZES: dict[str, tuple[int, int]] = {"portrait": (1080, 1350), "og": (1200, 630)}
WORDMARK = "MEGA"
TAGLINE = "on-prem AI adoption radar"
_FONT = "'Hanken Grotesk', Arial, Helvetica, sans-serif"
_MAX_ROWS = 6


def render_card(headline: str, rows: list[str], size: str) -> str:
    width, height = CARD_SIZES[size]
    band = max(120, height // 8)  # brand header band height (min 120px)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{_FONT}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<rect width="{width}" height="{band}" fill="{PROCESS_BLUE}"/>',
        f'<text x="48" y="{band - 40}" font-size="56" font-weight="700" '
        f'fill="#ffffff">{WORDMARK}</text>',
        f'<text x="48" y="{band + 90}" font-size="52" font-weight="700" '
        f'fill="#111111">{escape(headline)}</text>',
    ]
    first_row_y = band + 180          # first row baseline, below the headline
    row_step = 64                     # vertical gap between rows
    tagline_y = height - 48           # tagline baseline near the bottom
    # only render rows that fit above the tagline (small `og` cards hold fewer)
    fit_rows = max(1, (tagline_y - 40 - first_row_y) // row_step)
    y = first_row_y
    for row in rows[: min(_MAX_ROWS, fit_rows)]:
        parts.append(
            f'<text x="48" y="{y}" font-size="40" fill="#222222">{escape(row)}</text>'
        )
        y += row_step
    parts.append(
        f'<text x="48" y="{height - 48}" font-size="32" '
        f'fill="{PROCESS_BLUE}">{escape(TAGLINE)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _trending_rows(digest: WeeklyDigest) -> list[str]:
    rows = []
    for e in digest.trending_onprem[:3]:
        vel = f"{e.velocity_per_day:+.0f}★/day" if e.velocity_per_day is not None else "new"
        rows.append(f"{e.repo}  {vel}")
    return rows


def _mover_rows(digest: WeeklyDigest) -> list[str]:
    rows = []
    for c in digest.changes[:3]:
        arrow = f"{c.previous_ring} → {c.ring}" if c.previous_ring else c.ring
        rows.append(f"{c.name}  ({c.kind}) {arrow}")
    return rows


def _adopt_rows(digest: WeeklyDigest) -> list[str]:
    """Up to 3 entries that reached the adopt ring this week (across all radars)."""
    rows = []
    for c in digest.changes:
        if c.ring == "adopt" and c.change_type in {"new", "promoted"}:
            rows.append(f"{c.name}  ({c.kind})")
        if len(rows) >= 3:
            break
    return rows


def write_cards(digest: WeeklyDigest, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    specs = [("trending", f"Trending · {digest.label}", _trending_rows(digest))]
    if digest.changes:
        specs.append(("movers", f"Ring changes · {digest.label}", _mover_rows(digest)))
    adopt = _adopt_rows(digest)
    if adopt:
        specs.append(("adopt", f"Reached adopt · {digest.label}", adopt))
    for stem, headline, rows in specs:
        for size in CARD_SIZES:
            path = out_dir / f"{stem}_{size}.svg"
            path.write_text(render_card(headline, rows, size), encoding="utf-8")
            written.append(path)
    return written
