"""The published site: the built frontend, ``data/pulse.v1.json`` and the RSS feeds.

``data/pulse.v1.json`` is Pulse's public contract: the site renders it, the
homelab worker validates and reads it, and any future consumer (for example
InfraMedic's knowledge layer) should do the same instead of reaching into
``data/pulse/``. Its schema is pinned by ``view.validate_view``.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from radar.pulse.feeds import write_feeds
from radar.pulse.view import build_pulse_view, validate_view


VIEW_PATH = Path("data") / "pulse.v1.json"


def export_site(root: Path, out_dir: Path, frontend_dir: Path, now: datetime,
                base_url: str = "") -> dict[str, int]:
    """Write the static site into ``out_dir`` (created; existing files overwritten)."""
    index = frontend_dir / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"Built frontend missing: {index} (run `npm run build` first)")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(frontend_dir, out_dir, dirs_exist_ok=True)
    shutil.copy2(index, out_dir / "404.html")  # GitHub Pages fallback

    view = validate_view(build_pulse_view(root, now))  # never publish what readers would reject
    target = out_dir / VIEW_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
    feeds = write_feeds(view, out_dir, base_url)
    return {
        "items": sum(len(lane["items"]) + len(lane["uncertain"]) + lane["hidden_count"]
                     for lane in view["lanes"]),
        "feeds": len(feeds),
    }
