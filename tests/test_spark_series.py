"""Series extraction feeding the sparkline helper."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.metrics_store import ProjectMetrics
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.spark_series import downloads_sparkline, star_sparkline, trending_sparklines


def _obs(repo: str, stars: int, day: int) -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=Lane.ONPREM, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
        description="", topics=[], license="MIT",
    )


def test_trending_sparklines_grouped_and_ordered():
    obs = [_obs("a/r", 300, 3), _obs("a/r", 100, 1), _obs("a/r", 200, 2),
           _obs("b/r", 50, 1), _obs("b/r", 60, 2)]  # b/r: only 2 points
    sparks = trending_sparklines(obs)
    assert "<svg" in sparks["a/r"]
    assert sparks["b/r"] == ""


def test_trending_sparklines_respect_limit():
    obs = [_obs("a/r", 100 + d, d) for d in range(1, 20)]
    spark_all = trending_sparklines(obs, limit=14)
    # 14 points -> 14 coordinate pairs in the polyline
    assert spark_all["a/r"].count(",") >= 14


def test_star_and_download_sparklines_skip_none():
    rows = [ProjectMetrics(project="p", run_id=f"r{i}",
                           observed_at=datetime(2026, 7, i + 1, tzinfo=UTC),
                           stars=s)
            for i, s in enumerate([100, None, 120, 130])]
    assert "<svg" in star_sparkline(rows)

    mrows = [ModelMetrics(model_id="m", run_id=f"r{i}",
                          observed_at=datetime(2026, 7, i + 1, tzinfo=UTC),
                          downloads=d)
             for i, d in enumerate([10, 20, None])]
    assert downloads_sparkline(mrows) == ""  # only 2 usable points
