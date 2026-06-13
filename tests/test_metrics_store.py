"""Tests for the per-scan project metrics store (evidence foundation)."""

from __future__ import annotations

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
