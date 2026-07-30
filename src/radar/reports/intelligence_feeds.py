"""Atom, RSS, and JSON Feed renderers over one event identity."""

from __future__ import annotations

import json
from xml.sax.saxutils import escape

from radar.intelligence.events import IntelligenceEvent


def _validate_public(events: list[IntelligenceEvent]) -> None:
    if any(event.workspace_id is not None for event in events):
        raise ValueError("Public feeds cannot contain workspace-scoped events")


def filter_intelligence_events(
    events: list[IntelligenceEvent],
    *,
    event_types: set[str] | None = None,
    categories: set[str] | None = None,
    lifecycles: set[str] | None = None,
    lanes: set[str] | None = None,
    platforms: set[str] | None = None,
    watchlist: set[str] | None = None,
) -> list[IntelligenceEvent]:
    """Apply transport-independent channel filters to event metadata."""

    def includes(event: IntelligenceEvent) -> bool:
        data = event.data
        return all(
            (
                not event_types or event.type in event_types,
                not categories or data.get("category") in categories,
                not lifecycles or data.get("to") in lifecycles,
                not lanes or data.get("lane") in lanes,
                not platforms
                or bool(platforms.intersection(data.get("platforms", []))),
                not watchlist or event.subject_id in watchlist,
            )
        )

    return [event for event in events if includes(event)]


def render_intelligence_atom(
    events: list[IntelligenceEvent],
    base_url: str,
) -> str:
    _validate_public(events)
    entries = "".join(
        f"<entry><id>{escape(event.id)}</id><title>{escape(event.type)}</title>"
        f"<updated>{event.occurred_at.isoformat()}</updated>"
        f"<link href=\"{escape(base_url)}/releases/{escape(event.subject_id)}\"/>"
        "</entry>"
        for event in events
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>On-Prem Intelligence</title>"
        f"{entries}</feed>"
    )


def render_intelligence_rss(
    events: list[IntelligenceEvent],
    base_url: str,
) -> str:
    _validate_public(events)
    items = "".join(
        f"<item><guid>{escape(event.id)}</guid>"
        f"<title>{escape(event.type)}</title>"
        f"<link>{escape(base_url)}/releases/{escape(event.subject_id)}</link>"
        "</item>"
        for event in events
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def render_intelligence_json_feed(
    events: list[IntelligenceEvent],
    base_url: str,
) -> str:
    _validate_public(events)
    return json.dumps(
        {
            "version": "https://jsonfeed.org/version/1.1",
            "title": "On-Prem Intelligence",
            "home_page_url": base_url,
            "items": [
                {
                    "id": event.id,
                    "url": f"{base_url}/releases/{event.subject_id}",
                    "title": event.type,
                    "date_published": event.occurred_at.isoformat(),
                    "_event": event.model_dump(mode="json"),
                }
                for event in events
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
