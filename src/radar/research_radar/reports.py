"""Render technique movers + report sections (mirror of models_radar/reports.py)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.momentum import MomentumSignal
from radar.storage.history_store import ChangeType


MAX_TRENDING = 3


def build_technique_mover_lines(
    events: list[TechniqueHistoryEvent], momentums: list[MomentumSignal],
) -> list[str]:
    """Ring changes first, then up to MAX_TRENDING rising techniques not already shown."""
    lines: list[str] = []
    moved: set[str] = set()
    for ev in events:
        prev = ev.previous_ring.value if ev.previous_ring else "?"
        if ev.change_type == ChangeType.PROMOTED:
            lines.append(f"{ev.technique_id}: {prev} → {ev.ring.value} (promoted)")
            moved.add(ev.technique_id)
        elif ev.change_type == ChangeType.DEMOTED:
            lines.append(f"{ev.technique_id}: {prev} → {ev.ring.value} (demoted)")
            moved.add(ev.technique_id)
        elif ev.change_type == ChangeType.NEW:
            lines.append(f"{ev.technique_id}: new on the radar ({ev.ring.value})")
            moved.add(ev.technique_id)
    rising = sorted(
        (m for m in momentums if m.direction == "rising" and m.technique_id not in moved),
        key=lambda m: m.citation_growth_pct or 0.0, reverse=True,
    )
    for momentum in rising[:MAX_TRENDING]:
        pct = (f" citations {momentum.citation_growth_pct:+.1f}%"
               if momentum.citation_growth_pct is not None else "")
        lines.append(f"{momentum.technique_id}: rising —{pct} {momentum.note}".rstrip())
    return lines


def render_technique_report(
    entries: list[TechniqueEntry], mover_lines: list[str], title: str,
) -> str:
    out = [f"# {title}", ""]
    if mover_lines:
        out.append("## Movers")
        out += [f"- {line}" for line in mover_lines]
        out.append("")
    out.append("## Techniques")
    for entry in sorted(entries, key=lambda e: (e.domain.value, e.id)):
        ring = entry.ring.value if entry.ring else "-"
        impls = len(entry.resolved_implementations)
        citations = entry.citation_count if entry.citation_count is not None else "?"
        out.append(
            f"- **{entry.name}** ({entry.domain.value}) · `{ring}` · "
            f"{impls} impl(s) · {citations} citations"
        )
    out.append("")
    return "\n".join(out)


def _feed_event_title(ev: Any) -> str:
    """Format a technique ring-change event as a feed title line."""
    prev = ev.previous_ring.value if ev.previous_ring else None
    if prev:
        return f"{ev.technique_id}: {prev} → {ev.ring.value} ({ev.change_type.value})"
    return f"{ev.technique_id}: {ev.change_type.value} ({ev.ring.value})"


def technique_events_to_feed_json(events: list[Any], site_title: str) -> dict[str, Any]:
    """Convert technique events to JSON Feed 1.1 format (newest-first)."""
    items = []
    for ev in sorted(events, key=lambda e: e.observed_at, reverse=True):
        items.append({
            "id": f"urn:radar-technique:{ev.technique_id}:{ev.run_id}",
            "title": _feed_event_title(ev),
            "content_text": "; ".join(ev.reasons) or _feed_event_title(ev),
            "date_published": ev.observed_at.isoformat(),
            "tags": [ev.domain.value, ev.ring.value],
        })
    return {"version": "https://jsonfeed.org/version/1.1",
            "title": f"{site_title} — Research", "items": items}


def technique_events_to_feed_atom(events: list[Any], site_title: str, self_url: str) -> str:
    """Convert technique events to an Atom feed (newest-first)."""
    rows = sorted(events, key=lambda e: e.observed_at, reverse=True)
    updated = rows[0].observed_at.isoformat() if rows else datetime.now().astimezone().isoformat()
    entries_xml = "".join(
        f"<entry><title>{_xml_escape(_feed_event_title(ev))}</title>"
        f"<id>urn:radar-technique:{ev.technique_id}:{ev.run_id}</id>"
        f"<updated>{ev.observed_at.isoformat()}</updated>"
        f"<summary>{_xml_escape('; '.join(ev.reasons) or _feed_event_title(ev))}</summary></entry>"
        for ev in rows
    )
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{_xml_escape(site_title)} — Research</title>"
            f'<link rel="self" href="{_xml_escape(self_url)}"/><updated>{updated}</updated>'
            f"{entries_xml}</feed>")


def _xml_escape(s: str) -> str:
    """Escape string for XML text content and attributes."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
