"""Research→production timeline: papers + ring history merged chronologically.

ISO-prefix dates ("2022-11", "2026-07-03") sort correctly with plain string
comparison, so no date parsing is needed — a deliberate simplification that
keeps the builder pure and total.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent


class TimelineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str  # "YYYY-MM" or "YYYY-MM-DD"
    label: str
    kind: str  # "paper" | "ring"


def build_technique_timeline(
    entry: TechniqueEntry, events: list[TechniqueHistoryEvent],
) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    for paper in entry.papers:
        if not paper.published:
            continue
        items.append(TimelineItem(
            date=paper.published,
            label=f"{paper.role.value} paper: {paper.title}",
            kind="paper",
        ))
    for event in events:
        if event.technique_id != entry.id:
            continue
        prev = f"{event.previous_ring.value} → " if event.previous_ring else ""
        items.append(TimelineItem(
            date=event.observed_at.date().isoformat(),
            label=f"{prev}{event.ring.value} ({event.change_type.value})",
            kind="ring",
        ))
    return sorted(items, key=lambda item: item.date)
