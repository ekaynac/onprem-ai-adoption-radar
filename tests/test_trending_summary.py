"""Index-strip summary of the trending catalog."""

from __future__ import annotations

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.web.trending_summary import TrendingSummary, summarize_trending


def _entry(repo: str, lane: Lane, vel: float | None = 10.0) -> TrendingEntry:
    return TrendingEntry(
        repo=repo, lane=lane, stars=1000, velocity_per_day=vel, is_new=False,
        first_seen="2026-07-01", description="d", topics=["llm"],
    )


def test_summarize_top3_onprem_and_counts():
    entries = [
        _entry("a/1", Lane.ONPREM, 50.0), _entry("a/2", Lane.ONPREM, 40.0),
        _entry("a/3", Lane.ONPREM, 30.0), _entry("a/4", Lane.ONPREM, 20.0),
        _entry("b/1", Lane.BROADER), _entry("b/2", Lane.BROADER),
    ]
    summary = summarize_trending(entries)

    assert [e.repo for e in summary.onprem_top] == ["a/1", "a/2", "a/3"]  # top 3
    assert summary.onprem_count == 4
    assert summary.broader_count == 2
    assert summary.has_trending is True
    assert "4" in summary.one_line


def test_empty_summary_has_no_trending():
    summary = summarize_trending([])

    assert summary == TrendingSummary()
    assert summary.has_trending is False
