from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models_radar.entities import (
    HardwareTier,
    ModelEntry,
    Openness,
    QuantVariant,
)
from radar.models_radar.pipeline import persist_model_scan, score_entries


NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _entry(mid, **kw):
    base = dict(id=mid, name=mid, family="F", params_total=8_000_000_000,
                openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                hf_downloads=1_000_000,
                quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                     est_memory_gb_4k=8.0, source="hf:x")])
    base.update(kw)
    return ModelEntry(**base)


def test_score_entries_sets_ring_and_score():
    [e] = score_entries([_entry("qwen3-8b")])
    assert e.ring is not None and e.score is not None and e.score_breakdown is not None


def test_persist_records_metrics_and_new_event_then_no_event(tmp_path: Path):
    db = tmp_path / "radar.db"
    hist = tmp_path / "model-history.jsonl"
    entries = score_entries([_entry("qwen3-8b")])
    events1 = persist_model_scan(entries, "r1", NOW, db, hist)
    assert len(events1) == 1 and events1[0].change_type.value == "new"
    # second identical scan → ring unchanged → no new event, metrics still recorded
    events2 = persist_model_scan(entries, "r2", NOW, db, hist)
    assert events2 == []
    from radar.storage.model_metrics_store import ModelMetricsStore
    store = ModelMetricsStore(db)
    assert store.latest("qwen3-8b").ring == entries[0].ring.value
