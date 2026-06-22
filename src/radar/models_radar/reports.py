"""Render model movers + report sections from model history/momentum."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import ModelMomentum
from radar.storage.history_store import ChangeType


MAX_TRENDING = 3


def build_model_mover_lines(
    events: list[ModelHistoryEvent], momentums: list[ModelMomentum],
) -> list[str]:
    """Ring changes first, then up to MAX_TRENDING rising models not already shown."""
    lines: list[str] = []
    moved: set[str] = set()
    for ev in events:
        if ev.change_type == ChangeType.PROMOTED:
            lines.append(f"{ev.model_id}: {ev.previous_ring.value if ev.previous_ring else '?'} "
                         f"→ {ev.ring.value} (promoted)")
            moved.add(ev.model_id)
        elif ev.change_type == ChangeType.DEMOTED:
            lines.append(f"{ev.model_id}: {ev.previous_ring.value if ev.previous_ring else '?'} "
                         f"→ {ev.ring.value} (demoted)")
            moved.add(ev.model_id)
        elif ev.change_type == ChangeType.NEW:
            lines.append(f"{ev.model_id}: new on the radar ({ev.ring.value})")
            moved.add(ev.model_id)
    rising = sorted(
        (m for m in momentums if m.direction == "rising" and m.model_id not in moved),
        key=lambda m: m.downloads_growth_pct or 0.0, reverse=True,
    )
    for m in rising[:MAX_TRENDING]:
        pct = f" downloads {m.downloads_growth_pct:+.1f}%" if m.downloads_growth_pct is not None else ""
        lines.append(f"{m.model_id}: rising —{pct} across recent scans")
    return lines


def render_model_report(entries: list[ModelEntry], mover_lines: list[str], title: str) -> str:
    """Render markdown report with movers and model table."""
    out = [f"# {title}", ""]
    if mover_lines:
        out.append("## Movers")
        out += [f"- {line}" for line in mover_lines]
        out.append("")
    out.append("## Models")
    for e in sorted(entries, key=lambda m: (m.hardware_tier.value, m.id)):
        ring = e.ring.value if e.ring else "-"
        out.append(f"- **{e.name}** ({e.family}) · `{ring}` · {e.hardware_tier.value}"
                   + (f" · {e.license}" if e.license else ""))
    out.append("")
    return "\n".join(out)


def _event_title(ev: Any) -> str:
    """Format event as title line."""
    prev = ev.previous_ring.value if ev.previous_ring else None
    if prev:
        return f"{ev.model_id}: {prev} → {ev.ring.value} ({ev.change_type.value})"
    return f"{ev.model_id}: {ev.change_type.value} ({ev.ring.value})"


def model_events_to_feed_json(events: list[Any], site_title: str) -> dict[str, Any]:
    """Convert model events to JSON Feed 1.1 format."""
    items = []
    for ev in sorted(events, key=lambda e: e.observed_at, reverse=True):
        items.append({
            "id": f"urn:radar-model:{ev.model_id}:{ev.run_id}",
            "title": _event_title(ev),
            "content_text": "; ".join(ev.reasons) or _event_title(ev),
            "date_published": ev.observed_at.isoformat(),
            "tags": [ev.family, ev.ring.value],
        })
    return {"version": "https://jsonfeed.org/version/1.1", "title": f"{site_title} — Models",
            "items": items}


def model_events_to_feed_atom(events: list[Any], site_title: str, self_url: str) -> str:
    """Convert model events to Atom feed format."""
    rows = sorted(events, key=lambda e: e.observed_at, reverse=True)
    updated = rows[0].observed_at.isoformat() if rows else datetime.now().astimezone().isoformat()
    entries_xml = "".join(
        f"<entry><title>{_xml_escape(_event_title(ev))}</title>"
        f"<id>urn:radar-model:{ev.model_id}:{ev.run_id}</id>"
        f"<updated>{ev.observed_at.isoformat()}</updated>"
        f"<summary>{_xml_escape('; '.join(ev.reasons) or _event_title(ev))}</summary></entry>"
        for ev in rows
    )
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<feed xmlns="http://www.w3.org/2005/Atom"><title>{_xml_escape(site_title)} — Models</title>'
            f'<link rel="self" href="{_xml_escape(self_url)}"/><updated>{updated}</updated>'
            f'{entries_xml}</feed>')


def _xml_escape(s: str) -> str:
    """Escape string for XML text content and attributes."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
