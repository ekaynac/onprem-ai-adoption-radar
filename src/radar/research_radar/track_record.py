"""Track record: how long after publication did the radar flag each technique?

The honest, computable-today slice of the spec's track-record idea. The
predictive metric — how early a flag preceded a technique's first mainstream
implementation — needs months of accumulated implementation history and stays
deferred; callers should say so.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from radar.research_radar.entities import PaperRole, TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent


class TrackRecordRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    technique_id: str
    paper_published: str | None = None
    first_flagged: str
    lag_days: int | None = None
    ring: str | None = None
    implementations: int = 0


def build_track_record(
    entries: list[TechniqueEntry], events: list[TechniqueHistoryEvent],
) -> list[TrackRecordRow]:
    first_flag: dict[str, datetime] = {}
    for event in events:
        seen = first_flag.get(event.technique_id)
        if seen is None or event.observed_at < seen:
            first_flag[event.technique_id] = event.observed_at
    rows: list[TrackRecordRow] = []
    for entry in entries:
        flagged = first_flag.get(entry.id)
        if flagged is None:
            continue
        published = _canonical_published(entry)
        rows.append(TrackRecordRow(
            technique_id=entry.id,
            paper_published=published,
            first_flagged=flagged.date().isoformat(),
            lag_days=_lag_days(published, flagged),
            ring=entry.ring.value if entry.ring else None,
            implementations=len(entry.resolved_implementations),
        ))
    return sorted(rows, key=lambda r: (r.lag_days is None, r.lag_days or 0,
                                       r.technique_id))


def _canonical_published(entry: TechniqueEntry) -> str | None:
    for paper in entry.papers:
        if paper.role == PaperRole.CANONICAL:
            return paper.published
    return None


def _lag_days(published: str | None, flagged: datetime) -> int | None:
    if not published:
        return None
    normalized = f"{published}-01" if len(published) == 7 else published
    try:
        start = datetime.fromisoformat(normalized).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (flagged - start).days
