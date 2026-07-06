"""persist_model_scan appends metrics to the committed log when a path is given."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models_radar.entities import ModelEntry
from radar.models_radar.pipeline import persist_model_scan
from radar.storage.model_metrics_log import load_model_metrics


def _entry() -> ModelEntry:
    # Minimal valid ModelEntry — adjust required fields to the real schema if needed;
    # the load-bearing assertion is that a metrics row lands in the log.
    return ModelEntry.model_validate({
        "id": "qwen3-0.6b", "name": "Qwen3-0.6B", "family": "Qwen3",
        "hf_downloads": 1234, "quants": [],
    })


def test_persist_appends_to_metrics_log(tmp_path: Path):
    log = tmp_path / "data" / "model-metrics.jsonl"
    persist_model_scan(
        [_entry()], "r1", datetime(2026, 7, 6, tzinfo=UTC),
        tmp_path / "data" / "radar.db", tmp_path / "data" / "model-history.jsonl",
        metrics_log_path=log,
    )

    rows = load_model_metrics(log)
    assert len(rows) == 1 and rows[0].model_id == "qwen3-0.6b"
    assert rows[0].downloads == 1234


def test_persist_without_log_path_is_unchanged(tmp_path: Path):
    # back-compat: omitting metrics_log_path writes no log, doesn't raise
    persist_model_scan(
        [_entry()], "r1", datetime(2026, 7, 6, tzinfo=UTC),
        tmp_path / "data" / "radar.db", tmp_path / "data" / "model-history.jsonl",
    )
    assert not (tmp_path / "data" / "model-metrics.jsonl").exists()
