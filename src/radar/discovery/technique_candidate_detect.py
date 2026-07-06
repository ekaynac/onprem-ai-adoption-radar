"""Derive upvote velocity + the emerging surface from paper-candidate observations.

Pure builder (``now`` a parameter) plus one guarded loader that reads the
committed store and drops now-tracked papers — a corrupt/absent store degrades
to an empty section, never a raise (mirror of model_candidate_detect).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from radar.storage.technique_candidate_log import TechniqueCandidateObservation


logger = logging.getLogger(__name__)

VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14
STALE_AFTER_DAYS = 4
EMERGING_LIMIT = 15


class TechniqueCandidateEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    arxiv_id: str
    name: str
    upvotes: int
    upvotes_per_day: float | None
    citation_count: int | None
    is_new: bool
    first_seen: str
    last_seen: str
    is_stale: bool


def _upvotes_per_day(rows: list[TechniqueCandidateObservation], now: datetime) -> float | None:
    cutoff_date = now.date() - timedelta(days=VELOCITY_WINDOW_DAYS)
    in_window = sorted((r for r in rows if r.observed_at.date() >= cutoff_date),
                       key=lambda r: r.observed_at)
    if len(in_window) < 2:
        return None
    span = (in_window[-1].observed_at.date() - in_window[0].observed_at.date()).days
    if span <= 0:
        return None
    return round((in_window[-1].upvotes - in_window[0].upvotes) / span, 1)


def build_technique_candidates(
    observations: list[TechniqueCandidateObservation], now: datetime
) -> list[TechniqueCandidateEntry]:
    by_id: dict[str, list[TechniqueCandidateObservation]] = {}
    for obs in observations:
        by_id.setdefault(obs.arxiv_id, []).append(obs)
    entries: list[TechniqueCandidateEntry] = []
    for arxiv_id, rows in by_id.items():
        ordered = sorted(rows, key=lambda r: r.observed_at)
        latest = ordered[-1]
        first_seen = ordered[0].observed_at.date()
        last_seen = ordered[-1].observed_at.date()
        entries.append(TechniqueCandidateEntry(
            arxiv_id=arxiv_id, name=latest.name, upvotes=latest.upvotes,
            upvotes_per_day=_upvotes_per_day(ordered, now),
            citation_count=latest.citation_count,
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
            last_seen=last_seen.isoformat(),
            is_stale=last_seen < (now - timedelta(days=STALE_AFTER_DAYS)).date(),
        ))
    return sorted(entries, key=lambda e: (
        e.upvotes_per_day is None,
        -(e.upvotes_per_day if e.upvotes_per_day is not None else 0.0),
        -(e.citation_count or 0), e.arxiv_id,
    ))


def load_emerging_techniques(
    root: Path, now: datetime, *, limit: int = EMERGING_LIMIT
) -> list[TechniqueCandidateEntry]:
    """Guarded: emerging (untracked, still not in the seed) papers, capped. [] on any failure."""
    try:
        from radar.research_radar.seed import load_technique_seed
        from radar.storage.technique_candidate_log import load_technique_candidates

        root = Path(root)
        seed_path = root / "config" / "technique-seed.yaml"
        tracked = {p.arxiv_id for s in (load_technique_seed(seed_path) if seed_path.exists() else [])
                   for p in s.papers}
        entries = build_technique_candidates(
            load_technique_candidates(root / "data" / "technique-candidate-observations.jsonl"), now)
        return [e for e in entries if e.arxiv_id not in tracked][:limit]
    except Exception as exc:
        logger.warning("Emerging paper candidates unavailable under %s: %s", root, exc)
        return []
