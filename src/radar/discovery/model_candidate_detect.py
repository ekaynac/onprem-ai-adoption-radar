"""Derive velocity + sustained-momentum signals from candidate observations (pure)."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from radar.storage.model_candidate_log import ModelCandidateObservation


VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14
MIN_MOMENTUM_DAYS = 3
MIN_MOMENTUM_SPAN = 5
MIN_GROWTH_PCT = 25.0


class ModelCandidateEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    hf_repo: str
    name: str
    family: str
    downloads: int
    downloads_per_day: float | None
    is_new: bool
    first_seen: str


def _downloads_per_day(rows: list[ModelCandidateObservation], now: datetime) -> float | None:
    cutoff_date = now.date() - timedelta(days=VELOCITY_WINDOW_DAYS)
    in_window = sorted((r for r in rows if r.observed_at.date() >= cutoff_date),
                       key=lambda r: r.observed_at)
    if len(in_window) < 2:
        return None
    span = (in_window[-1].observed_at.date() - in_window[0].observed_at.date()).days
    if span <= 0:
        return None
    return round((in_window[-1].downloads - in_window[0].downloads) / span, 1)


def build_model_candidates(
    observations: list[ModelCandidateObservation], now: datetime
) -> list[ModelCandidateEntry]:
    by_repo: dict[str, list[ModelCandidateObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.hf_repo, []).append(obs)
    entries: list[ModelCandidateEntry] = []
    for repo, rows in by_repo.items():
        ordered = sorted(rows, key=lambda r: r.observed_at)
        latest = ordered[-1]
        first_seen = ordered[0].observed_at.date()
        entries.append(ModelCandidateEntry(
            hf_repo=repo, name=latest.name, family=latest.family,
            downloads=latest.downloads,
            downloads_per_day=_downloads_per_day(ordered, now),
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
        ))
    return sorted(entries, key=lambda e: (
        e.downloads_per_day is None,
        -(e.downloads_per_day if e.downloads_per_day is not None else 0.0),
        -e.downloads, e.hf_repo,
    ))


def has_sustained_download_momentum(observations: list[ModelCandidateObservation]) -> bool:
    if len(observations) < 2:
        return False
    ordered = sorted(observations, key=lambda r: r.observed_at)
    distinct_days = len({r.observed_at.date() for r in ordered})
    span = (ordered[-1].observed_at.date() - ordered[0].observed_at.date()).days
    if distinct_days < MIN_MOMENTUM_DAYS or span < MIN_MOMENTUM_SPAN:
        return False
    earliest = ordered[0].downloads
    if earliest <= 0:
        return False
    growth_pct = (ordered[-1].downloads - earliest) / earliest * 100
    return growth_pct >= MIN_GROWTH_PCT
