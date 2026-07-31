"""Derive velocity + sustained-momentum signals from candidate observations (pure)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from radar.storage.model_candidate_log import ModelCandidateObservation


logger = logging.getLogger(__name__)

VELOCITY_WINDOW_DAYS = 7
NEW_WINDOW_DAYS = 14
MIN_MOMENTUM_DAYS = 3
MIN_MOMENTUM_SPAN = 5
MIN_GROWTH_PCT = 25.0
STALE_AFTER_DAYS = 4
EMERGING_LIMIT = 15
MOMENTUM_WINDOW_DAYS = 14


class ModelCandidateEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    hf_repo: str
    name: str
    family: str
    downloads: int
    likes: int = 0
    pipeline_tag: str | None = None
    created_at: str | None = None
    last_modified: str | None = None
    downloads_per_day: float | None
    is_new: bool
    first_seen: str
    last_seen: str
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    is_stale: bool


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
        last_seen = ordered[-1].observed_at.date()
        entries.append(ModelCandidateEntry(
            hf_repo=repo, name=latest.name, family=latest.family,
            downloads=latest.downloads, likes=latest.likes,
            pipeline_tag=latest.pipeline_tag,
            created_at=latest.created_at,
            last_modified=latest.last_modified,
            downloads_per_day=_downloads_per_day(ordered, now),
            is_new=first_seen >= (now - timedelta(days=NEW_WINDOW_DAYS)).date(),
            first_seen=first_seen.isoformat(),
            last_seen=last_seen.isoformat(),
            first_observed_at=ordered[0].observed_at.isoformat(),
            last_observed_at=ordered[-1].observed_at.isoformat(),
            is_stale=last_seen < (now - timedelta(days=STALE_AFTER_DAYS)).date(),
        ))
    return sorted(entries, key=lambda e: (
        e.downloads_per_day is None,
        -(e.downloads_per_day if e.downloads_per_day is not None else 0.0),
        -e.downloads, e.hf_repo,
    ))


def has_sustained_download_momentum(
    observations: list[ModelCandidateObservation], now: datetime
) -> bool:
    recent = [o for o in observations
              if o.observed_at >= now - timedelta(days=MOMENTUM_WINDOW_DAYS)]
    if len(recent) < 2:
        return False
    ordered = sorted(recent, key=lambda r: r.observed_at)
    distinct_days = len({r.observed_at.date() for r in ordered})
    span = (ordered[-1].observed_at.date() - ordered[0].observed_at.date()).days
    if distinct_days < MIN_MOMENTUM_DAYS or span < MIN_MOMENTUM_SPAN:
        return False
    earliest = ordered[0].downloads
    if earliest <= 0:
        return False
    growth_pct = (ordered[-1].downloads - earliest) / earliest * 100
    return growth_pct >= MIN_GROWTH_PCT


def load_emerging_candidates(
    root: Path, now: datetime, *, limit: int = EMERGING_LIMIT
) -> list[ModelCandidateEntry]:
    """Guarded: emerging (untracked, still not seeded) candidates, capped. [] on any failure.

    A promoted model drops out of new sweep observations (the sweep excludes
    seeded repos) but ``build_model_candidates`` still renders every repo ever
    observed — so without this filter a promoted model would show up in both
    "Rising in the catalog" and "Emerging" with a frozen, stale download count.
    This is the I/O boundary for the pure builders above, mirroring
    ``web/hub_sections.load_hub_sections``.
    """
    try:
        from radar.models_radar.seed import load_model_seed
        from radar.storage.model_candidate_log import load_model_candidates

        root = Path(root)
        seed_path = root / "config" / "model-seed.yaml"
        seeded = {(s.hf_repo or "").lower()
                  for s in (load_model_seed(seed_path) if seed_path.exists() else [])
                  if s.hf_repo}
        entries = build_model_candidates(
            load_model_candidates(root / "data" / "model-candidate-observations.jsonl"), now)
        return [e for e in entries if e.hf_repo.lower() not in seeded][:limit]
    except Exception as exc:
        logger.warning("Emerging model candidates unavailable under %s: %s", root, exc)
        return []
