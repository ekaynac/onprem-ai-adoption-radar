"""Append-only JSONL log of trending observations (mirror of technique_metrics_log)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.trending_observations_log import append_observations, load_observations


def _obs(repo: str, stars: int, at: str) -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=Lane.ONPREM, stars=stars,
        observed_at=datetime.fromisoformat(at),
        repo_created_at=datetime(2026, 6, 20, tzinfo=UTC),
        topics=["llm"], license="MIT",
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "trending-observations.jsonl"

    append_observations(path, [_obs("a/b", 100, "2026-07-01T07:00:00+00:00")])
    append_observations(path, [_obs("a/b", 130, "2026-07-02T07:00:00+00:00")])
    append_observations(path, [])  # no-op

    rows = load_observations(path)
    assert [r.stars for r in rows] == [100, 130]
    assert rows[1].license == "MIT"


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_observations(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "trending-observations.jsonl"
    append_observations(path, [_obs("a/b", 100, "2026-07-01T07:00:00+00:00")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert len(load_observations(path)) == 1
