"""Trending detection: velocity + new + assembly (pure, deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from radar.discovery.trending_detect import (
    NEW_WINDOW_DAYS,
    TRENDING_WINDOWS,
    build_trending,
    is_new,
    star_velocity,
)
from radar.discovery.trending_entities import Lane, TrendingObservation


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         created: str = "2026-06-01") -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
        topics=["llm"], license="Apache-2.0",
    )


def test_velocity_over_window():
    rows = [_obs("a/b", 100, 1), _obs("a/b", 250, 4)]  # +150 over 3 days
    assert star_velocity(rows, NOW) == 50.0


def test_velocity_none_with_single_observation():
    assert star_velocity([_obs("a/b", 100, 1)], NOW) is None


def test_velocity_ignores_rows_outside_window():
    rows = [_obs("a/b", 10, 1), _obs("a/b", 400, 5), _obs("a/b", 460, 8)]
    # window = 7 days back from 2026-07-08 → 07-01 inclusive; all three qualify.
    # earliest in-window is day 1 (10), latest day 8 (460): +450 over 7 days
    assert star_velocity(rows, NOW) == round(450 / 7, 1)


def test_velocity_none_on_zero_span():
    rows = [_obs("a/b", 100, 4), _obs("a/b", 120, 4)]  # same day
    assert star_velocity(rows, NOW) is None


def test_is_new_boundary():
    assert is_new(NOW - timedelta(days=NEW_WINDOW_DAYS - 1), NOW) is True
    assert is_new(NOW - timedelta(days=NEW_WINDOW_DAYS + 1), NOW) is False


def test_build_trending_groups_and_sorts():
    observations = [
        _obs("slow/repo", 500, 1), _obs("slow/repo", 520, 4),         # vel low
        _obs("fast/repo", 100, 1), _obs("fast/repo", 400, 4),         # vel high
        _obs("solo/repo", 900, 4),                                     # vel None
    ]
    entries = build_trending(observations, NOW)

    assert [e.repo for e in entries] == ["fast/repo", "slow/repo", "solo/repo"]
    fast = entries[0]
    assert fast.velocity_per_day == 100.0
    assert fast.stars == 400  # latest row wins for current state
    assert fast.first_seen == "2026-07-01"
    assert entries[2].velocity_per_day is None  # solo → sorts last


def test_build_trending_latest_row_supplies_lane_and_license():
    observations = [
        _obs("x/y", 100, 1, lane=Lane.BROADER),
        _obs("x/y", 200, 4, lane=Lane.ONPREM),  # lane can change; latest wins
    ]
    entry = build_trending(observations, NOW)[0]
    assert entry.lane == Lane.ONPREM and entry.license == "Apache-2.0"


def test_build_trending_marks_new_repo():
    entry = build_trending([
        _obs("new/repo", 60, 6, created="2026-07-01"),
        _obs("new/repo", 90, 7, created="2026-07-01"),
    ], NOW)[0]
    assert entry.is_new is True


def test_velocity_window_parameter():
    now = datetime(2026, 7, 28, 7, 0, tzinfo=UTC)
    rows = [_obs("a/r", 100, 8), _obs("a/r", 400, 27)]  # 20d and 1d before `now`
    assert star_velocity(rows, now) is None            # default 7d window: only 1 row qualifies
    v30 = star_velocity(rows, now, window_days=30)
    assert v30 is not None and v30 > 0


def test_trending_windows_mapping():
    assert TRENDING_WINDOWS == {"7d": 7, "30d": 30, "90d": 90}


def test_build_trending_threads_window_days():
    observations = [_obs("a/r", 100, 8), _obs("a/r", 400, 27)]
    now = datetime(2026, 7, 28, 7, 0, tzinfo=UTC)

    entries_7d = build_trending(observations, now)
    entries_30d = build_trending(observations, now, window_days=30)

    assert entries_7d[0].velocity_per_day is None
    assert entries_30d[0].velocity_per_day is not None and entries_30d[0].velocity_per_day > 0


def test_build_trending_negative_velocity_sorts_before_unknown():
    observations = [
        _obs("solo/repo", 900, 4),                            # velocity None (1 obs)
        _obs("dying/repo", 200, 1), _obs("dying/repo", 100, 4),  # -33.3/day
    ]
    entries = build_trending(observations, NOW)

    # A real (negative) velocity must precede an unknown one.
    assert [e.repo for e in entries] == ["dying/repo", "solo/repo"]
    assert entries[0].velocity_per_day is not None and entries[0].velocity_per_day < 0
    assert entries[1].velocity_per_day is None
