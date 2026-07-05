"""Derive trending signals from repeated observations (pure, no I/O).

GitHub cannot tell us growth, so velocity is the star delta across the
observation window. Day one of the system yields no velocity (one row per
repo); it fills in from day two.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from radar.discovery.trending_entities import TrendingEntry, TrendingObservation


VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14

def star_velocity(rows: list[TrendingObservation], now: datetime) -> float | None:
    """Stars/day across in-window rows; None with <2 rows or a zero day-span."""
    cutoff = now - timedelta(days=VELOCITY_WINDOW_DAYS)
    in_window = sorted(
        (r for r in rows if r.observed_at >= cutoff), key=lambda r: r.observed_at
    )
    if len(in_window) < 2:
        return None
    span_days = (in_window[-1].observed_at.date() - in_window[0].observed_at.date()).days
    if span_days <= 0:
        return None
    return round((in_window[-1].stars - in_window[0].stars) / span_days, 1)


def is_new(repo_created_at: datetime, now: datetime) -> bool:
    return repo_created_at >= now - timedelta(days=NEW_WINDOW_DAYS)


def build_trending(
    observations: list[TrendingObservation], now: datetime
) -> list[TrendingEntry]:
    by_repo: dict[str, list[TrendingObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.repo, []).append(obs)
    entries: list[TrendingEntry] = []
    for repo, rows in by_repo.items():
        ordered = sorted(rows, key=lambda r: r.observed_at)
        latest = ordered[-1]
        entries.append(TrendingEntry(
            repo=repo, lane=latest.lane, stars=latest.stars,
            velocity_per_day=star_velocity(ordered, now),
            is_new=is_new(latest.repo_created_at, now),
            first_seen=ordered[0].observed_at.date().isoformat(),
            description=latest.description, topics=latest.topics, license=latest.license,
        ))
    return sorted(entries, key=lambda e: (
        e.velocity_per_day is None,
        -(e.velocity_per_day if e.velocity_per_day is not None else 0.0),
        -e.stars,
        e.repo,
    ))
