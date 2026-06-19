"""Tests for source-health tracking (dead-feed detection)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from radar.storage.source_health_store import (
    DEFAULT_STALE_WINDOW,
    SourceHealthStore,
)


BASE = datetime(2026, 6, 1, tzinfo=UTC)


def _at(day: int) -> datetime:
    return BASE + timedelta(days=day)


def test_record_and_counts_round_trip(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()

    store.record("run-1", _at(1), {"github-vllm": 3, "rss-dead": 0})

    assert store.latest_counts()["github-vllm"] == 3
    assert store.latest_counts()["rss-dead"] == 0


def test_stale_after_n_consecutive_zero_scans(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    for day in range(1, 4):  # 3 consecutive zero scans for rss-dead
        store.record(f"run-{day}", _at(day), {"github-vllm": 2, "rss-dead": 0})

    stale = store.stale_source_ids(window=3)

    assert "rss-dead" in stale
    assert "github-vllm" not in stale


def test_not_stale_with_fewer_than_window_scans(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    store.record("run-1", _at(1), {"rss-dead": 0})
    store.record("run-2", _at(2), {"rss-dead": 0})

    assert store.stale_source_ids(window=3) == set()


def test_recent_activity_clears_stale(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    store.record("run-1", _at(1), {"rss-flaky": 0})
    store.record("run-2", _at(2), {"rss-flaky": 0})
    store.record("run-3", _at(3), {"rss-flaky": 5})  # came back to life

    assert store.stale_source_ids(window=3) == set()


def test_latest_counts_uses_most_recent_run(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    store.record("run-2", _at(2), {"s": 9})
    store.record("run-1", _at(1), {"s": 1})  # older, inserted later

    assert store.latest_counts()["s"] == 9


def test_empty_store_has_no_stale(tmp_path: Path):
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    assert store.stale_source_ids() == set()
    assert store.latest_counts() == {}


def test_default_window_tolerates_low_frequency_feed(tmp_path: Path):
    """A feed silent for fewer than the default window of scans isn't stale."""
    store = SourceHealthStore(tmp_path / "radar.db")
    store.initialize()
    for day in range(1, DEFAULT_STALE_WINDOW):  # one short of the window
        store.record(f"run-{day}", _at(day), {"rss-weekly": 0})

    assert store.stale_source_ids() == set()

    store.record(f"run-{DEFAULT_STALE_WINDOW}", _at(DEFAULT_STALE_WINDOW), {"rss-weekly": 0})
    assert "rss-weekly" in store.stale_source_ids()


def test_accepts_str_path(tmp_path: Path):
    store = SourceHealthStore(str(tmp_path / "radar.db"))
    store.initialize()
    store.record("run-1", _at(1), {"s": 1})

    assert store.latest_counts()["s"] == 1
