"""Append-only JSONL log of model metrics (makes download velocity durable)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.model_metrics_log import append_model_metrics, load_model_metrics
from radar.storage.model_metrics_store import ModelMetrics


def _m(model_id: str, downloads: int, day: int) -> ModelMetrics:
    return ModelMetrics(model_id=model_id, run_id="r1",
                        observed_at=datetime(2026, 7, day, tzinfo=UTC),
                        downloads=downloads, ring="pilot", hardware_tier="workstation")


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "model-metrics.jsonl"
    append_model_metrics(path, [_m("qwen3-0.6b", 100, 1)])
    append_model_metrics(path, [_m("qwen3-0.6b", 180, 4)])
    append_model_metrics(path, [])

    rows = load_model_metrics(path)
    assert [r.downloads for r in rows] == [100, 180]


def test_missing_and_corrupt(tmp_path: Path):
    assert load_model_metrics(tmp_path / "nope.jsonl") == []
    path = tmp_path / "model-metrics.jsonl"
    append_model_metrics(path, [_m("qwen3-0.6b", 100, 1)])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_model_metrics(path)) == 1


def test_non_utf8_bytes_are_skipped(tmp_path: Path):
    path = tmp_path / "model-metrics.jsonl"
    append_model_metrics(path, [_m("qwen3-0.6b", 100, 1)])
    with path.open("ab") as h:
        h.write(b"\xff\xfe broken\n")
    assert len(load_model_metrics(path)) == 1  # guarded read, no raise
