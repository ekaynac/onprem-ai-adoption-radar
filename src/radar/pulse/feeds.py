"""RSS 2.0 feeds from the Pulse view: one per lane plus a combined feed.

Only TOP items go in (hidden and uncertain never reach a reader's feed), newest
sighting first, so a reader sees each item once when it first qualifies.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


FEED_LIMIT = 50
FEED_FILES = {
    None: "pulse.xml",
    "model": "pulse-models.xml",
    "paper": "pulse-papers.xml",
    "repo": "pulse-repos.xml",
    "news": "pulse-news.xml",
}


def render_feed(view: dict[str, Any], lane: str | None, base_url: str) -> str:
    rows = [
        row for section in view["lanes"] if lane in (None, section["lane"])
        for row in section["items"]
    ]
    rows.sort(key=lambda r: r["first_seen"], reverse=True)
    title = "AI Radar Pulse" + (f" — {_lane_title(view, lane)}" if lane else "")
    link = base_url.rstrip("/") + "/" if base_url else ""
    generated = datetime.fromisoformat(view["generated_at"])
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{escape(link)}</link>",
        "<description>New models, papers, repositories and news for AI developers, "
        "triaged and ranked by the on-prem AI radar.</description>",
        f"<lastBuildDate>{format_datetime(generated)}</lastBuildDate>",
    ]
    for row in rows[:FEED_LIMIT]:
        why = "; ".join(row["reasons"])
        description = (row.get("summary") or "") + (f" [{why}]" if why else "")
        parts += [
            "<item>",
            f"<title>{escape(_prefix(row) + row['title'])}</title>",
            f"<link>{escape(row['url'])}</link>",
            f'<guid isPermaLink="false">{escape(row["id"])}</guid>',
            f"<pubDate>{format_datetime(datetime.fromisoformat(row['first_seen']))}</pubDate>",
            f"<category>{escape(row['lane'])}</category>",
            f"<description>{escape(description.strip())}</description>",
            "</item>",
        ]
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


def write_feeds(view: dict[str, Any], out_dir: Path, base_url: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for lane, name in FEED_FILES.items():
        path = out_dir / name
        path.write_text(render_feed(view, lane, base_url), encoding="utf-8")
        written.append(path)
    return written


def _lane_title(view: dict[str, Any], lane: str) -> str:
    return next(s["title"] for s in view["lanes"] if s["lane"] == lane)


def _prefix(row: dict[str, Any]) -> str:
    return {"model": "[model] ", "paper": "[paper] ", "repo": "[repo] ", "news": ""}[row["lane"]]
