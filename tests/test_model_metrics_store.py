from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from radar.storage.model_metrics_store import ModelMetrics, ModelMetricsStore


def _m(model_id, run_id, day, **kw):
    base = dict(model_id=model_id, run_id=run_id,
                observed_at=datetime(2026, 6, day, tzinfo=UTC))
    base.update(kw)
    return ModelMetrics(**base)


def test_record_and_latest_round_trip(tmp_path):
    store = ModelMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_m("qwen3-8b", "r1", 19, downloads=1000, ring="pilot",
                     min_memory_gb=8.4, hardware_tier="laptop")])
    got = store.latest("qwen3-8b")
    assert got.downloads == 1000 and got.ring == "pilot" and got.min_memory_gb == 8.4


def test_latest_excludes_current_run(tmp_path):
    store = ModelMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.record([_m("m", "r1", 18, downloads=100)])
    store.record([_m("m", "r2", 19, downloads=200)])
    assert store.latest("m", exclude_run="r2").downloads == 100


def test_initialize_is_idempotent(tmp_path):
    store = ModelMetricsStore(tmp_path / "radar.db")
    store.initialize()
    store.initialize()  # must not raise
    cols = {r[1] for r in sqlite3.connect(tmp_path / "radar.db").execute(
        "PRAGMA table_info(model_metrics)")}
    assert {"model_id", "downloads", "ring", "min_memory_gb", "hardware_tier"} <= cols
