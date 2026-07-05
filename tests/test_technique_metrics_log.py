"""Append-only technique metrics log (the CI-persistence backbone)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.technique_metrics_log import append_metrics, load_metrics
from radar.storage.technique_metrics_store import TechniqueMetrics, TechniqueMetricsStore


def _row(run: str, count: int) -> TechniqueMetrics:
    return TechniqueMetrics(
        technique_id="spec-dec", run_id=run,
        observed_at=datetime(2026, 7, 5, 10, 0, tzinfo=UTC),
        citation_count=count, citation_source="s2", resolved_impls=3, ring="adopt",
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "technique-metrics.jsonl"

    append_metrics(path, [_row("run-1", 100)])
    append_metrics(path, [_row("run-2", 120)])
    append_metrics(path, [])  # no-op

    rows = load_metrics(path)
    assert [r.run_id for r in rows] == ["run-1", "run-2"]
    assert rows[1].citation_count == 120


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_metrics(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "technique-metrics.jsonl"
    append_metrics(path, [_row("run-1", 100)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert len(load_metrics(path)) == 1


def test_store_is_empty_flips_after_record(tmp_path: Path):
    store = TechniqueMetricsStore(tmp_path / "radar.db")
    store.initialize()

    assert store.is_empty() is True
    store.record([_row("run-1", 100)])
    assert store.is_empty() is False
