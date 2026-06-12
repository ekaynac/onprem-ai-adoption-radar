"""Static-site export for GitHub Pages.

The dashboard is a live FastAPI app; Pages needs plain files. This renders a
single self-contained ``index.html`` (no server-relative links, embedded CSS)
from the latest persisted cards, so a CI job can scan and publish a snapshot.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.models import DecisionCard, Ring

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TRY_RINGS = {Ring.ADOPT, Ring.PILOT}


def render_static_site(
    cards: list[DecisionCard],
    out_dir: Path,
    generated_at: datetime,
) -> Path:
    """Render a self-contained index.html into ``out_dir`` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("static_index.html")
    try_this_week = [c for c in cards if c.ring in _TRY_RINGS]
    html = template.render(
        cards=cards,
        try_this_week=try_this_week,
        generated_at=generated_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    index = out_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    return index
