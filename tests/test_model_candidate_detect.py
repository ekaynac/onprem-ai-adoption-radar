"""Model-candidate detection: velocity, new, sustained momentum (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.model_candidate_detect import (
    build_model_candidates,
    has_sustained_download_momentum,
)
from radar.storage.model_candidate_log import ModelCandidateObservation


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _obs(repo: str, downloads: int, day: int, created: int = 1) -> ModelCandidateObservation:
    return ModelCandidateObservation(
        hf_repo=repo, name=repo.split("/")[-1], family=repo.split("/")[0],
        downloads=downloads, likes=1, observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
    )


def test_velocity_over_window():
    rows = [_obs("a/b", 100, 1), _obs("a/b", 400, 4)]   # +300 over 3 days
    entry = build_model_candidates(rows, NOW)[0]
    assert entry.downloads_per_day == 100.0
    assert entry.downloads == 400            # latest row = current
    assert entry.first_seen == "2026-07-01"


def test_velocity_none_single_observation():
    entry = build_model_candidates([_obs("a/b", 100, 1)], NOW)[0]
    assert entry.downloads_per_day is None


def test_ranking_velocity_desc_none_last():
    rows = [_obs("fast/x", 100, 1), _obs("fast/x", 700, 4),   # +200/day
            _obs("slow/y", 100, 1), _obs("slow/y", 130, 4),   # +10/day
            _obs("solo/z", 900, 4)]                            # None
    entries = build_model_candidates(rows, NOW)
    assert [e.hf_repo for e in entries] == ["fast/x", "slow/y", "solo/z"]


def test_is_new_flag():
    # first_seen 2026-07-06 → within 14 days of NOW(07-08)
    entry = build_model_candidates([_obs("n/m", 60, 6), _obs("n/m", 90, 7)], NOW)[0]
    assert entry.is_new is True


def test_sustained_momentum_requires_days_span_growth():
    strong = [_obs("a/b", 100, 1), _obs("a/b", 110, 4), _obs("a/b", 130, 6)]  # 3 days, span 5, +30%
    assert has_sustained_download_momentum(strong) is True

    too_few_days = [_obs("a/b", 100, 1), _obs("a/b", 200, 6)]                 # 2 days
    assert has_sustained_download_momentum(too_few_days) is False

    flat = [_obs("a/b", 100, 1), _obs("a/b", 101, 4), _obs("a/b", 102, 6)]    # +2% < 25%
    assert has_sustained_download_momentum(flat) is False
