"""Tests for the per-scan project metrics store (evidence foundation)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from radar.storage.metrics_store import MetricsStore, ProjectMetrics


def _metrics(project: str, day: int, stars: int | None = None, **kwargs) -> ProjectMetrics:
    return ProjectMetrics(
        project=project,
        run_id=f"run-{day}",
        observed_at=datetime(2026, 6, day, tzinfo=UTC),
        stars=stars,
        **kwargs,
    )


def test_record_and_latest_round_trip(tmp_path: Path):
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()

    store.record([_metrics("vLLM", 10, stars=1000, license="Apache-2.0")])

    latest = store.latest("vLLM")
    assert latest is not None
    assert latest.stars == 1000
    assert latest.license == "Apache-2.0"
    assert store.latest("Unknown") is None


def test_latest_returns_most_recent_by_observed_at(tmp_path: Path):
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metrics("vLLM", 12, stars=1200)])
    store.record([_metrics("vLLM", 10, stars=1000)])  # older row inserted later

    latest = store.latest("vLLM")

    assert latest is not None
    assert latest.stars == 1200


def test_latest_excluding_run_skips_current_scan(tmp_path: Path):
    """During a scan we need the PREVIOUS scan's row, not the one just written."""
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metrics("vLLM", 10, stars=1000)])
    store.record([_metrics("vLLM", 12, stars=1200)])

    previous = store.latest("vLLM", exclude_run="run-12")

    assert previous is not None
    assert previous.stars == 1000


def test_history_for_returns_rows_oldest_first(tmp_path: Path):
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_metrics("vLLM", 12, stars=1200), _metrics("vLLM", 10, stars=1000)])

    rows = store.history_for("vLLM")

    assert [r.stars for r in rows] == [1000, 1200]


def test_record_empty_is_noop(tmp_path: Path):
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([])
    assert store.latest("vLLM") is None


def test_paper_mentions_round_trip(tmp_path):
    store = MetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record(
        [
            ProjectMetrics(
                project="vLLM",
                run_id="r1",
                observed_at=datetime(2026, 6, 19, tzinfo=UTC),
                paper_mentions=7,
            )
        ]
    )
    latest = store.latest("vLLM")
    assert latest is not None
    assert latest.paper_mentions == 7


def test_initialize_adds_paper_mentions_to_legacy_table(tmp_path):
    db = tmp_path / "radar.db"
    # Simulate a pre-existing table WITHOUT the new column.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE project_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project TEXT NOT NULL, run_id TEXT NOT NULL, observed_at TEXT NOT NULL, "
            "stars INTEGER, forks INTEGER, open_issues INTEGER, license TEXT, "
            "pushed_at TEXT, releases_in_window INTEGER NOT NULL DEFAULT 0, "
            "downloads_weekly INTEGER, hn_mentions INTEGER, advisories_open INTEGER, "
            "advisories_max_severity TEXT)"
        )
    store = MetricsStore(db)
    store.initialize()  # must add the missing column, not crash
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(project_metrics)")}
    assert "paper_mentions" in cols
