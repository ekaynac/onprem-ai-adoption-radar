"""Build per-entity value series from stores/logs and render sparklines."""

from __future__ import annotations

from radar.discovery.trending_entities import TrendingObservation
from radar.storage.metrics_store import ProjectMetrics
from radar.storage.model_metrics_store import ModelMetrics
from radar.web.sparkline import sparkline_svg


def trending_sparklines(
    observations: list[TrendingObservation], limit: int = 14
) -> dict[str, str]:
    """repo -> sparkline SVG of its star counts (last ``limit`` sweeps)."""
    by_repo: dict[str, list[TrendingObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.repo, []).append(obs)
    sparks: dict[str, str] = {}
    for repo, rows in by_repo.items():
        series = [r.stars for r in sorted(rows, key=lambda r: r.observed_at)][-limit:]
        sparks[repo] = sparkline_svg(
            series, label=f"{repo} stars, last {len(series)} sweeps"
        )
    return sparks


def star_sparkline(rows: list[ProjectMetrics]) -> str:
    series = [float(r.stars) for r in rows if r.stars is not None]
    return sparkline_svg(series, label=f"stars, last {len(series)} scans")


def downloads_sparkline(rows: list[ModelMetrics]) -> str:
    series = [float(r.downloads) for r in rows if r.downloads is not None]
    return sparkline_svg(series, label=f"downloads, last {len(series)} scans")
