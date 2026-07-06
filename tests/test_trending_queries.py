"""MCP trending query service over the observation store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.mcp_server.trending_queries import TrendingQueryService, load_trending_entries
from radar.storage.trending_observations_log import append_observations


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         created: str = "2026-06-01") -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
        description="d", topics=["llm"], license="MIT",
    )


def _seed(root: Path, rows: list[TrendingObservation]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_load_trending_entries_empty_without_store(tmp_path):
    assert load_trending_entries(tmp_path, NOW) == []


def test_load_trending_entries_guards_corrupt_store(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "trending-observations.jsonl").write_text(
        "{not json}\n", encoding="utf-8"
    )
    # corrupt lines are skipped by load_observations → empty derived list, no raise
    assert load_trending_entries(tmp_path, NOW) == []


def test_list_trending_compact_rows_and_lane_filter(tmp_path):
    _seed(tmp_path, [
        _obs("fast/repo", 100, 1), _obs("fast/repo", 400, 4),
        _obs("broad/repo", 900, 4, lane=Lane.BROADER),
    ])
    svc = TrendingQueryService(tmp_path)

    rows = svc.list_trending(now=NOW)
    assert {r["repo"] for r in rows} == {"fast/repo", "broad/repo"}
    assert rows[0].keys() >= {"repo", "lane", "stars", "velocity_per_day",
                              "is_new", "first_seen", "description", "topics"}

    onprem = svc.list_trending(lane="onprem", now=NOW)
    assert [r["repo"] for r in onprem] == ["fast/repo"]


def test_list_trending_respects_limit(tmp_path):
    _seed(tmp_path, [
        _obs("a/a", 100, 1), _obs("a/a", 500, 4),
        _obs("b/b", 100, 1), _obs("b/b", 300, 4),
    ])
    svc = TrendingQueryService(tmp_path)

    assert len(svc.list_trending(limit=1, now=NOW)) == 1
