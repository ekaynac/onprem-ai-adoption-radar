"""Subscribable change feeds (Atom + JSON Feed + RSS) over the ring-change timeline.

Exported alongside the static site so the GitHub Pages deployment becomes
subscribable: a reader or agent can follow ring changes without polling the
dashboard. The same events drive all three formats; RSS 2.0 exists for the
older readers/tools that still prefer ``<rss>`` over Atom.
"""

from __future__ import annotations

from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape

from radar.storage.history_store import ProjectHistoryEvent


JSON_FEED_VERSION = "https://jsonfeed.org/version/1.1"


def _newest_first(events: list[ProjectHistoryEvent]) -> list[ProjectHistoryEvent]:
    return sorted(events, key=lambda e: e.observed_at, reverse=True)


def _title(event: ProjectHistoryEvent) -> str:
    prev = event.previous_ring.value if event.previous_ring else None
    if prev and prev != event.ring.value:
        return f"{event.project}: {prev} → {event.ring.value} ({event.change_type.value})"
    return f"{event.project}: {event.change_type.value} ({event.ring.value})"


def _entry_id(event: ProjectHistoryEvent) -> str:
    return f"{event.run_id}:{event.project}:{event.change_type.value}"


def render_changes_json(
    events: list[ProjectHistoryEvent],
    site_title: str,
) -> dict[str, Any]:
    """JSON Feed 1.1 document of ring changes, newest first."""
    items = [
        {
            "id": _entry_id(event),
            "title": _title(event),
            "content_text": " ".join(event.reasons) or _title(event),
            "date_published": event.observed_at.isoformat(),
            "tags": [event.category.value, event.ring.value],
        }
        for event in _newest_first(events)
    ]
    return {"version": JSON_FEED_VERSION, "title": site_title, "items": items}


def render_changes_atom(
    events: list[ProjectHistoryEvent],
    site_title: str,
    self_url: str,
) -> str:
    """Atom 1.0 feed of ring changes, newest first."""
    ordered = _newest_first(events)
    updated = ordered[0].observed_at.isoformat() if ordered else "1970-01-01T00:00:00+00:00"
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(site_title)}</title>",
        f'  <link rel="self" href="{escape(self_url)}"/>',
        f"  <id>{escape(self_url)}</id>",
        f"  <updated>{updated}</updated>",
    ]
    for event in ordered:
        parts.extend(
            [
                "  <entry>",
                f"    <title>{escape(_title(event))}</title>",
                f"    <id>urn:radar:{escape(_entry_id(event))}</id>",
                f"    <updated>{event.observed_at.isoformat()}</updated>",
                f"    <summary>{escape(' '.join(event.reasons) or _title(event))}</summary>",
                "  </entry>",
            ]
        )
    parts.append("</feed>")
    return "\n".join(parts) + "\n"


def render_changes_rss(
    events: list[ProjectHistoryEvent],
    site_title: str,
    self_url: str,
) -> str:
    """RSS 2.0 feed of ring changes, newest first.

    RSS is the same data as the Atom feed in the format older readers prefer.
    The one wire difference from Atom: RSS timestamps are RFC-822
    (``Fri, 12 Jun 2026 00:00:00 +0000``), not ISO-8601.
    """
    ordered = _newest_first(events)
    build_date = format_datetime(ordered[0].observed_at) if ordered else None
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(site_title)}</title>",
        f"    <link>{escape(self_url)}</link>",
        f"    <description>{escape(site_title)} — ring changes</description>",
        f'    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>',
    ]
    if build_date:
        parts.append(f"    <lastBuildDate>{build_date}</lastBuildDate>")
    for event in ordered:
        parts.extend(
            [
                "    <item>",
                f"      <title>{escape(_title(event))}</title>",
                f"      <description>{escape(' '.join(event.reasons) or _title(event))}</description>",
                f'      <guid isPermaLink="false">urn:radar:{escape(_entry_id(event))}</guid>',
                f"      <pubDate>{format_datetime(event.observed_at)}</pubDate>",
                "    </item>",
            ]
        )
    parts.extend(["  </channel>", "</rss>"])
    return "\n".join(parts) + "\n"
