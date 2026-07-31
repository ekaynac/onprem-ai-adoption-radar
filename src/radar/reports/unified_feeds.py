"""One backward-compatible public feed over radar and intelligence events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from radar.intelligence.events import IntelligenceEvent
from radar.storage.history_store import ProjectHistoryEvent
from radar.web.slugs import project_slug


class FeedContinuityError(RuntimeError):
    """Backing history exists but no public feed item could be projected."""


@dataclass(frozen=True)
class UnifiedFeedItem:
    id: str
    title: str
    url: str
    summary: str
    occurred_at: datetime
    kind: Literal["project_ring", "intelligence_lifecycle"]


def _project_title(event: ProjectHistoryEvent) -> str:
    previous = event.previous_ring.value if event.previous_ring else None
    if previous and previous != event.ring.value:
        return (
            f"{event.project}: {previous} → {event.ring.value} "
            f"({event.change_type.value})"
        )
    return f"{event.project}: {event.change_type.value} ({event.ring.value})"


def collect_unified_feed_items(
    project_events: list[ProjectHistoryEvent],
    intelligence_events: list[IntelligenceEvent],
    *,
    base_url: str,
) -> list[UnifiedFeedItem]:
    base = base_url.rstrip("/")
    items = [
        UnifiedFeedItem(
            id=f"{event.run_id}:{event.project}:{event.change_type.value}",
            title=_project_title(event),
            url=f"{base}/project_{project_slug(event.project)}.html",
            summary=" ".join(event.reasons) or _project_title(event),
            occurred_at=event.observed_at,
            kind="project_ring",
        )
        for event in project_events
    ]
    items.extend(
        UnifiedFeedItem(
            id=event.id,
            title=event.type,
            url=f"{base}/#/catalog/{event.subject_id}",
            summary=(
                f"{event.subject_id} moved from "
                f"{event.data.get('from') or 'untracked'} to "
                f"{event.data.get('to') or event.type}"
            ),
            occurred_at=event.occurred_at,
            kind="intelligence_lifecycle",
        )
        for event in intelligence_events
        if event.workspace_id is None
    )
    unique = {item.id: item for item in items}
    return sorted(
        unique.values(),
        key=lambda item: (-item.occurred_at.timestamp(), item.id),
    )


def write_unified_feeds(
    out_dir: Path,
    *,
    project_events: list[ProjectHistoryEvent],
    intelligence_events: list[IntelligenceEvent],
    site_title: str,
    base_url: str,
    backing_event_count: int | None = None,
    limit: int = 100,
) -> None:
    """Write the three stable public feed filenames from one merged item list."""

    items = collect_unified_feed_items(
        project_events,
        intelligence_events,
        base_url=base_url,
    )[:limit]
    backing = (
        backing_event_count
        if backing_event_count is not None
        else len(project_events) + len(intelligence_events)
    )
    if backing and not items:
        raise FeedContinuityError(
            "backing history is non-empty but the unified public feed has no items"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/")
    rss_url = f"{base}/changes.rss" if base else "changes.rss"
    atom_url = f"{base}/changes.xml" if base else "changes.xml"
    _write_rss(out_dir / "changes.rss", items, site_title, rss_url)
    _write_atom(out_dir / "changes.xml", items, site_title, atom_url)
    (out_dir / "changes.json").write_text(
        json.dumps(
            {
                "version": "https://jsonfeed.org/version/1.1",
                "title": site_title,
                "home_page_url": base,
                "items": [
                    {
                        "id": item.id,
                        "url": item.url,
                        "title": item.title,
                        "content_text": item.summary,
                        "date_published": item.occurred_at.isoformat(),
                        "tags": [item.kind],
                    }
                    for item in items
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_rss(
    path: Path,
    items: list[UnifiedFeedItem],
    site_title: str,
    self_url: str,
) -> None:
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(site_title)}</title>",
        f"    <link>{escape(self_url)}</link>",
        f"    <description>{escape(site_title)} — radar and lifecycle changes</description>",
        f'    <atom:link href="{escape(self_url)}" rel="self" '
        'type="application/rss+xml"/>',
    ]
    if items:
        parts.append(f"    <lastBuildDate>{format_datetime(items[0].occurred_at)}</lastBuildDate>")
    for item in items:
        parts.extend(
            [
                "    <item>",
                f"      <title>{escape(item.title)}</title>",
                f"      <link>{escape(item.url)}</link>",
                f"      <description>{escape(item.summary)}</description>",
                f'      <guid isPermaLink="false">{escape(item.id)}</guid>',
                f"      <pubDate>{format_datetime(item.occurred_at)}</pubDate>",
                "    </item>",
            ]
        )
    parts.extend(["  </channel>", "</rss>"])
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _write_atom(
    path: Path,
    items: list[UnifiedFeedItem],
    site_title: str,
    self_url: str,
) -> None:
    updated = items[0].occurred_at.isoformat() if items else "1970-01-01T00:00:00+00:00"
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(site_title)}</title>",
        f'  <link rel="self" href="{escape(self_url)}"/>',
        f"  <id>{escape(self_url)}</id>",
        f"  <updated>{updated}</updated>",
    ]
    for item in items:
        parts.extend(
            [
                "  <entry>",
                f"    <title>{escape(item.title)}</title>",
                f"    <id>{escape(item.id)}</id>",
                f"    <updated>{item.occurred_at.isoformat()}</updated>",
                f'    <link href="{escape(item.url)}"/>',
                f"    <summary>{escape(item.summary)}</summary>",
                "  </entry>",
            ]
        )
    parts.append("</feed>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
